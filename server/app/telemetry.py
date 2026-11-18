from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from urllib.parse import urlparse

from openinference.semconv.trace import (
    MessageAttributes,
    OpenInferenceLLMProviderValues,
    OpenInferenceMimeTypeValues,
    OpenInferenceSpanKindValues,
    SpanAttributes,
)
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanProcessor
from opentelemetry.trace import Span, Status, StatusCode

from app.config import Settings

SERVICE_NAME = "game-2048-server"
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}
# ASGI send/receive child spans and health checks are noise for LLM traces.
_EXCLUDED_URLS = "/health,/docs,/openapi.json,/redoc"
_FIRST_TOKEN_EVENT = "First Token Stream Event"
_GENERATION_DONE_EVENT = "Generation Done"
_DURATION_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20)
_TOKEN_BUCKETS = (1, 4, 16, 64, 256, 1024, 4096, 16384)

# Re-export OpenInference keys used by tests and callers.
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
    operation_duration: metrics.Histogram
    time_to_first_token: metrics.Histogram
    time_per_output_token: metrics.Histogram
    token_usage: metrics.Histogram


_llm_metrics: LlmMetrics | None = None


def tracer() -> trace.Tracer:
    return trace.get_tracer(SERVICE_NAME)


def llm_metrics() -> LlmMetrics | None:
    return _llm_metrics


def install_tracer_provider(provider: TracerProvider) -> None:
    """Point ``get_tracer`` at this provider, replacing any previous one.

    OpenTelemetry's public ``set_tracer_provider`` only works once. Tests (and
    ``create_app``) build multiple apps, each with its own exporter, so LLM
    spans must follow the latest provider.
    """
    trace._TRACER_PROVIDER = provider


def install_meter_provider(provider: MeterProvider) -> None:
    metrics._METER_PROVIDER = provider


def traces_url(collector_endpoint: str) -> str:
    endpoint = collector_endpoint.rstrip("/")
    if endpoint.endswith("/v1/traces"):
        return endpoint
    return f"{endpoint}/v1/traces"


def exporter_headers(collector_endpoint: str, api_key: str | None) -> dict[str, str] | None:
    if not api_key:
        return None
    parsed = urlparse(traces_url(collector_endpoint))
    host = (parsed.hostname or "").lower()
    loopback = host in _LOOPBACK
    if parsed.scheme == "https" or (parsed.scheme == "http" and loopback):
        return {"authorization": f"Bearer {api_key}"}
    return None


def _tag_http_span(span: Span, scope: dict) -> None:
    """Mark API request spans as OpenInference CHAIN; skip noise paths."""
    path = scope.get("path") or ""
    if path in {"/health", "/docs", "/openapi.json", "/redoc"}:
        return
    span.set_attribute(OPENINFERENCE_SPAN_KIND, SPAN_KIND_CHAIN)


def setup_telemetry(
    app,
    settings: Settings,
    span_processor: SpanProcessor | None = None,
) -> TracerProvider:
    global _llm_metrics

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

    # Phoenix ingests traces, not OTLP metrics. Keep instruments in-process so
    # TTFT/TTD/token histograms are available to a future metrics backend.
    meter_provider = MeterProvider(resource=resource)
    install_meter_provider(meter_provider)
    meter = meter_provider.get_meter(SERVICE_NAME)
    _llm_metrics = LlmMetrics(
        operation_duration=meter.create_histogram(
            name="gen_ai.client.operation.duration",
            unit="s",
            description="End-to-end LLM call duration (time to done).",
            explicit_bucket_boundaries_advisory=_DURATION_BUCKETS,
        ),
        time_to_first_token=meter.create_histogram(
            name="gen_ai.client.time_to_first_token",
            unit="s",
            description="Approximate time to first token from provider timings.",
            explicit_bucket_boundaries_advisory=_DURATION_BUCKETS,
        ),
        time_per_output_token=meter.create_histogram(
            name="gen_ai.client.time_per_output_token",
            unit="s",
            description="Average generation time per output token.",
            explicit_bucket_boundaries_advisory=_DURATION_BUCKETS,
        ),
        token_usage=meter.create_histogram(
            name="gen_ai.client.token.usage",
            unit="{token}",
            description="Tokens consumed by an LLM call.",
            explicit_bucket_boundaries_advisory=_TOKEN_BUCKETS,
        ),
    )

    install_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        excluded_urls=_EXCLUDED_URLS,
        exclude_spans=["send", "receive"],
        server_request_hook=_tag_http_span,
    )
    app.state.tracer_provider = provider
    app.state.meter_provider = meter_provider
    app.state.trace_endpoint = endpoint
    return provider


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
    if input_payload is not None:
        span.set_attribute(INPUT_VALUE, json.dumps(input_payload))
        span.set_attribute(INPUT_MIME_TYPE, OpenInferenceMimeTypeValues.JSON.value)
    if output_payload is not None:
        span.set_attribute(OUTPUT_VALUE, json.dumps(output_payload))
        span.set_attribute(OUTPUT_MIME_TYPE, OpenInferenceMimeTypeValues.JSON.value)


def mark_chain_io(span: Span, *, input_payload: object, output_payload: object) -> None:
    span.set_attribute(OPENINFERENCE_SPAN_KIND, SPAN_KIND_CHAIN)
    set_json_io(span, input_payload=input_payload, output_payload=output_payload)


def annotate_llm_span(span: Span, model: str) -> None:
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
    """Chat content lives in llm.* messages; input/output mirror for Phoenix list view."""
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


def record_llm_success(
    span: Span,
    *,
    model: str,
    body: dict,
    wall_seconds: float,
    started_ns: int,
) -> None:
    prompt_tokens = _as_int(body.get("prompt_eval_count"))
    completion_tokens = _as_int(body.get("eval_count"))
    cache_read = _as_int(body.get("prompt_eval_cached_count"))
    load = _ns_to_s(body.get("load_duration"))
    prompt_eval = _ns_to_s(body.get("prompt_eval_duration"))
    eval_time = _ns_to_s(body.get("eval_duration"))
    total = _ns_to_s(body.get("total_duration"))
    ttd = total if total is not None else wall_seconds
    ttft = _ttft_seconds(load, prompt_eval, ttd, eval_time)

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

    # Latency belongs on events: span duration is TTD; first-token event marks TTFT.
    if ttft is not None:
        prefill = {
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
            attributes=prefill,
            timestamp=started_ns + int(ttft * 1e9),
        )
    done_attrs: dict[str, float] = {"ttd": ttd, "wall": wall_seconds}
    if eval_time is not None:
        done_attrs["eval"] = eval_time
    if completion_tokens and eval_time is not None and completion_tokens > 0:
        done_attrs["time_per_output_token"] = eval_time / completion_tokens
    span.add_event(_GENERATION_DONE_EVENT, attributes=done_attrs)

    metric_attrs = {
        "gen_ai.operation.name": "chat",
        "gen_ai.provider.name": "ollama",
        "gen_ai.request.model": model,
    }
    instruments = llm_metrics()
    if instruments is None:
        return
    instruments.operation_duration.record(ttd, metric_attrs)
    if ttft is not None:
        instruments.time_to_first_token.record(ttft, metric_attrs)
    if completion_tokens and eval_time is not None and completion_tokens > 0:
        instruments.time_per_output_token.record(eval_time / completion_tokens, metric_attrs)
    if prompt_tokens is not None:
        instruments.token_usage.record(
            prompt_tokens, {**metric_attrs, "gen_ai.token.type": "input"}
        )
    if completion_tokens is not None:
        instruments.token_usage.record(
            completion_tokens, {**metric_attrs, "gen_ai.token.type": "output"}
        )


def mark_span_error(span: Span, error: Exception) -> None:
    span.record_exception(error)
    span.set_status(Status(StatusCode.ERROR, str(error)))


def _ttft_seconds(
    load: float | None,
    prompt_eval: float | None,
    ttd: float | None,
    eval_time: float | None,
) -> float | None:
    # Prefill + load is the non-streaming stand-in for time to first token.
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
