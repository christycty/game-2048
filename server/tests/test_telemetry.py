import json
import threading

import httpx
import pytest
from fastapi.testclient import TestClient
from openinference.semconv.trace import SpanAttributes
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from app.cancel import SuggestCancelled
from app.config import Settings
from app.expectimax import choose_move as real_choose_move
from app.llm import ModelSuggestion, OllamaClient
from app.main import create_app
from app.rate_limit import HEADER_SUGGEST_LIMIT, InFlightGate, SuggestRateLimiter
from app.suggester import MoveSuggester
from app.telemetry import (
    CLIENT_OUTCOME_CANCEL,
    CLIENT_OUTCOME_FAIL,
    CLIENT_OUTCOME_MODEL_BUSY,
    CLIENT_OUTCOME_RATE_LIMIT,
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
    LLM_TOKEN_COUNT_TOTAL,
    OPENINFERENCE_SPAN_KIND,
    OUTPUT_VALUE,
    PROM_CLIENT_SUGGEST_OUTCOME,
    PROM_OPERATION_DURATION,
    PROM_REQUEST_COUNT,
    PROM_SUGGEST_LIMIT_REJECT,
    PROM_SUGGEST_SOURCE,
    PROM_TOKEN_USAGE,
    SERVICE_NAME,
    SPAN_KIND_CHAIN,
    SPAN_KIND_LLM,
    exporter_headers,
    record_client_suggest_outcome,
    traces_url,
)
from helpers import OPEN_BOARD, STUCK_BOARD, UnusedLLM, isolated_settings, labeled_counter


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
    status_label = f'http_status_code="{status_code}"'
    return sum(
        (
            float(line.rsplit(" ", 1)[-1])
            for line in body.splitlines()
            if line.startswith("http_server_duration_milliseconds_count{")
            and status_label in line
            and 'http_target="/suggest"' in line
        ),
        0.0,
    )


def _metric_sample_sum(body: str, sample_name: str, *label_fragments: str) -> float:
    """Sum Prometheus sample lines matching ``sample_name`` and all label fragments."""
    labeled_prefix = f"{sample_name}{{"
    bare_prefix = f"{sample_name} "
    total = 0.0
    for line in body.splitlines():
        if line.startswith(labeled_prefix):
            if all(fragment in line for fragment in label_fragments):
                total += float(line.rsplit(" ", 1)[-1])
        elif not label_fragments and line.startswith(bare_prefix):
            total += float(line.rsplit(" ", 1)[-1])
    return total


def _assert_usage_histograms_recorded(
    body: str,
    *,
    prompt_tokens: float = 40.0,
    completion_tokens: float = 12.0,
) -> None:
    assert _metric_sample_sum(body, f"{PROM_OPERATION_DURATION}_count") == 1.0
    assert _metric_sample_sum(body, f"{PROM_TOKEN_USAGE}_count", 'gen_ai_token_type="input"') == 1.0
    assert (
        _metric_sample_sum(body, f"{PROM_TOKEN_USAGE}_sum", 'gen_ai_token_type="input"')
        == prompt_tokens
    )
    assert (
        _metric_sample_sum(body, f"{PROM_TOKEN_USAGE}_count", 'gen_ai_token_type="output"') == 1.0
    )
    assert (
        _metric_sample_sum(body, f"{PROM_TOKEN_USAGE}_sum", 'gen_ai_token_type="output"')
        == completion_tokens
    )


def _assert_usage_histograms_empty(body: str) -> None:
    assert _metric_sample_sum(body, f"{PROM_OPERATION_DURATION}_count") == 0.0
    assert _metric_sample_sum(body, f"{PROM_TOKEN_USAGE}_count") == 0.0


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
    assert exporter_headers("http://[::1]:6006", "secret") == {"authorization": "Bearer secret"}
    assert exporter_headers("https://phoenix.example", None) is None
    with caplog.at_level("WARNING"):
        assert exporter_headers("http://host.docker.internal:6006", "secret") == {
            "authorization": "Bearer secret"
        }
        assert exporter_headers("http://phoenix.example:6006", "secret") is None
    assert "not sent" in caplog.text
    assert "phoenix.example" in caplog.text
    assert "secret" not in caplog.text


def test_export_traces_defaults_off() -> None:
    # Field default, not Settings() — that still reads the process env / .env.
    assert Settings.model_fields["export_traces"].default is False


def test_each_app_keeps_its_own_exporter() -> None:
    first = InMemorySpanExporter()
    second = InMemorySpanExporter()
    app_one = create_app(
        isolated_settings(export_traces=True, phoenix_collector_endpoint="http://localhost:6006"),
        _QuietLLM(),
        SimpleSpanProcessor(first),
    )
    app_two = create_app(
        isolated_settings(export_traces=True, phoenix_collector_endpoint="http://phoenix:6006"),
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
        isolated_settings(app_env="dev", export_traces=True),
        _QuietLLM(),
        SimpleSpanProcessor(exporter),
    )
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    assert client.get("/metrics").status_code == 200
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200
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
    app = create_app(isolated_settings(export_traces=False), _QuietLLM())
    client = TestClient(app)
    assert client.post("/client-events", json={"outcome": CLIENT_OUTCOME_FAIL}).status_code == 204
    assert (
        client.post("/client-events", json={"outcome": CLIENT_OUTCOME_RATE_LIMIT}).status_code
        == 204
    )
    assert (
        client.post("/client-events", json={"outcome": CLIENT_OUTCOME_MODEL_BUSY}).status_code
        == 204
    )
    assert client.post("/client-events", json={"outcome": CLIENT_OUTCOME_CANCEL}).status_code == 204
    # Defense in depth: unknown labels never touch the scrape counter.
    record_client_suggest_outcome("not-an-outcome")
    record_client_suggest_outcome("success")

    body = client.get("/metrics").text
    assert (
        labeled_counter(body, PROM_CLIENT_SUGGEST_OUTCOME, f'outcome="{CLIENT_OUTCOME_FAIL}"')
        == 1.0
    )
    assert (
        labeled_counter(body, PROM_CLIENT_SUGGEST_OUTCOME, f'outcome="{CLIENT_OUTCOME_RATE_LIMIT}"')
        == 1.0
    )
    assert (
        labeled_counter(body, PROM_CLIENT_SUGGEST_OUTCOME, f'outcome="{CLIENT_OUTCOME_MODEL_BUSY}"')
        == 1.0
    )
    assert (
        labeled_counter(body, PROM_CLIENT_SUGGEST_OUTCOME, f'outcome="{CLIENT_OUTCOME_CANCEL}"')
        == 1.0
    )
    assert _metric_sample_sum(body, f"{PROM_CLIENT_SUGGEST_OUTCOME}_total") == 4.0


def test_http_body_size_metrics_dropped_active_and_duration_kept() -> None:
    """Scrape surface matches GenAI ops: drop size histograms, keep duration + active."""
    app = create_app(isolated_settings(export_traces=False), _QuietLLM())
    client = TestClient(app)
    assert client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"}).status_code == 200

    body = client.get("/metrics").text
    assert _suggest_status_count(body, 200) == 1.0
    assert "http_server_active_requests" in body
    assert "http_server_request_size_bytes" not in body
    assert "http_server_response_size_bytes" not in body


def test_metrics_exposes_gen_ai_series_after_suggest() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _ollama_chat_json('{"move": "right", "reason": "Opens the row."}')

    settings = isolated_settings(export_traces=False, ollama_model="test-model")
    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="http://ollama.test") as http:
        app = create_app(settings, OllamaClient(settings, client=http))
        client = TestClient(app)
        assert client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"}).status_code == 200
        metrics = client.get("/metrics")

    assert metrics.status_code == 200
    body = metrics.text
    assert labeled_counter(body, PROM_REQUEST_COUNT, 'gen_ai_request_outcome="success"') == 1.0
    assert labeled_counter(body, PROM_REQUEST_COUNT, 'gen_ai_request_outcome="error"') == 0.0
    assert labeled_counter(body, PROM_REQUEST_COUNT, 'gen_ai_request_outcome="timeout"') == 0.0
    assert labeled_counter(body, PROM_REQUEST_COUNT, 'gen_ai_request_outcome="cancelled"') == 0.0
    assert labeled_counter(body, PROM_SUGGEST_SOURCE, 'suggest_source="llm"') == 1.0
    assert labeled_counter(body, PROM_SUGGEST_SOURCE, 'suggest_source="fallback"') == 0.0
    assert labeled_counter(body, PROM_SUGGEST_SOURCE, 'suggest_source="expectimax"') == 0.0
    _assert_usage_histograms_recorded(body, prompt_tokens=40.0, completion_tokens=12.0)
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

    assert (
        _metric_sample_sum(
            body,
            f"{PROM_REQUEST_COUNT}_total",
            'gen_ai_request_outcome="error"',
            'error_type="request"',
        )
        == 1.0
    )
    assert labeled_counter(body, PROM_REQUEST_COUNT, 'gen_ai_request_outcome="error"') == 1.0
    assert labeled_counter(body, PROM_REQUEST_COUNT, 'gen_ai_request_outcome="success"') == 0.0
    assert labeled_counter(body, PROM_REQUEST_COUNT, 'gen_ai_request_outcome="timeout"') == 0.0
    assert labeled_counter(body, PROM_REQUEST_COUNT, 'gen_ai_request_outcome="cancelled"') == 0.0
    assert labeled_counter(body, PROM_SUGGEST_SOURCE, 'suggest_source="fallback"') == 1.0
    assert labeled_counter(body, PROM_SUGGEST_SOURCE, 'suggest_source="llm"') == 0.0
    _assert_usage_histograms_empty(body)


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

    assert labeled_counter(body, PROM_REQUEST_COUNT, 'gen_ai_request_outcome="timeout"') == 1.0
    assert labeled_counter(body, PROM_REQUEST_COUNT, 'gen_ai_request_outcome="error"') == 0.0
    assert labeled_counter(body, PROM_REQUEST_COUNT, 'gen_ai_request_outcome="success"') == 0.0
    assert labeled_counter(body, PROM_REQUEST_COUNT, 'gen_ai_request_outcome="cancelled"') == 0.0
    assert labeled_counter(body, PROM_SUGGEST_SOURCE, 'suggest_source="fallback"') == 1.0
    assert labeled_counter(body, PROM_SUGGEST_SOURCE, 'suggest_source="llm"') == 0.0
    _assert_usage_histograms_empty(body)


def test_cancelled_llm_records_cancelled_not_error() -> None:
    """Disconnect cancel mid-Ollama attempt → gen_ai cancelled + spans not ERROR."""
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
    assert labeled_counter(body, PROM_REQUEST_COUNT, 'gen_ai_request_outcome="cancelled"') == 1.0
    assert labeled_counter(body, PROM_REQUEST_COUNT, 'gen_ai_request_outcome="error"') == 0.0
    assert labeled_counter(body, PROM_REQUEST_COUNT, 'gen_ai_request_outcome="success"') == 0.0
    assert labeled_counter(body, PROM_REQUEST_COUNT, 'gen_ai_request_outcome="timeout"') == 0.0
    # Cancelled mid-pipeline: no completed suggest_source increment or usage histograms.
    assert labeled_counter(body, PROM_SUGGEST_SOURCE, 'suggest_source="llm"') == 0.0
    assert labeled_counter(body, PROM_SUGGEST_SOURCE, 'suggest_source="fallback"') == 0.0
    assert labeled_counter(body, PROM_SUGGEST_SOURCE, 'suggest_source="expectimax"') == 0.0
    _assert_usage_histograms_empty(body)

    finished = exporter.get_finished_spans()
    assert len(finished) == 3
    spans = {span.name: span for span in finished}
    assert set(spans) == {"POST /suggest", "suggest", "ollama chat"}
    assert spans["ollama chat"].status.status_code == StatusCode.UNSET
    assert spans["suggest"].status.status_code == StatusCode.UNSET
    assert spans["POST /suggest"].status.status_code == StatusCode.UNSET
    assert "cancelled" in (spans["ollama chat"].attributes.get(OUTPUT_VALUE) or "")
    assert "cancelled" in (spans["suggest"].attributes.get(OUTPUT_VALUE) or "")
    assert "cancelled" in (spans["POST /suggest"].attributes.get(OUTPUT_VALUE) or "")


def test_cancel_already_set_records_cancelled_without_ollama_post() -> None:
    """Attempt span opens, cancel already set → gen_ai cancelled, no HTTP to Ollama."""
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
    assert labeled_counter(body, PROM_REQUEST_COUNT, 'gen_ai_request_outcome="cancelled"') == 1.0
    assert labeled_counter(body, PROM_REQUEST_COUNT, 'gen_ai_request_outcome="error"') == 0.0
    assert labeled_counter(body, PROM_SUGGEST_SOURCE, 'suggest_source="llm"') == 0.0
    assert labeled_counter(body, PROM_SUGGEST_SOURCE, 'suggest_source="fallback"') == 0.0
    _assert_usage_histograms_empty(body)

    finished = exporter.get_finished_spans()
    assert len(finished) == 3
    spans = {span.name: span for span in finished}
    assert spans["ollama chat"].status.status_code == StatusCode.UNSET
    assert spans["suggest"].status.status_code == StatusCode.UNSET
    assert spans["POST /suggest"].status.status_code == StatusCode.UNSET
    assert "cancelled" in (spans["ollama chat"].attributes.get(OUTPUT_VALUE) or "")
    assert "cancelled" in (spans["POST /suggest"].attributes.get(OUTPUT_VALUE) or "")


def test_between_attempt_cancel_records_cancelled() -> None:
    """Fail attempt 1, cancel before attempt 2 → cancelled (not a second error)."""
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
    # First attempt still counts as a model error; cancel must not add another.
    assert labeled_counter(body, PROM_REQUEST_COUNT, 'gen_ai_request_outcome="error"') == 1.0
    assert labeled_counter(body, PROM_REQUEST_COUNT, 'error_type="parse"') == 1.0
    assert labeled_counter(body, PROM_REQUEST_COUNT, 'gen_ai_request_outcome="cancelled"') == 1.0
    assert labeled_counter(body, PROM_SUGGEST_SOURCE, 'suggest_source="llm"') == 0.0
    assert labeled_counter(body, PROM_SUGGEST_SOURCE, 'suggest_source="fallback"') == 0.0

    finished = exporter.get_finished_spans()
    attempts = [s for s in finished if s.name == "ollama chat"]
    assert len(attempts) == 2
    assert attempts[0].status.status_code == StatusCode.ERROR
    assert attempts[1].status.status_code == StatusCode.UNSET
    assert "cancelled" in (attempts[1].attributes.get(OUTPUT_VALUE) or "")

    suggest = next(s for s in finished if s.name == "suggest")
    root = next(s for s in finished if s.name == "POST /suggest")
    assert suggest.status.status_code == StatusCode.UNSET
    assert "cancelled" in (suggest.attributes.get(OUTPUT_VALUE) or "")
    assert root.status.status_code == StatusCode.UNSET
    assert "cancelled" in (root.attributes.get(OUTPUT_VALUE) or "")


def test_metrics_counts_expectimax_suggest_source() -> None:
    app = create_app(isolated_settings(export_traces=False), UnusedLLM())
    client = TestClient(app)
    assert (
        client.post("/suggest", json={"board": OPEN_BOARD, "mode": "expectimax"}).status_code == 200
    )
    body = client.get("/metrics").text
    assert labeled_counter(body, PROM_SUGGEST_SOURCE, 'suggest_source="expectimax"') == 1.0
    assert labeled_counter(body, PROM_SUGGEST_SOURCE, 'suggest_source="llm"') == 0.0
    assert labeled_counter(body, PROM_SUGGEST_SOURCE, 'suggest_source="fallback"') == 0.0
    assert _metric_sample_sum(body, f"{PROM_REQUEST_COUNT}_total") == 0.0
    _assert_usage_histograms_empty(body)


def test_suggest_status_count_is_order_independent_and_sums_series() -> None:
    sample = "\n".join(
        [
            "http_server_duration_milliseconds_count{"
            'http_target="/suggest",http_status_code="200",net_host_port="8000"} 2.0',
            "http_server_duration_milliseconds_count{"
            'http_status_code="200",http_target="/suggest",net_host_port="8001"} 3.0',
            "http_server_duration_milliseconds_count{"
            'http_status_code="200",http_target="/health"} 9.0',
            "http_server_duration_milliseconds_count{"
            'http_status_code="429",http_target="/suggest"} 1.0',
        ]
    )
    assert _suggest_status_count(sample, 200) == 5.0
    assert _suggest_status_count(sample, 429) == 1.0
    assert _suggest_status_count(sample, 499) == 0.0


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
    assert _suggest_status_count(body, 200) == 1.0
    assert _suggest_status_count(body, 422) == 1.0
    assert _suggest_status_count(body, 409) == 1.0
    assert labeled_counter(body, PROM_SUGGEST_SOURCE, 'suggest_source="llm"') == 1.0
    assert labeled_counter(body, PROM_SUGGEST_SOURCE, 'suggest_source="fallback"') == 0.0

    # Spend 429
    spend_app = create_app(
        isolated_settings(export_traces=False),
        _QuietLLM(),
        rate_limiters={
            "llm": SuggestRateLimiter(1, 60),
            "expectimax": SuggestRateLimiter(30, 60),
        },
    )
    spend_client = TestClient(spend_app)
    assert (
        spend_client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"}).status_code == 200
    )
    spend_429 = spend_client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"})
    assert spend_429.status_code == 429
    assert spend_429.headers[HEADER_SUGGEST_LIMIT] == "spend"
    spend_body = spend_client.get("/metrics").text
    assert _suggest_status_count(spend_body, 200) == 1.0
    assert _suggest_status_count(spend_body, 429) == 1.0
    assert labeled_counter(spend_body, PROM_SUGGEST_LIMIT_REJECT, 'reason="spend"') == 1.0
    assert labeled_counter(spend_body, PROM_SUGGEST_LIMIT_REJECT, 'reason="capacity"') == 0.0
    assert labeled_counter(spend_body, PROM_SUGGEST_SOURCE, 'suggest_source="llm"') == 1.0
    assert labeled_counter(spend_body, PROM_SUGGEST_SOURCE, 'suggest_source="fallback"') == 0.0

    # Capacity 429
    held_gate = InFlightGate(1)
    held_slot = held_gate.acquire().token
    try:
        cap_app = create_app(
            isolated_settings(export_traces=False),
            UnusedLLM(),
            llm_in_flight=held_gate,
        )
        cap_client = TestClient(cap_app)
        cap_429 = cap_client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"})
        assert cap_429.status_code == 429
        assert cap_429.headers[HEADER_SUGGEST_LIMIT] == "capacity"
        cap_body = cap_client.get("/metrics").text
    finally:
        held_gate.release(held_slot)
    assert _suggest_status_count(cap_body, 429) == 1.0
    assert _suggest_status_count(cap_body, 200) == 0.0
    assert labeled_counter(cap_body, PROM_SUGGEST_LIMIT_REJECT, 'reason="capacity"') == 1.0
    assert labeled_counter(cap_body, PROM_SUGGEST_LIMIT_REJECT, 'reason="spend"') == 0.0
    assert _metric_sample_sum(cap_body, f"{PROM_SUGGEST_SOURCE}_total") == 0.0

    # Cancel 499
    class _CancelLLM:
        def suggest_move(self, *args: object, **kwargs: object) -> ModelSuggestion:
            raise SuggestCancelled()

    cancel_app = create_app(isolated_settings(export_traces=False), _CancelLLM())
    cancel_client = TestClient(cancel_app)
    assert (
        cancel_client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"}).status_code == 499
    )
    cancel_body = cancel_client.get("/metrics").text
    assert _suggest_status_count(cancel_body, 499) == 1.0
    assert _suggest_status_count(cancel_body, 200) == 0.0
    assert _metric_sample_sum(cancel_body, f"{PROM_SUGGEST_SOURCE}_total") == 0.0


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

    assert (
        _metric_sample_sum(
            body,
            f"{PROM_REQUEST_COUNT}_total",
            'gen_ai_request_outcome="error"',
            'error_type="response"',
        )
        == 1.0
    )
    assert labeled_counter(body, PROM_REQUEST_COUNT, 'error_type="request"') == 0.0
    assert labeled_counter(body, PROM_SUGGEST_SOURCE, 'suggest_source="fallback"') == 1.0
    assert labeled_counter(body, PROM_SUGGEST_SOURCE, 'suggest_source="llm"') == 0.0
    _assert_usage_histograms_empty(body)


@pytest.mark.parametrize("non_object_json", [[], None, "str", 123])
def test_metrics_counts_non_object_json_as_response_error_type(non_object_json: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Encode explicitly because httpx.Response(json=None) treats None as "no body".
        return httpx.Response(
            200,
            content=json.dumps(non_object_json).encode(),
            headers={"content-type": "application/json"},
        )

    settings = isolated_settings(export_traces=False, llm_max_attempts=1)
    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="http://ollama.test") as http:
        app = create_app(settings, OllamaClient(settings, client=http))
        client = TestClient(app)
        assert client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"}).status_code == 200
        body = client.get("/metrics").text

    assert (
        _metric_sample_sum(
            body,
            f"{PROM_REQUEST_COUNT}_total",
            'error_type="response"',
            'gen_ai_request_outcome="error"',
        )
        == 1.0
    )
    assert labeled_counter(body, PROM_REQUEST_COUNT, 'error_type="response"') == 1.0
    assert labeled_counter(body, PROM_REQUEST_COUNT, 'error_type="request"') == 0.0
    assert labeled_counter(body, PROM_SUGGEST_SOURCE, 'suggest_source="fallback"') == 1.0
    assert labeled_counter(body, PROM_SUGGEST_SOURCE, 'suggest_source="llm"') == 0.0
    _assert_usage_histograms_empty(body)


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

    assert (
        _metric_sample_sum(
            body,
            f"{PROM_REQUEST_COUNT}_total",
            'gen_ai_request_outcome="error"',
            'error_type="parse"',
        )
        == 1.0
    )
    assert labeled_counter(body, PROM_REQUEST_COUNT, 'gen_ai_request_outcome="error"') == 1.0
    assert labeled_counter(body, PROM_REQUEST_COUNT, 'gen_ai_request_outcome="success"') == 0.0
    assert labeled_counter(body, PROM_SUGGEST_SOURCE, 'suggest_source="fallback"') == 1.0
    assert labeled_counter(body, PROM_SUGGEST_SOURCE, 'suggest_source="llm"') == 0.0
    _assert_usage_histograms_recorded(body, prompt_tokens=40.0, completion_tokens=12.0)


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

    assert (
        _metric_sample_sum(
            body,
            f"{PROM_REQUEST_COUNT}_total",
            'gen_ai_request_outcome="error"',
            'error_type="illegal_move"',
        )
        == 1.0
    )
    assert labeled_counter(body, PROM_REQUEST_COUNT, 'gen_ai_request_outcome="error"') == 1.0
    assert labeled_counter(body, PROM_REQUEST_COUNT, 'gen_ai_request_outcome="success"') == 0.0
    assert labeled_counter(body, PROM_SUGGEST_SOURCE, 'suggest_source="fallback"') == 1.0
    assert labeled_counter(body, PROM_SUGGEST_SOURCE, 'suggest_source="llm"') == 0.0
    _assert_usage_histograms_recorded(body, prompt_tokens=40.0, completion_tokens=12.0)


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
    assert SpanAttributes.LLM_RESPONSE_MODEL_NAME not in attrs
    assert attrs[LLM_FINISH_REASON] == "stop"
    assert "Legal moves:" in attrs[LLM_INPUT_MESSAGE_CONTENT]
    assert attrs[INPUT_VALUE] == attrs[LLM_INPUT_MESSAGE_CONTENT]
    assert '"move": "right"' in attrs[LLM_OUTPUT_MESSAGE_CONTENT]
    assert attrs[OUTPUT_VALUE] == attrs[LLM_OUTPUT_MESSAGE_CONTENT]
    assert attrs[LLM_TOKEN_COUNT_PROMPT] == 40
    assert attrs[LLM_TOKEN_COUNT_COMPLETION] == 12
    assert attrs[LLM_TOKEN_COUNT_TOTAL] == 52
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


def test_record_llm_usage_non_default_branches() -> None:
    """Response model override, zero cache_read omission, and ttd - eval_time TTFT fallback."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "gemma4:27b-q4",
                "message": {"content": '{"move": "right", "reason": "Opens the row."}'},
                "done_reason": "stop",
                "prompt_eval_count": 25,
                "prompt_eval_cached_count": 0,
                "eval_count": 5,
                # Omit load_duration and prompt_eval_duration so TTFT falls back to ttd - eval.
                "eval_duration": 250_000_000,
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
        client = TestClient(app)
        response = client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"})
        body = client.get("/metrics").text

    assert response.status_code == 200
    llm_span = next(s for s in exporter.get_finished_spans() if s.name == "ollama chat")
    attrs = llm_span.attributes
    assert attrs[LLM_MODEL_NAME] == "test-model"
    assert attrs[SpanAttributes.LLM_RESPONSE_MODEL_NAME] == "gemma4:27b-q4"
    assert LLM_TOKEN_COUNT_CACHE_READ not in attrs
    assert attrs[LLM_TOKEN_COUNT_PROMPT] == 25
    assert attrs[LLM_TOKEN_COUNT_COMPLETION] == 5
    assert attrs[LLM_TOKEN_COUNT_TOTAL] == 30

    first_token = next(
        event for event in llm_span.events if event.name == "First Token Stream Event"
    )
    assert first_token.attributes["ttft"] == pytest.approx(0.35)
    assert "load" not in first_token.attributes
    assert "prompt_eval" not in first_token.attributes
    _assert_usage_histograms_recorded(body, prompt_tokens=25.0, completion_tokens=5.0)


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
    assert llm_spans[0].status.status_code == StatusCode.ERROR
    assert llm_spans[1].status.status_code == StatusCode.UNSET
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
    assert llm_spans[1].status.status_code == StatusCode.UNSET
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
    assert spans["suggest"].status.status_code == StatusCode.UNSET
    assert spans["POST /suggest"].status.status_code == StatusCode.UNSET
    assert '"source": "fallback"' in spans["suggest"].attributes[OUTPUT_VALUE]


def test_stuck_board_marks_http_span_without_llm() -> None:
    exporter = InMemorySpanExporter()
    app = create_app(
        isolated_settings(export_traces=True),
        UnusedLLM(),
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


@pytest.mark.parametrize("rejection_kind", ["422", "spend_429", "capacity_429"])
def test_pre_suggester_422_and_429_emit_single_unset_http_span_without_io(
    rejection_kind: str,
) -> None:
    """422 and both 429 gates stop before set_json_io / suggest child / suggest_source."""
    exporter = InMemorySpanExporter()
    held_gate = InFlightGate(1)
    held_slot: object | None = None
    rate_limiters = None

    if rejection_kind == "spend_429":
        exhausted = SuggestRateLimiter(1, 60)
        assert exhausted.allow().retry_after is None
        rate_limiters = {
            "llm": exhausted,
            "expectimax": SuggestRateLimiter(30, 60),
        }
    elif rejection_kind == "capacity_429":
        held_slot = held_gate.acquire().token

    try:
        app = create_app(
            isolated_settings(export_traces=True),
            UnusedLLM(),
            SimpleSpanProcessor(exporter),
            rate_limiters=rate_limiters,
            llm_in_flight=held_gate if rejection_kind == "capacity_429" else None,
        )
        client = TestClient(app)
        payload = (
            {"board": [[0, 0, 0, 0]], "mode": "llm"}
            if rejection_kind == "422"
            else {"board": OPEN_BOARD, "mode": "llm"}
        )
        response = client.post("/suggest", json=payload)
        body = client.get("/metrics").text
    finally:
        if held_slot is not None:
            held_gate.release(held_slot)

    expected_status = 422 if rejection_kind == "422" else 429
    assert response.status_code == expected_status

    finished = exporter.get_finished_spans()
    assert len(finished) == 1
    root = finished[0]
    assert root.name == "POST /suggest"
    assert root.attributes[OPENINFERENCE_SPAN_KIND] == SPAN_KIND_CHAIN
    assert root.status.status_code == StatusCode.UNSET
    assert INPUT_VALUE not in root.attributes
    assert OUTPUT_VALUE not in root.attributes

    assert _suggest_status_count(body, expected_status) == 1.0
    assert _metric_sample_sum(body, f"{PROM_SUGGEST_SOURCE}_total") == 0.0
    assert _metric_sample_sum(body, f"{PROM_REQUEST_COUNT}_total") == 0.0
    if rejection_kind == "spend_429":
        assert response.headers[HEADER_SUGGEST_LIMIT] == "spend"
        assert labeled_counter(body, PROM_SUGGEST_LIMIT_REJECT, 'reason="spend"') == 1.0
        assert labeled_counter(body, PROM_SUGGEST_LIMIT_REJECT, 'reason="capacity"') == 0.0
    elif rejection_kind == "capacity_429":
        assert response.headers[HEADER_SUGGEST_LIMIT] == "capacity"
        assert labeled_counter(body, PROM_SUGGEST_LIMIT_REJECT, 'reason="capacity"') == 1.0
        assert labeled_counter(body, PROM_SUGGEST_LIMIT_REJECT, 'reason="spend"') == 0.0
    else:
        assert _metric_sample_sum(body, f"{PROM_SUGGEST_LIMIT_REJECT}_total") == 0.0


def test_expectimax_200_and_fallback_span_and_metric_exit_tuples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expectimax 200 vs Expectimax fallback: 2 CHAIN spans, 0 LLM spans, span-only failures."""
    # (1) Normal 200 expectimax
    ok_exporter = InMemorySpanExporter()
    ok_app = create_app(
        isolated_settings(export_traces=True),
        UnusedLLM(),
        SimpleSpanProcessor(ok_exporter),
    )
    ok_client = TestClient(ok_app)
    ok_resp = ok_client.post("/suggest", json={"board": OPEN_BOARD, "mode": "expectimax"})
    ok_body = ok_client.get("/metrics").text

    assert ok_resp.status_code == 200
    assert ok_resp.json()["source"] == "expectimax"
    ok_finished = ok_exporter.get_finished_spans()
    assert len(ok_finished) == 2
    assert {s.name for s in ok_finished} == {"POST /suggest", "suggest"}
    ok_spans = {s.name: s for s in ok_finished}
    assert ok_spans["POST /suggest"].attributes[OPENINFERENCE_SPAN_KIND] == SPAN_KIND_CHAIN
    assert ok_spans["suggest"].attributes[OPENINFERENCE_SPAN_KIND] == SPAN_KIND_CHAIN
    assert ok_spans["POST /suggest"].status.status_code == StatusCode.UNSET
    assert ok_spans["suggest"].status.status_code == StatusCode.UNSET
    assert ok_spans["suggest"].parent is not None
    assert ok_spans["suggest"].parent.span_id == ok_spans["POST /suggest"].context.span_id
    assert "failures" not in json.loads(ok_spans["suggest"].attributes[OUTPUT_VALUE])
    assert "failures" not in json.loads(ok_spans["POST /suggest"].attributes[OUTPUT_VALUE])
    assert labeled_counter(ok_body, PROM_SUGGEST_SOURCE, 'suggest_source="expectimax"') == 1.0
    assert labeled_counter(ok_body, PROM_SUGGEST_SOURCE, 'suggest_source="fallback"') == 0.0
    assert _metric_sample_sum(ok_body, f"{PROM_REQUEST_COUNT}_total") == 0.0

    # (2) Expectimax 200 fallback when choose_move returns None
    monkeypatch.setattr("app.suggester.choose_move", lambda board, cancel=None: None)
    fb_exporter = InMemorySpanExporter()
    fb_app = create_app(
        isolated_settings(export_traces=True),
        UnusedLLM(),
        SimpleSpanProcessor(fb_exporter),
    )
    fb_client = TestClient(fb_app)
    fb_resp = fb_client.post("/suggest", json={"board": OPEN_BOARD, "mode": "expectimax"})
    fb_body = fb_client.get("/metrics").text

    assert fb_resp.status_code == 200
    assert fb_resp.json()["source"] == "fallback"
    assert "failures" not in fb_resp.json()
    fb_finished = fb_exporter.get_finished_spans()
    assert len(fb_finished) == 2
    assert {s.name for s in fb_finished} == {"POST /suggest", "suggest"}
    fb_spans = {s.name: s for s in fb_finished}
    assert fb_spans["POST /suggest"].attributes[OPENINFERENCE_SPAN_KIND] == SPAN_KIND_CHAIN
    assert fb_spans["suggest"].attributes[OPENINFERENCE_SPAN_KIND] == SPAN_KIND_CHAIN
    assert fb_spans["POST /suggest"].status.status_code == StatusCode.UNSET
    assert fb_spans["suggest"].status.status_code == StatusCode.UNSET
    assert fb_spans["suggest"].parent is not None
    assert fb_spans["suggest"].parent.span_id == fb_spans["POST /suggest"].context.span_id

    suggest_out = json.loads(fb_spans["suggest"].attributes[OUTPUT_VALUE])
    root_out = json.loads(fb_spans["POST /suggest"].attributes[OUTPUT_VALUE])
    assert suggest_out["source"] == "fallback"
    assert suggest_out["failures"] == ["no scored move"]
    assert root_out["source"] == "fallback"
    assert "failures" not in root_out

    assert labeled_counter(fb_body, PROM_SUGGEST_SOURCE, 'suggest_source="fallback"') == 1.0
    assert labeled_counter(fb_body, PROM_SUGGEST_SOURCE, 'suggest_source="expectimax"') == 0.0
    assert labeled_counter(fb_body, PROM_SUGGEST_SOURCE, 'suggest_source="llm"') == 0.0
    assert _metric_sample_sum(fb_body, f"{PROM_REQUEST_COUNT}_total") == 0.0
    _assert_usage_histograms_empty(fb_body)


def test_pre_suggester_vs_mid_expectimax_499_cancel_span_shapes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pre-suggester 499 emits POST /suggest only; mid-Expectimax emits POST /suggest + suggest."""
    # (1) Pre-suggester cancel: cancel Event already set before MoveSuggester opens `suggest`.
    real_suggest = MoveSuggester.suggest

    def preset_cancel_suggest(
        self: MoveSuggester,
        board: list[list[int]],
        mode: str,
        cancel: threading.Event | None = None,
    ):
        assert cancel is not None
        cancel.set()
        return real_suggest(self, board, mode, cancel)

    pre_exporter = InMemorySpanExporter()
    with monkeypatch.context() as mp:
        mp.setattr(MoveSuggester, "suggest", preset_cancel_suggest)
        pre_app = create_app(
            isolated_settings(export_traces=True),
            UnusedLLM(),
            SimpleSpanProcessor(pre_exporter),
        )
        pre_client = TestClient(pre_app)
        pre_resp = pre_client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"})
        pre_body = pre_client.get("/metrics").text

    assert pre_resp.status_code == 499
    pre_finished = pre_exporter.get_finished_spans()
    assert len(pre_finished) == 1
    pre_root = pre_finished[0]
    assert pre_root.name == "POST /suggest"
    assert pre_root.status.status_code == StatusCode.UNSET
    assert "cancelled" in (pre_root.attributes.get(OUTPUT_VALUE) or "")
    assert _suggest_status_count(pre_body, 499) == 1.0
    assert _metric_sample_sum(pre_body, f"{PROM_REQUEST_COUNT}_total") == 0.0
    assert _metric_sample_sum(pre_body, f"{PROM_SUGGEST_SOURCE}_total") == 0.0
    _assert_usage_histograms_empty(pre_body)

    # (2) Mid-Expectimax cancel: `suggest` span is open when choose_move sees cancel set.
    def cancel_inside_expectimax(board: list[list[int]], *, cancel: threading.Event | None = None):
        assert cancel is not None
        cancel.set()
        return real_choose_move(board, cancel=cancel)

    mid_exporter = InMemorySpanExporter()
    with monkeypatch.context() as mp:
        mp.setattr("app.suggester.choose_move", cancel_inside_expectimax)
        mid_app = create_app(
            isolated_settings(export_traces=True),
            UnusedLLM(),
            SimpleSpanProcessor(mid_exporter),
        )
        mid_client = TestClient(mid_app)
        mid_resp = mid_client.post("/suggest", json={"board": OPEN_BOARD, "mode": "expectimax"})
        mid_body = mid_client.get("/metrics").text

    assert mid_resp.status_code == 499
    mid_finished = mid_exporter.get_finished_spans()
    assert len(mid_finished) == 2
    assert {s.name for s in mid_finished} == {"POST /suggest", "suggest"}
    mid_spans = {s.name: s for s in mid_finished}
    assert mid_spans["POST /suggest"].status.status_code == StatusCode.UNSET
    assert mid_spans["suggest"].status.status_code == StatusCode.UNSET
    assert "cancelled" in (mid_spans["POST /suggest"].attributes.get(OUTPUT_VALUE) or "")
    assert "cancelled" in (mid_spans["suggest"].attributes.get(OUTPUT_VALUE) or "")
    assert _suggest_status_count(mid_body, 499) == 1.0
    assert _metric_sample_sum(mid_body, f"{PROM_REQUEST_COUNT}_total") == 0.0
    assert _metric_sample_sum(mid_body, f"{PROM_SUGGEST_SOURCE}_total") == 0.0
    _assert_usage_histograms_empty(mid_body)


def test_labeled_counter_sums_matching_subseries() -> None:
    sample = "\n".join(
        [
            "gen_ai_client_request_count_total{"
            'error_type="parse",gen_ai_request_outcome="error"} 2.0',
            "gen_ai_client_request_count_total{"
            'error_type="request",gen_ai_request_outcome="error"} 1.0',
            'gen_ai_client_request_count_total{gen_ai_request_outcome="cancelled"} 4.0',
        ]
    )
    assert (
        labeled_counter(sample, "gen_ai_client_request_count", 'gen_ai_request_outcome="error"')
        == 3.0
    )
    assert (
        labeled_counter(sample, "gen_ai_client_request_count", 'gen_ai_request_outcome="ok"') == 0.0
    )
