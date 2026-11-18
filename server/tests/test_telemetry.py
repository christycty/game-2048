import httpx
import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from app.config import Settings
from app.llm import ModelSuggestion, OllamaClient
from app.main import create_app
from app.telemetry import (
    INPUT_VALUE,
    LLM_FINISH_REASON,
    LLM_INPUT_MESSAGE_CONTENT,
    LLM_MODEL_NAME,
    LLM_OUTPUT_MESSAGE_CONTENT,
    LLM_PROVIDER,
    LLM_SYSTEM,
    LLM_TOKEN_COUNT_CACHE_READ,
    LLM_TOKEN_COUNT_COMPLETION,
    LLM_TOKEN_COUNT_PROMPT,
    OPENINFERENCE_SPAN_KIND,
    OUTPUT_VALUE,
    SERVICE_NAME,
    SPAN_KIND_LLM,
    exporter_headers,
    install_tracer_provider,
    traces_url,
)
from helpers import isolated_settings

OPEN_BOARD = [
    [2, 0, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
]


class _QuietLLM:
    def suggest_move(
        self,
        board: list[list[int]],
        *,
        legal: list[str],
        rejected: list[str],
        invalid_reply: bool,
    ) -> ModelSuggestion:
        return ModelSuggestion(legal[0], "ok")


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

    install_tracer_provider(app_one.state.tracer_provider)
    TestClient(app_one).post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"})
    assert first.get_finished_spans()
    assert second.get_finished_spans() == ()

    install_tracer_provider(app_two.state.tracer_provider)
    TestClient(app_two).post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"})
    assert len(second.get_finished_spans()) >= 1


def test_health_and_asgi_noise_are_not_traced() -> None:
    exporter = InMemorySpanExporter()
    app = create_app(
        isolated_settings(export_traces=True),
        _QuietLLM(),
        SimpleSpanProcessor(exporter),
    )
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    assert exporter.get_finished_spans() == ()

    response = client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"})
    assert response.status_code == 200
    names = {span.name for span in exporter.get_finished_spans()}
    assert names == {"POST /suggest"}
    assert not any("http send" in name or "http receive" in name for name in names)


def test_ollama_call_records_an_openinference_llm_span() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "test-model",
                "message": {"content": '{"move": "right", "reason": "Opens the row."}'},
                "done_reason": "stop",
                "prompt_eval_count": 40,
                "prompt_eval_cached_count": 10,
                "eval_count": 12,
                "load_duration": 100_000_000,
                "prompt_eval_duration": 200_000_000,
                "eval_duration": 300_000_000,
                "total_duration": 600_000_000,
            },
        )

    exporter = InMemorySpanExporter()
    settings = isolated_settings(export_traces=True, ollama_model="test-model")
    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="http://ollama.test") as http:
        app = create_app(
            settings,
            OllamaClient(settings, client=http),
            SimpleSpanProcessor(exporter),
        )
        response = TestClient(app).post(
            "/suggest",
            json={"board": OPEN_BOARD, "mode": "llm"},
        )

    assert response.status_code == 200
    assert response.json()["source"] == "llm"

    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert set(spans) == {"POST /suggest", "test-model"}
    llm_span = spans["test-model"]
    assert llm_span.parent is not None
    assert llm_span.parent.span_id == spans["POST /suggest"].context.span_id

    attrs = llm_span.attributes
    assert attrs[OPENINFERENCE_SPAN_KIND] == SPAN_KIND_LLM
    assert attrs[LLM_PROVIDER] == "ollama"
    assert attrs[LLM_SYSTEM] == "ollama"
    assert attrs[LLM_MODEL_NAME] == "test-model"
    assert attrs[LLM_FINISH_REASON] == "stop"
    assert "Legal moves:" in attrs[LLM_INPUT_MESSAGE_CONTENT]
    assert attrs[INPUT_VALUE] == attrs[LLM_INPUT_MESSAGE_CONTENT]
    assert '"move": "right"' in attrs[LLM_OUTPUT_MESSAGE_CONTENT]
    assert attrs[OUTPUT_VALUE] == attrs[LLM_OUTPUT_MESSAGE_CONTENT]
    assert attrs[LLM_TOKEN_COUNT_PROMPT] == 40
    assert attrs[LLM_TOKEN_COUNT_COMPLETION] == 12
    assert attrs[LLM_TOKEN_COUNT_CACHE_READ] == 10
    assert "metadata" not in attrs

    first_token = next(
        event for event in llm_span.events if event.name == "First Token Stream Event"
    )
    assert first_token.attributes["ttft"] == pytest.approx(0.3)
    assert first_token.attributes["load"] == pytest.approx(0.1)
    assert first_token.attributes["prompt_eval"] == pytest.approx(0.2)

    done = next(event for event in llm_span.events if event.name == "Generation Done")
    assert done.attributes["ttd"] == pytest.approx(0.6)
    assert done.attributes["time_per_output_token"] == pytest.approx(0.025)


def test_failed_ollama_call_marks_llm_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    exporter = InMemorySpanExporter()
    settings = isolated_settings(export_traces=True, llm_max_attempts=1)
    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="http://ollama.test") as http:
        app = create_app(
            settings,
            OllamaClient(settings, client=http),
            SimpleSpanProcessor(exporter),
        )
        response = TestClient(app).post(
            "/suggest",
            json={"board": OPEN_BOARD, "mode": "llm"},
        )

    assert response.status_code == 200
    assert response.json()["source"] == "fallback"
    llm_spans = [
        span
        for span in exporter.get_finished_spans()
        if span.attributes and span.attributes.get(OPENINFERENCE_SPAN_KIND) == SPAN_KIND_LLM
    ]
    assert len(llm_spans) == 1
    assert llm_spans[0].status.status_code == StatusCode.ERROR
