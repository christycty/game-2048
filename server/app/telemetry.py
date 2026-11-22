"""Phoenix traces + Prometheus metrics for suggestion requests.

Traces (OTLP → Phoenix) own LLM forensics. Metrics (`GET /metrics`) own
ops aggregates scrapers can read. Each app owns its tracer, meter, and
Prometheus registry so tests can build more than one app in-process.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from urllib.parse import urlparse

from fastapi.responses import Response
from openinference.semconv.trace import (
    MessageAttributes,
    OpenInferenceLLMProviderValues,
    OpenInferenceMimeTypeValues,
    OpenInferenceSpanKindValues,
    SpanAttributes,
)
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.view import DropAggregation, View
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanProcessor
from opentelemetry.trace import Span, Status, StatusCode
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import Settings

logger = logging.getLogger(__name__)
SERVICE_NAME = "game-2048-server"
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}
# Compose reaches Phoenix on the host at this name.
_DOCKER_HOST_ALIAS = "host.docker.internal"
# Keep the Phoenix tree on suggestion work. /metrics and client beacons are scrape noise.
_EXCLUDED_URLS = "/health,/metrics,/client-events,/docs,/openapi.json,/redoc"
# FastAPI OTel also emits request/response body-size histograms. Tiny fixed JSON
# boards make those panels flat forever — drop at the SDK so scrape == charted.
# Keep duration (API latency) and active_requests (in-flight /suggest under Auto Play).
_DROP_HTTP_BODY_SIZE_VIEWS = (
    View(instrument_name="http.server.request.size", aggregation=DropAggregation()),
    View(instrument_name="http.server.response.size", aggregation=DropAggregation()),
)
# Phoenix places TTFT from this OpenInference event name.
# The call is not streamed; the stamp is load + prompt_eval.
_FIRST_TOKEN_EVENT = "First Token Stream Event"
_GENERATION_DONE_EVENT = "Generation Done"
_DURATION_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20)
_TOKEN_BUCKETS = (1, 4, 16, 64, 256, 1024, 4096, 16384)
# Prometheus text names for GenAI series (dots → underscores; unit "s"
# becomes a `_seconds` suffix; Counter → `_total`).
PROM_OPERATION_DURATION = "gen_ai_client_operation_duration_seconds"
PROM_TOKEN_USAGE = "gen_ai_client_token_usage"
PROM_REQUEST_COUNT = "gen_ai_client_request_count"
PROM_SUGGEST_SOURCE = "suggest_source"
PROM_CLIENT_SUGGEST_OUTCOME = "client_suggest_outcome"
# Outcome label on request_count (success rate = success / total).
REQUEST_OUTCOME_SUCCESS = "success"
REQUEST_OUTCOME_ERROR = "error"
REQUEST_OUTCOME_TIMEOUT = "timeout"
# Browser beacon outcomes (fail / rate_limit; cancel deferred until AbortSignal).
CLIENT_OUTCOME_FAIL = "fail"
CLIENT_OUTCOME_RATE_LIMIT = "rate_limit"

# OpenInference keys used by tests and callers.
OPENINFERENCE_SPAN_KIND = SpanAttributes.OPENINFERENCE_SPAN_KIND
LLM_SYSTEM = SpanAttributes.LLM_SYSTEM
LLM_PROVIDER = SpanAttributes.LLM_PROVIDER
LLM_MODEL_NAME = SpanAttributes.LLM_MODEL_NAME
LLM_INVOCATION_PARAMETERS = SpanAttributes.LLM_INVOCATION_PARAMETERS
LLM_FINISH_REASON = SpanAttributes.LLM_FINISH_REASON
LLM_INPUT_MESSAGE_ROLE = f"{SpanAttributes.LLM_INPUT_MESSAGES}.0.{MessageAttributes.MESSAGE_ROLE}"
LLM_INPUT_MESSAGE_CONTENT = (
    f"{SpanAttributes.LLM_INPUT_MESSAGES}.0.{MessageAttributes.MESSAGE_CONTENT}"
)
LLM_OUTPUT_MESSAGE_ROLE = f"{SpanAttributes.LLM_OUTPUT_MESSAGES}.0.{MessageAttributes.MESSAGE_ROLE}"
LLM_OUTPUT_MESSAGE_CONTENT = (
    f"{SpanAttributes.LLM_OUTPUT_MESSAGES}.0.{MessageAttributes.MESSAGE_CONTENT}"
)
LLM_TOKEN_COUNT_PROMPT = SpanAttributes.LLM_TOKEN_COUNT_PROMPT
LLM_TOKEN_COUNT_COMPLETION = SpanAttributes.LLM_TOKEN_COUNT_COMPLETION
LLM_TOKEN_COUNT_TOTAL = SpanAttributes.LLM_TOKEN_COUNT_TOTAL
LLM_TOKEN_COUNT_CACHE_READ = SpanAttributes.LLM_TOKEN_COUNT_PROMPT_DETAILS_CACHE_READ
INPUT_VALUE = SpanAttributes.INPUT_VALUE
INPUT_MIME_TYPE = SpanAttributes.INPUT_MIME_TYPE
OUTPUT_VALUE = SpanAttributes.OUTPUT_VALUE
OUTPUT_MIME_TYPE = SpanAttributes.OUTPUT_MIME_TYPE
SPAN_KIND_LLM = OpenInferenceSpanKindValues.LLM.value
SPAN_KIND_CHAIN = OpenInferenceSpanKindValues.CHAIN.value


@dataclass(frozen=True)
class LlmMetrics:
    # Scrape series. TTFT / per-token timings stay on span events.
    operation_duration: metrics.Histogram
    token_usage: metrics.Histogram
    request_count: metrics.Counter
    suggest_source: metrics.Counter
    client_suggest_outcome: metrics.Counter


@dataclass(frozen=True)
class _RequestTelemetry:
    tracer: trace.Tracer
    metrics: LlmMetrics


# Per-request binding: a process-global provider would send later apps'
# traces to whichever app was created last.
_request_telemetry: ContextVar[_RequestTelemetry | None] = ContextVar(
    "request_telemetry",
    default=None,
)


def tracer() -> trace.Tracer:
    bound = _request_telemetry.get()
    if bound is not None:
        return bound.tracer
    return trace.get_tracer(SERVICE_NAME)


def llm_metrics() -> LlmMetrics | None:
    bound = _request_telemetry.get()
    if bound is not None:
        return bound.metrics
    return None


class _RequestTelemetryMiddleware:
    """Bind this app's tracer for the request, including the threadpool endpoint."""

    def __init__(self, app: ASGIApp, tracer: trace.Tracer, metrics: LlmMetrics) -> None:
        self.app = app
        self._tracer = tracer
        self._metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = _request_telemetry.set(
            _RequestTelemetry(tracer=self._tracer, metrics=self._metrics)
        )
        try:
            await self.app(scope, receive, send)
        finally:
            _request_telemetry.reset(token)


def traces_url(collector_endpoint: str) -> str:
    """Accept a Phoenix base URL or a full `/v1/traces` path."""
    endpoint = collector_endpoint.rstrip("/")
    if endpoint.endswith("/v1/traces"):
        return endpoint
    return f"{endpoint}/v1/traces"


def exporter_headers(collector_endpoint: str, api_key: str | None) -> dict[str, str] | None:
    """Send the API key only over HTTPS or to a local collector."""
    if not api_key:
        return None
    parsed = urlparse(traces_url(collector_endpoint))
    host = (parsed.hostname or "").lower()
    http_ok = host in _LOOPBACK or host == _DOCKER_HOST_ALIAS
    if parsed.scheme == "https" or (parsed.scheme == "http" and http_ok):
        return {"authorization": f"Bearer {api_key}"}
    logger.warning(
        "Phoenix API key was not sent to %s because the collector URL is not HTTPS or local",
        collector_endpoint,
    )
    return None


def _tag_http_span(span: Span, scope: dict) -> None:
    """Mark the FastAPI server span as CHAIN so Phoenix nests LLM children under it."""
    path = scope.get("path") or ""
    if path in _EXCLUDED_URLS.split(","):
        return
    span.set_attribute(OPENINFERENCE_SPAN_KIND, SPAN_KIND_CHAIN)


def setup_telemetry(
    app,
    settings: Settings,
    span_processor: SpanProcessor | None = None,
) -> TracerProvider:
    """Wire this app's tracer, Prometheus metrics, and FastAPI instrumentation."""
    endpoint = traces_url(settings.phoenix_collector_endpoint)
    resource = Resource.create({"service.name": SERVICE_NAME})
    provider = TracerProvider(resource=resource)
    headers = exporter_headers(endpoint, settings.phoenix_api_key)

    if settings.export_traces:
        if span_processor is None:
            span_processor = BatchSpanProcessor(
                OTLPSpanExporter(endpoint=endpoint, headers=headers)
            )
        provider.add_span_processor(span_processor)

    # Phoenix stays on OTLP traces. Scrapers (Prometheus, Datadog, Grafana)
    # read the same /metrics text. Stage 2 may add Compose Prometheus/Grafana.
    metrics_registry = CollectorRegistry()
    metric_reader = PrometheusMetricReader(
        registry=metrics_registry,
        disable_target_info=True,
        scope_info_enabled=False,
    )
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[metric_reader],
        views=_DROP_HTTP_BODY_SIZE_VIEWS,
    )
    meter = meter_provider.get_meter(SERVICE_NAME)
    app_metrics = LlmMetrics(
        operation_duration=meter.create_histogram(
            name="gen_ai.client.operation.duration",
            unit="s",
            description="End-to-end LLM call duration (time to done).",
            explicit_bucket_boundaries_advisory=_DURATION_BUCKETS,
        ),
        token_usage=meter.create_histogram(
            name="gen_ai.client.token.usage",
            unit="{token}",
            description="Tokens consumed by an LLM call.",
            explicit_bucket_boundaries_advisory=_TOKEN_BUCKETS,
        ),
        request_count=meter.create_counter(
            name="gen_ai.client.request_count",
            unit="{request}",
            description="LLM chat requests by outcome (success / error / timeout).",
        ),
        suggest_source=meter.create_counter(
            name="suggest.source",
            unit="{suggestion}",
            description="Suggest responses by source (llm / fallback / expectimax).",
        ),
        client_suggest_outcome=meter.create_counter(
            name="client.suggest.outcome",
            unit="{event}",
            description="Browser-reported suggest outcomes (fail / rate_limit).",
        ),
    )

    app_tracer = provider.get_tracer(SERVICE_NAME)
    # Bind before FastAPIInstrumentor so the threadpool endpoint shares this tracer.
    app.add_middleware(
        _RequestTelemetryMiddleware,
        tracer=app_tracer,
        metrics=app_metrics,
    )
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        meter_provider=meter_provider,
        excluded_urls=_EXCLUDED_URLS,
        exclude_spans=["send", "receive"],
        server_request_hook=_tag_http_span,
    )
    app.state.tracer_provider = provider
    app.state.meter_provider = meter_provider
    app.state.metrics_registry = metrics_registry
    app.state.trace_endpoint = endpoint
    app.state.telemetry_shutdown = False

    @app.get("/metrics", include_in_schema=False)
    def prometheus_metrics() -> Response:
        return Response(
            generate_latest(metrics_registry),
            media_type=CONTENT_TYPE_LATEST,
        )

    return provider


def shutdown_telemetry(app) -> None:
    """Flush this app's spans. Safe to call from lifespan and process exit."""
    if getattr(app.state, "telemetry_shutdown", False):
        return
    app.state.telemetry_shutdown = True
    provider = getattr(app.state, "tracer_provider", None)
    if provider is not None:
        provider.shutdown()
    meter_provider = getattr(app.state, "meter_provider", None)
    if meter_provider is not None:
        meter_provider.shutdown()


@contextmanager
def chain_span(name: str, *, input_payload: object | None = None) -> Iterator[Span]:
    """OpenInference CHAIN span for a nested application step."""
    with tracer().start_as_current_span(name) as span:
        span.set_attribute(OPENINFERENCE_SPAN_KIND, SPAN_KIND_CHAIN)
        if input_payload is not None:
            set_json_io(span, input_payload=input_payload)
        yield span


def set_json_io(
    span: Span,
    *,
    input_payload: object | None = None,
    output_payload: object | None = None,
) -> None:
    """Attach JSON input/output for Phoenix chain views."""
    if input_payload is not None:
        span.set_attribute(INPUT_VALUE, json.dumps(input_payload))
        span.set_attribute(INPUT_MIME_TYPE, OpenInferenceMimeTypeValues.JSON.value)
    if output_payload is not None:
        span.set_attribute(OUTPUT_VALUE, json.dumps(output_payload))
        span.set_attribute(OUTPUT_MIME_TYPE, OpenInferenceMimeTypeValues.JSON.value)


def mark_chain_io(span: Span, *, input_payload: object, output_payload: object) -> None:
    """Tag a span as CHAIN and set its JSON I/O."""
    span.set_attribute(OPENINFERENCE_SPAN_KIND, SPAN_KIND_CHAIN)
    set_json_io(span, input_payload=input_payload, output_payload=output_payload)


def annotate_llm_span(span: Span, model: str) -> None:
    """OpenInference LLM labels for an Ollama chat call."""
    span.set_attribute(OPENINFERENCE_SPAN_KIND, SPAN_KIND_LLM)
    span.set_attribute(LLM_PROVIDER, OpenInferenceLLMProviderValues.OLLAMA.value)
    span.set_attribute(LLM_SYSTEM, "ollama")
    span.set_attribute(LLM_MODEL_NAME, model)


def set_llm_messages(
    span: Span,
    *,
    prompt: str,
    output: str | None = None,
    finish_reason: str | None = None,
    invocation: dict[str, object] | None = None,
) -> None:
    """Chat content in llm.* messages; input/output mirror for the Phoenix list view."""
    span.set_attribute(LLM_INPUT_MESSAGE_ROLE, "user")
    span.set_attribute(LLM_INPUT_MESSAGE_CONTENT, prompt)
    span.set_attribute(INPUT_VALUE, prompt)
    span.set_attribute(INPUT_MIME_TYPE, OpenInferenceMimeTypeValues.TEXT.value)
    if invocation is not None:
        span.set_attribute(LLM_INVOCATION_PARAMETERS, json.dumps(invocation))
    if output is not None:
        span.set_attribute(LLM_OUTPUT_MESSAGE_ROLE, "assistant")
        span.set_attribute(LLM_OUTPUT_MESSAGE_CONTENT, output)
        span.set_attribute(OUTPUT_VALUE, output)
        span.set_attribute(OUTPUT_MIME_TYPE, OpenInferenceMimeTypeValues.JSON.value)
    if finish_reason:
        span.set_attribute(LLM_FINISH_REASON, finish_reason)


def record_llm_usage(
    span: Span,
    *,
    model: str,
    body: dict,
    wall_seconds: float,
    started_ns: int,
) -> None:
    """Map an Ollama chat body onto token attrs, latency events, and histograms.

    `wall_seconds` is the client wait (span duration). Provider timings come from
    the response body and land on events.
    """
    prompt_tokens = _as_int(body.get("prompt_eval_count"))
    completion_tokens = _as_int(body.get("eval_count"))
    cache_read = _as_int(body.get("prompt_eval_cached_count"))
    load = _ns_to_s(body.get("load_duration"))
    prompt_eval = _ns_to_s(body.get("prompt_eval_duration"))
    eval_time = _ns_to_s(body.get("eval_duration"))
    total = _ns_to_s(body.get("total_duration"))
    total_seconds = total if total is not None else wall_seconds
    ttft = _ttft_seconds(load, prompt_eval, total_seconds, eval_time)
    seconds_per_token = None
    if completion_tokens and eval_time is not None and completion_tokens > 0:
        seconds_per_token = eval_time / completion_tokens

    if prompt_tokens is not None:
        span.set_attribute(LLM_TOKEN_COUNT_PROMPT, prompt_tokens)
    if completion_tokens is not None:
        span.set_attribute(LLM_TOKEN_COUNT_COMPLETION, completion_tokens)
    if prompt_tokens is not None and completion_tokens is not None:
        span.set_attribute(LLM_TOKEN_COUNT_TOTAL, prompt_tokens + completion_tokens)
    if cache_read is not None and cache_read > 0:
        span.set_attribute(LLM_TOKEN_COUNT_CACHE_READ, cache_read)

    response_model = body.get("model")
    if isinstance(response_model, str) and response_model and response_model != model:
        span.set_attribute(SpanAttributes.LLM_RESPONSE_MODEL_NAME, response_model)

    # Clamp the first-token stamp so Phoenix keeps it inside this span.
    if ttft is not None:
        first_token = {
            key: value
            for key, value in {
                "ttft": ttft,
                "load": load,
                "prompt_eval": prompt_eval,
            }.items()
            if value is not None
        }
        span.add_event(
            _FIRST_TOKEN_EVENT,
            attributes=first_token,
            timestamp=_timestamp_inside_span(span, started_ns, ttft),
        )
    done_attrs: dict[str, float] = {}
    if total is not None:
        done_attrs["provider_total"] = total
    if eval_time is not None:
        done_attrs["eval"] = eval_time
    if seconds_per_token is not None:
        done_attrs["time_per_output_token"] = seconds_per_token
    if done_attrs:
        span.add_event(_GENERATION_DONE_EVENT, attributes=done_attrs)

    metric_attrs = _operation_metric_attrs(model)
    instruments = llm_metrics()
    if instruments is None:
        return
    instruments.operation_duration.record(wall_seconds, metric_attrs)
    if prompt_tokens is not None:
        instruments.token_usage.record(
            prompt_tokens, {**metric_attrs, "gen_ai.token.type": "input"}
        )
    if completion_tokens is not None:
        instruments.token_usage.record(
            completion_tokens, {**metric_attrs, "gen_ai.token.type": "output"}
        )


def record_llm_request_count(model: str, *, outcome: str, error_type: str | None = None) -> None:
    """Count one LLM chat request. Histograms stay on successful usage mapping only."""
    instruments = llm_metrics()
    if instruments is None:
        return
    attrs = {
        **_operation_metric_attrs(model),
        "gen_ai.request.outcome": outcome,
    }
    if error_type:
        attrs["error.type"] = error_type
    instruments.request_count.add(1, attrs)


def record_suggest_source(source: str) -> None:
    """Count one completed suggest response by API `source` (not HTTP status)."""
    instruments = llm_metrics()
    if instruments is None:
        return
    instruments.suggest_source.add(1, {"suggest.source": source})


def record_client_suggest_outcome(outcome: str) -> None:
    """Count one browser beacon for a suggest fail / rate_limit (not cancel yet)."""
    instruments = llm_metrics()
    if instruments is None:
        return
    instruments.client_suggest_outcome.add(1, {"outcome": outcome})


def mark_span_error(span: Span, error: Exception) -> None:
    span.record_exception(error)
    span.set_status(Status(StatusCode.ERROR, str(error)))


def _operation_metric_attrs(model: str) -> dict[str, str]:
    return {
        "gen_ai.operation.name": "chat",
        "gen_ai.provider.name": "ollama",
        "gen_ai.request.model": model,
    }


def _timestamp_inside_span(span: Span, started_ns: int, offset_seconds: float) -> int:
    """Clamp an event timestamp into the still-open span.

    Provider timings can exceed the client span (fast test doubles, clock skew).
    Phoenix drops or mis-draws events outside the span window.
    """
    start = getattr(span, "start_time", None)
    if not isinstance(start, int):
        start = started_ns
    now = time.time_ns()
    stamp = started_ns + int(offset_seconds * 1e9)
    if stamp < start:
        stamp = start
    if stamp > now:
        stamp = now
    if stamp < start:
        stamp = start
    return stamp


def _ttft_seconds(
    load: float | None,
    prompt_eval: float | None,
    ttd: float | None,
    eval_time: float | None,
) -> float | None:
    # Prefill + load stands in for time to first token when the call is not streamed.
    parts = [part for part in (load, prompt_eval) if part is not None]
    if parts:
        return sum(parts)
    if ttd is not None and eval_time is not None and ttd >= eval_time:
        return ttd - eval_time
    return None


def _ns_to_s(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < 0:
        return None
    return float(value) / 1e9


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value
