from urllib.parse import urlparse

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanProcessor

from app.config import Settings

SERVICE_NAME = "game-2048-server"
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


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


def setup_telemetry(
    app,
    settings: Settings,
    span_processor: SpanProcessor | None = None,
) -> TracerProvider:
    endpoint = traces_url(settings.phoenix_collector_endpoint)
    provider = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))
    if settings.export_traces:
        if span_processor is None:
            span_processor = BatchSpanProcessor(
                OTLPSpanExporter(
                    endpoint=endpoint,
                    headers=exporter_headers(endpoint, settings.phoenix_api_key),
                )
            )
        provider.add_span_processor(span_processor)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    app.state.tracer_provider = provider
    app.state.trace_endpoint = endpoint
    return provider
