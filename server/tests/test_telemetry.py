import httpx
import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from app.config import Settings
from app.llm import ModelSuggestion, OllamaClient
from app.main import create_app
from app.rate_limit import SuggestRateLimiter
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
    PROM_CLIENT_SUGGEST_OUTCOME,
    PROM_OPERATION_DURATION,
    PROM_REQUEST_COUNT,
    PROM_SUGGEST_SOURCE,
    PROM_TOKEN_USAGE,
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
        cancel=None,
    ) -> ModelSuggestion:
        return ModelSuggestion(legal[0], "ok")


def _ollama_chat_json(content: object) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "test-model",
            "message": {"content": content},
            "done_reason": "stop",
            "prompt_eval_count": 40,
            "eval_count": 12,
            "load_duration": 100_000_000,
            "prompt_eval_duration": 200_000_000,
            "eval_duration": 300_000_000,
            "total_duration": 600_000_000,
        },
    )


def _suggest_status_count(body: str, status_code: int) -> float:
    """Count samples for POST /suggest at this HTTP status (Grafana by-status panel)."""
    marker = f'http_status_code="{status_code}",http_target="/suggest"'
    for line in body.splitlines():
        if line.startswith("http_server_duration_milliseconds_count") and marker in line:
            return float(line.rsplit(" ", 1)[-1])
    return 0.0


def _labeled_counter(body: str, metric: str, label_fragment: str) -> float:
    prefix = f"{metric}_total{{"
    for line in body.splitlines():
        if line.startswith(prefix) and label_fragment in line:
            return float(line.rsplit(" ", 1)[-1])
    return 0.0


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
    assert client.get("/metrics").status_code == 200
    assert client.post("/client-events", json={"outcome": "fail"}).status_code == 204
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


def test_suggest_continues_client_traceparent() -> None:
    """Browser W3C traceparent must join the server HTTP + suggest spans."""
    exporter = InMemorySpanExporter()
    app = create_app(
        isolated_settings(export_traces=True),
        _QuietLLM(),
        SimpleSpanProcessor(exporter),
    )
    # Fixed ids from the W3C Trace Context examples.
    trace_id_hex = "4bf92f3577b34da6a3ce929d0e0e4736"
    parent_span_hex = "00f067aa0ba902b7"
    response = TestClient(app).post(
        "/suggest",
        json={"board": OPEN_BOARD, "mode": "llm"},
        headers={"traceparent": f"00-{trace_id_hex}-{parent_span_hex}-01"},
    )
    assert response.status_code == 200

    finished = exporter.get_finished_spans()
    assert {span.name for span in finished} == {"POST /suggest", "suggest"}
    expected_trace_id = int(trace_id_hex, 16)
    assert all(span.context.trace_id == expected_trace_id for span in finished)

    root = next(span for span in finished if span.name == "POST /suggest")
    assert root.parent is not None
    assert root.parent.span_id == int(parent_span_hex, 16)


def test_client_events_increment_scrape_counter() -> None:
    from app.telemetry import (
        CLIENT_OUTCOME_CANCEL,
        CLIENT_OUTCOME_FAIL,
        CLIENT_OUTCOME_RATE_LIMIT,
        record_client_suggest_outcome,
    )

    app = create_app(isolated_settings(export_traces=False), _QuietLLM())
    client = TestClient(app)
    assert client.post("/client-events", json={"outcome": CLIENT_OUTCOME_FAIL}).status_code == 204
    assert (
        client.post("/client-events", json={"outcome": CLIENT_OUTCOME_RATE_LIMIT}).status_code
        == 204
    )
    assert client.post("/client-events", json={"outcome": CLIENT_OUTCOME_CANCEL}).status_code == 204
    # Defense in depth: unknown labels never touch the scrape counter.
    record_client_suggest_outcome("not-an-outcome")
    record_client_suggest_outcome("success")

    body = client.get("/metrics").text
    assert PROM_CLIENT_SUGGEST_OUTCOME in body
    assert (
        _labeled_counter(body, PROM_CLIENT_SUGGEST_OUTCOME, f'outcome="{CLIENT_OUTCOME_FAIL}"')
        == 1.0
    )
    assert (
        _labeled_counter(
            body, PROM_CLIENT_SUGGEST_OUTCOME, f'outcome="{CLIENT_OUTCOME_RATE_LIMIT}"'
        )
        == 1.0
    )
    assert (
        _labeled_counter(body, PROM_CLIENT_SUGGEST_OUTCOME, f'outcome="{CLIENT_OUTCOME_CANCEL}"')
        == 1.0
    )


def test_http_body_size_metrics_dropped_active_and_duration_kept() -> None:
    """Scrape surface matches GenAI ops: drop size histograms, keep duration + active."""
    app = create_app(isolated_settings(export_traces=False), _QuietLLM())
    client = TestClient(app)
    assert client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"}).status_code == 200

    body = client.get("/metrics").text
    assert "http_server_duration_milliseconds" in body
    assert "http_server_active_requests" in body
    assert "http_server_request_size_bytes" not in body
    assert "http_server_response_size_bytes" not in body


def test_metrics_exposes_gen_ai_series_after_suggest() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "test-model",
                "message": {"content": '{"move": "right", "reason": "Opens the row."}'},
                "done_reason": "stop",
                "prompt_eval_count": 40,
                "eval_count": 12,
                "load_duration": 100_000_000,
                "prompt_eval_duration": 200_000_000,
                "eval_duration": 300_000_000,
                "total_duration": 600_000_000,
            },
        )

    settings = isolated_settings(export_traces=False, ollama_model="test-model")
    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="http://ollama.test") as http:
        app = create_app(settings, OllamaClient(settings, client=http))
        client = TestClient(app)
        assert client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"}).status_code == 200
        metrics = client.get("/metrics")

    assert metrics.status_code == 200
    body = metrics.text
    assert PROM_OPERATION_DURATION in body
    assert PROM_TOKEN_USAGE in body
    assert PROM_REQUEST_COUNT in body
    assert PROM_SUGGEST_SOURCE in body
    assert 'gen_ai_request_outcome="success"' in body
    assert 'suggest_source="llm"' in body
    assert 'gen_ai_token_type="input"' in body
    assert 'gen_ai_token_type="output"' in body
    assert "time_to_first_token" not in body
    assert "time_per_output_token" not in body


def test_metrics_counts_failed_llm_requests() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    settings = isolated_settings(export_traces=False, llm_max_attempts=1)
    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="http://ollama.test") as http:
        app = create_app(settings, OllamaClient(settings, client=http))
        client = TestClient(app)
        assert client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"}).status_code == 200
        body = client.get("/metrics").text

    assert PROM_REQUEST_COUNT in body
    assert 'gen_ai_request_outcome="error"' in body
    assert 'error_type="request"' in body
    assert 'suggest_source="fallback"' in body


def test_metrics_counts_timed_out_llm_requests() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    settings = isolated_settings(export_traces=False, llm_max_attempts=1)
    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="http://ollama.test") as http:
        app = create_app(settings, OllamaClient(settings, client=http))
        client = TestClient(app)
        assert client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"}).status_code == 200
        body = client.get("/metrics").text

    assert PROM_REQUEST_COUNT in body
    assert 'gen_ai_request_outcome="timeout"' in body
    assert 'gen_ai_request_outcome="error"' not in body
    assert 'suggest_source="fallback"' in body


def test_cancelled_llm_records_cancelled_not_error() -> None:
    """Disconnect cancel mid-Ollama attempt → gen_ai cancelled + spans not ERROR."""
    import threading

    from app.telemetry import OUTPUT_VALUE

    held: dict[str, threading.Event | None] = {"cancel": None}
    posts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        posts["n"] += 1
        # Trip cancel while the sync MockTransport POST is in flight; client then
        # raises SuggestCancelled after the response (same as disconnect mid-call).
        cancel = held["cancel"]
        if cancel is not None:
            cancel.set()
        return _ollama_chat_json('{"move": "right", "reason": "ignored after cancel"}')

    class HoldCancelLLM:
        def __init__(self, inner: OllamaClient) -> None:
            self._inner = inner

        def suggest_move(
            self,
            board: list[list[int]],
            *,
            legal: list[str],
            rejected: list[str],
            invalid_reply: bool,
            cancel: threading.Event | None = None,
        ) -> ModelSuggestion:
            held["cancel"] = cancel
            return self._inner.suggest_move(
                board,
                legal=legal,
                rejected=rejected,
                invalid_reply=invalid_reply,
                cancel=cancel,
            )

    exporter = InMemorySpanExporter()
    settings = isolated_settings(
        export_traces=True,
        ollama_model="test-model",
        llm_max_attempts=1,
    )
    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="http://ollama.test") as http:
        llm = OllamaClient(settings, client=http)
        app = create_app(settings, HoldCancelLLM(llm), SimpleSpanProcessor(exporter))
        client = TestClient(app)
        response = client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"})
        body = client.get("/metrics").text

    assert response.status_code == 499
    assert response.json()["detail"] == "client cancelled"
    assert posts["n"] == 1
    assert PROM_REQUEST_COUNT in body
    assert 'gen_ai_request_outcome="cancelled"' in body
    assert 'gen_ai_request_outcome="error"' not in body
    # Cancelled mid-pipeline: no completed suggest_source increment.
    assert 'suggest_source="llm"' not in body
    assert 'suggest_source="fallback"' not in body

    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert "ollama chat" in spans
    assert "suggest" in spans
    assert spans["ollama chat"].status.status_code != StatusCode.ERROR
    assert spans["suggest"].status.status_code != StatusCode.ERROR
    assert "cancelled" in (spans["ollama chat"].attributes.get(OUTPUT_VALUE) or "")


def test_cancel_already_set_records_cancelled_without_ollama_post() -> None:
    """Attempt span opens, cancel already set → gen_ai cancelled, no HTTP to Ollama."""
    import threading

    from app.telemetry import OUTPUT_VALUE

    posts = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        posts["n"] += 1
        return _ollama_chat_json('{"move": "right", "reason": "should not run"}')

    class PreSetCancelLLM:
        def __init__(self, inner: OllamaClient) -> None:
            self._inner = inner

        def suggest_move(
            self,
            board: list[list[int]],
            *,
            legal: list[str],
            rejected: list[str],
            invalid_reply: bool,
            cancel: threading.Event | None = None,
        ) -> ModelSuggestion:
            # Trip cancel after the LLM loop starts but before the Ollama POST.
            if cancel is not None:
                cancel.set()
            return self._inner.suggest_move(
                board,
                legal=legal,
                rejected=rejected,
                invalid_reply=invalid_reply,
                cancel=cancel,
            )

    exporter = InMemorySpanExporter()
    settings = isolated_settings(
        export_traces=True,
        ollama_model="test-model",
        llm_max_attempts=1,
    )
    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="http://ollama.test") as http:
        llm = OllamaClient(settings, client=http)
        app = create_app(settings, PreSetCancelLLM(llm), SimpleSpanProcessor(exporter))
        client = TestClient(app)
        response = client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"})
        body = client.get("/metrics").text

    assert response.status_code == 499
    assert posts["n"] == 0
    assert 'gen_ai_request_outcome="cancelled"' in body
    assert 'gen_ai_request_outcome="error"' not in body
    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert "ollama chat" in spans
    assert spans["ollama chat"].status.status_code != StatusCode.ERROR
    assert "cancelled" in (spans["ollama chat"].attributes.get(OUTPUT_VALUE) or "")


def test_between_attempt_cancel_records_cancelled() -> None:
    """Fail attempt 1, cancel before attempt 2 → cancelled (not a second error)."""
    import threading

    from app.telemetry import OUTPUT_VALUE

    posts = {"n": 0}
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        posts["n"] += 1
        # Unusable body → LlmError → suggester retries.
        return httpx.Response(200, json={"message": {"content": "not-json"}})

    class CancelBeforeRetryLLM:
        def __init__(self, inner: OllamaClient) -> None:
            self._inner = inner

        def suggest_move(
            self,
            board: list[list[int]],
            *,
            legal: list[str],
            rejected: list[str],
            invalid_reply: bool,
            cancel: threading.Event | None = None,
        ) -> ModelSuggestion:
            calls["n"] += 1
            if calls["n"] == 2 and cancel is not None:
                cancel.set()
            return self._inner.suggest_move(
                board,
                legal=legal,
                rejected=rejected,
                invalid_reply=invalid_reply,
                cancel=cancel,
            )

    exporter = InMemorySpanExporter()
    settings = isolated_settings(
        export_traces=True,
        ollama_model="test-model",
        llm_max_attempts=3,
    )
    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="http://ollama.test") as http:
        llm = OllamaClient(settings, client=http)
        app = create_app(settings, CancelBeforeRetryLLM(llm), SimpleSpanProcessor(exporter))
        client = TestClient(app)
        # Seed the request cancel Event: middleware creates it unset; the wrapper
        # sets it on the second suggest_move so attempt 2 records cancelled.
        response = client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"})
        body = client.get("/metrics").text

    assert response.status_code == 499
    assert calls["n"] == 2
    assert posts["n"] == 1
    assert 'gen_ai_request_outcome="cancelled"' in body
    # First attempt still counts as a model error; cancel must not add another.
    assert _labeled_counter(body, PROM_REQUEST_COUNT, 'gen_ai_request_outcome="error"') == 1.0
    assert _labeled_counter(body, PROM_REQUEST_COUNT, 'gen_ai_request_outcome="cancelled"') == 1.0
    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert spans["suggest"].status.status_code != StatusCode.ERROR
    ollama_spans = [s for s in exporter.get_finished_spans() if s.name == "ollama chat"]
    assert len(ollama_spans) == 2
    assert any("cancelled" in (s.attributes.get(OUTPUT_VALUE) or "") for s in ollama_spans)


def test_metrics_counts_expectimax_suggest_source() -> None:
    app = create_app(isolated_settings(export_traces=False), _QuietLLM())
    client = TestClient(app)
    assert (
        client.post("/suggest", json={"board": OPEN_BOARD, "mode": "expectimax"}).status_code == 200
    )
    body = client.get("/metrics").text
    assert PROM_SUGGEST_SOURCE in body
    assert 'suggest_source="expectimax"' in body
    assert PROM_REQUEST_COUNT not in body or "gen_ai_request_outcome=" not in body


def test_metrics_records_suggest_http_status_codes() -> None:
    """FastAPI scrape series power Grafana 'by status' — assert each dashboarded code."""
    app = create_app(
        isolated_settings(export_traces=False, suggest_rate_limit_requests=10),
        _QuietLLM(),
    )
    client = TestClient(app)
    assert client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"}).status_code == 200
    assert client.post("/suggest", json={"board": [[0, 0, 0, 0]], "mode": "llm"}).status_code == 422
    assert client.post("/suggest", json={"board": STUCK_BOARD, "mode": "llm"}).status_code == 409
    body = client.get("/metrics").text
    assert _suggest_status_count(body, 200) >= 1.0
    assert _suggest_status_count(body, 422) >= 1.0
    assert _suggest_status_count(body, 409) >= 1.0
    # 409 returns no body source; 200 did increment llm.
    assert 'suggest_source="llm"' in body

    limited = create_app(
        isolated_settings(export_traces=False),
        _QuietLLM(),
        rate_limiters={
            "llm": SuggestRateLimiter(1, 60),
            "expectimax": SuggestRateLimiter(30, 60),
        },
    )
    limited_client = TestClient(limited)
    assert (
        limited_client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"}).status_code
        == 200
    )
    assert (
        limited_client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"}).status_code
        == 429
    )
    limited_body = limited_client.get("/metrics").text
    assert _suggest_status_count(limited_body, 429) >= 1.0
    # Rate-limit path must not invent an extra suggest_source beyond the 200.
    assert _labeled_counter(limited_body, PROM_SUGGEST_SOURCE, 'suggest_source="llm"') == 1.0
    assert _labeled_counter(limited_body, PROM_SUGGEST_SOURCE, 'suggest_source="fallback"') == 0.0


def test_metrics_counts_response_error_type() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "test-model"})

    settings = isolated_settings(export_traces=False, llm_max_attempts=1)
    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="http://ollama.test") as http:
        app = create_app(settings, OllamaClient(settings, client=http))
        client = TestClient(app)
        assert client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"}).status_code == 200
        body = client.get("/metrics").text

    assert 'gen_ai_request_outcome="error"' in body
    assert 'error_type="response"' in body
    assert 'suggest_source="fallback"' in body


def test_metrics_counts_parse_error_type() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _ollama_chat_json("not-json")

    settings = isolated_settings(export_traces=False, llm_max_attempts=1)
    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="http://ollama.test") as http:
        app = create_app(settings, OllamaClient(settings, client=http))
        client = TestClient(app)
        assert client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"}).status_code == 200
        body = client.get("/metrics").text

    assert 'gen_ai_request_outcome="error"' in body
    assert 'error_type="parse"' in body
    assert 'suggest_source="fallback"' in body


def test_metrics_counts_illegal_move_error_type() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # left is illegal on OPEN_BOARD (tile only slides right/down).
        return _ollama_chat_json('{"move": "left", "reason": "Bad direction."}')

    settings = isolated_settings(export_traces=False, llm_max_attempts=1)
    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="http://ollama.test") as http:
        app = create_app(settings, OllamaClient(settings, client=http))
        client = TestClient(app)
        assert client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"}).status_code == 200
        body = client.get("/metrics").text

    assert 'gen_ai_request_outcome="error"' in body
    assert 'error_type="illegal_move"' in body
    assert 'suggest_source="fallback"' in body


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
