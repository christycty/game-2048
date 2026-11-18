from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.config import Settings
from app.main import create_app
from app.telemetry import SERVICE_NAME, exporter_headers, traces_url


class _QuietLLM:
    def suggest_move(self, board: list[list[int]]) -> str:
        return "left"


def test_phoenix_base_url_gets_traces_path() -> None:
    assert traces_url("http://localhost:6006") == "http://localhost:6006/v1/traces"
    assert traces_url("http://phoenix:6006/") == "http://phoenix:6006/v1/traces"


def test_full_traces_url_is_kept() -> None:
    url = "http://localhost:6006/v1/traces"
    assert traces_url(url) == url


def test_api_key_is_sent_only_on_https_or_loopback() -> None:
    assert exporter_headers("https://phoenix.example", "secret") == {
        "authorization": "Bearer secret"
    }
    assert exporter_headers("http://localhost:6006", "secret") == {"authorization": "Bearer secret"}
    assert exporter_headers("http://127.0.0.1:6006", "secret") == {"authorization": "Bearer secret"}
    assert exporter_headers("http://phoenix.example:6006", "secret") is None
    assert exporter_headers("https://phoenix.example", None) is None


def test_each_app_keeps_its_own_exporter() -> None:
    first = InMemorySpanExporter()
    second = InMemorySpanExporter()
    app_one = create_app(
        Settings(export_traces=True, phoenix_collector_endpoint="http://localhost:6006"),
        _QuietLLM(),
        SimpleSpanProcessor(first),
    )
    app_two = create_app(
        Settings(export_traces=True, phoenix_collector_endpoint="http://phoenix:6006"),
        _QuietLLM(),
        SimpleSpanProcessor(second),
    )

    assert app_one.state.trace_endpoint == "http://localhost:6006/v1/traces"
    assert app_two.state.trace_endpoint == "http://phoenix:6006/v1/traces"
    assert app_one.state.tracer_provider.resource.attributes["service.name"] == SERVICE_NAME

    TestClient(app_one).get("/health")
    assert first.get_finished_spans()
    assert second.get_finished_spans() == ()

    TestClient(app_two).get("/health")
    assert len(second.get_finished_spans()) >= 1
