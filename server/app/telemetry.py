import sys

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.config import Settings

_configured = False


def traces_url(collector_endpoint: str) -> str:
    endpoint = collector_endpoint.rstrip("/")
    if endpoint.endswith("/v1/traces"):
        return endpoint
    return f"{endpoint}/v1/traces"


def setup_telemetry(app, settings: Settings) -> None:
    global _configured
    if not _configured:
        provider = TracerProvider()
        if "pytest" not in sys.modules:
            headers = None
            if settings.phoenix_api_key:
                headers = {"authorization": f"Bearer {settings.phoenix_api_key}"}
            exporter = OTLPSpanExporter(
                endpoint=traces_url(settings.phoenix_collector_endpoint),
                headers=headers,
            )
            provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _configured = True
    FastAPIInstrumentor.instrument_app(app)
