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
    SPAN_KIND_CHAIN,
    SPAN_KIND_LLM,
    exporter_headers,
    traces_url,
)
from helpers import isolated_settings

OPEN_BOARD = [
    [2, 0, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
]

STUCK_BOARD = [
    [2, 4, 8, 16],
    [32, 64, 128, 256],
    [512, 1024, 2048, 4096],
    [8192, 16384, 32768, 65536],
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


def test_api_key_is_sent_only_on_https_or_loopback(caplog: pytest.LogCaptureFixture) -> None:
    assert exporter_headers("https://phoenix.example", "secret") == {
        "authorization": "Bearer secret"
    }
    assert exporter_headers("http://localhost:6006", "secret") == {"authorization": "Bearer secret"}
    assert exporter_headers("http://127.0.0.1:6006", "secret") == {"authorization": "Bearer secret"}
    assert exporter_headers("https://phoenix.example", None) is None
    with caplog.at_level("WARNING"):
        assert exporter_headers("http://host.docker.internal:6006", "secret") == {
            "authorization": "Bearer secret"
        }
        assert exporter_headers("http://phoenix.example:6006", "secret") is None
    assert "not sent" in caplog.text
    assert "phoenix.example" in caplog.text
    assert "secret" not in caplog.text


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

    # Each request records on the app that served it, including the nested chain span.
    TestClient(app_one).post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"})
    first_spans = first.get_finished_spans()
    assert {span.name for span in first_spans} == {"POST /suggest", "suggest"}
    assert len({span.context.trace_id for span in first_spans}) == 1
    assert second.get_finished_spans() == ()

    TestClient(app_two).post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"})
    assert {span.name for span in first.get_finished_spans()} == {"POST /suggest", "suggest"}
    second_spans = second.get_finished_spans()
    assert {span.name for span in second_spans} == {"POST /suggest", "suggest"}
    assert len({span.context.trace_id for span in second_spans}) == 1


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
    assert names == {"POST /suggest", "suggest"}
    assert not any("http send" in name or "http receive" in name for name in names)

    root = next(span for span in exporter.get_finished_spans() if span.name == "POST /suggest")
    assert root.attributes[OPENINFERENCE_SPAN_KIND] == SPAN_KIND_CHAIN
    assert '"mode": "llm"' in root.attributes[INPUT_VALUE]
    assert '"source": "llm"' in root.attributes[OUTPUT_VALUE]


def test_suggest_nests_llm_under_suggest_chain() -> None:
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
    assert set(spans) == {"POST /suggest", "suggest", "ollama chat"}

    root = spans["POST /suggest"]
    suggest = spans["suggest"]
    llm_span = spans["ollama chat"]

    assert root.attributes[OPENINFERENCE_SPAN_KIND] == SPAN_KIND_CHAIN
    assert suggest.attributes[OPENINFERENCE_SPAN_KIND] == SPAN_KIND_CHAIN
    assert llm_span.attributes[OPENINFERENCE_SPAN_KIND] == SPAN_KIND_LLM

    assert suggest.parent is not None
    assert llm_span.parent is not None
    assert suggest.parent.span_id == root.context.span_id
    assert llm_span.parent.span_id == suggest.context.span_id

    attrs = llm_span.attributes
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
    assert llm_span.start_time <= first_token.timestamp <= llm_span.end_time

    done = next(event for event in llm_span.events if event.name == "Generation Done")
    assert 0 <= done.attributes["time_to_done"] < 1
    assert done.attributes["provider_total"] == pytest.approx(0.6)
    assert done.attributes["time_per_output_token"] == pytest.approx(0.025)


def test_retries_add_sibling_llm_spans_under_suggest() -> None:
    replies = [
        httpx.Response(500, text="boom"),
        httpx.Response(
            200,
            json={
                "message": {"content": '{"move": "right", "reason": "Opens the row."}'},
                "done_reason": "stop",
                "prompt_eval_count": 10,
                "eval_count": 4,
                "total_duration": 100_000_000,
            },
        ),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return replies.pop(0)

    exporter = InMemorySpanExporter()
    settings = isolated_settings(export_traces=True, ollama_model="test-model", llm_max_attempts=2)
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
    finished = exporter.get_finished_spans()
    assert {span.name for span in finished} == {"POST /suggest", "suggest", "ollama chat"}
    llm_spans = [span for span in finished if span.name == "ollama chat"]
    assert len(llm_spans) == 2
    suggest = next(span for span in finished if span.name == "suggest")
    assert all(span.parent and span.parent.span_id == suggest.context.span_id for span in llm_spans)
    assert sum(1 for span in llm_spans if span.status.status_code == StatusCode.ERROR) == 1
    assert sum(1 for span in llm_spans if span.status.status_code != StatusCode.ERROR) == 1
    assert "failures" in suggest.attributes[OUTPUT_VALUE]
    assert "ollama request failed" in suggest.attributes[OUTPUT_VALUE]


def test_rejected_move_is_an_llm_error_and_stays_on_the_chain() -> None:
    replies = [
        httpx.Response(
            200,
            json={"message": {"content": '{"move": "up", "reason": "bad"}'}, "done_reason": "stop"},
        ),
        httpx.Response(
            200,
            json={
                "message": {"content": '{"move": "right", "reason": "good"}'},
                "done_reason": "stop",
            },
        ),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return replies.pop(0)

    exporter = InMemorySpanExporter()
    settings = isolated_settings(export_traces=True, ollama_model="test-model", llm_max_attempts=2)
    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="http://ollama.test") as http:
        app = create_app(
            settings,
            OllamaClient(settings, client=http),
            SimpleSpanProcessor(exporter),
        )
        response = TestClient(app).post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"})

    assert response.status_code == 200
    assert response.json()["source"] == "llm"
    assert "failures" not in response.json()
    finished = exporter.get_finished_spans()
    llm_spans = [span for span in finished if span.name == "ollama chat"]
    assert len(llm_spans) == 2
    assert llm_spans[0].status.status_code == StatusCode.ERROR
    assert llm_spans[1].status.status_code != StatusCode.ERROR
    suggest = next(span for span in finished if span.name == "suggest")
    root = next(span for span in finished if span.name == "POST /suggest")
    assert "illegal move up" in suggest.attributes[OUTPUT_VALUE]
    assert '"source": "llm"' in suggest.attributes[OUTPUT_VALUE]
    assert "failures" not in root.attributes[OUTPUT_VALUE]


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
    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert spans["ollama chat"].status.status_code == StatusCode.ERROR
    assert '"source": "fallback"' in spans["suggest"].attributes[OUTPUT_VALUE]


def test_stuck_board_marks_http_span_without_llm() -> None:
    exporter = InMemorySpanExporter()
    app = create_app(
        isolated_settings(export_traces=True),
        _QuietLLM(),
        SimpleSpanProcessor(exporter),
    )
    response = TestClient(app).post("/suggest", json={"board": STUCK_BOARD, "mode": "llm"})

    assert response.status_code == 409
    finished = exporter.get_finished_spans()
    assert {span.name for span in finished} == {"POST /suggest"}
    root = finished[0]
    assert root.status.status_code == StatusCode.ERROR
    assert "65536" in root.attributes[INPUT_VALUE]
    assert "no legal move" in root.attributes[OUTPUT_VALUE]
    assert "failures" not in root.attributes[OUTPUT_VALUE]
