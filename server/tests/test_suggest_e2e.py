"""End-to-end suggest paths.

LLM cases marked ``e2e`` need a local Ollama + configured model (``pytest --e2e``).
HTTP contract cases (health, validation, stuck board, rate limit, beacons,
fallback via unreachable Ollama, expectimax) run in the default suite so CI
still covers every status / source without the model.
"""

from __future__ import annotations

import os
import re

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.moves import legal_moves
from app.telemetry import PROM_CLIENT_SUGGEST_OUTCOME
from helpers import (
    E2E_BOARD_COUNT,
    E2E_RUN_COUNT,
    E2E_SUGGEST_CALLS,
    SORTED_ROW,
    isolated_settings,
)

MERGE_BOARD = [
    [2, 2, 4, 8],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
]

CORNER_BOARD = [
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

# Extra LLM posts on the shared e2e app beyond the parametrized matrix
# (traceparent continuation + /metrics after success).
E2E_EXTRA_LLM_CALLS = 2

# One module-scoped app serves every parametrized case. Size the rate limit
# from this list so adding a board or run cannot silently hit the default cap.
E2E_BOARDS = [MERGE_BOARD, CORNER_BOARD]
E2E_RUN_IDS = [1, 2, 3]
assert len(E2E_BOARDS) == E2E_BOARD_COUNT
assert len(E2E_RUN_IDS) == E2E_RUN_COUNT
assert len(E2E_BOARDS) * len(E2E_RUN_IDS) == E2E_SUGGEST_CALLS

TRACEPARENT_RE = re.compile(
    r"^00-[0-9a-f]{32}-[0-9a-f]{16}-0[01]$",
)


def _unavailable(base_url: str, model: str) -> str | None:
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=2)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return f"Ollama is not reachable at {base_url}: {exc}"
    names = [item.get("name", "") for item in response.json().get("models", [])]
    if model not in names:
        return f"{model} is not installed in Ollama"
    return None


def _ollama_env() -> tuple[str, str]:
    model = os.environ.get("OLLAMA_MODEL", "gemma4:latest")
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    return model, base_url


@pytest.fixture(scope="module")
def suggest_client() -> TestClient:
    model, base_url = _ollama_env()
    reason = _unavailable(base_url, model)
    if reason:
        pytest.skip(reason)
    settings = isolated_settings(
        app_env="prod",
        ollama_model=model,
        ollama_base_url=base_url,
        llm_max_attempts=3,
        # Default process cap is 5; this suite shares one app for more posts.
        suggest_rate_limit_requests=E2E_SUGGEST_CALLS + E2E_EXTRA_LLM_CALLS,
        suggest_rate_limit_window_seconds=60,
    )
    # Prod parses the prompt's JSON. The schema format stays off.
    assert settings.ollama_structured_output is False
    return TestClient(create_app(settings))


# --- Real Ollama (opt-in with --e2e) -----------------------------------------


@pytest.mark.e2e
@pytest.mark.parametrize("board", E2E_BOARDS, ids=["merge", "corner"])
@pytest.mark.parametrize("run", E2E_RUN_IDS)
def test_gemma_returns_a_legal_move_and_a_short_reason(
    suggest_client: TestClient,
    board: list[list[int]],
    run: int,
) -> None:
    response = suggest_client.post("/suggest", json={"board": board, "mode": "llm"})
    assert response.status_code == 200, f"run {run}"
    body = response.json()
    assert body["mode"] == "llm"
    assert body["source"] == "llm"
    assert body["move"] in legal_moves(board)
    words = body["reason"].split()
    assert 1 <= len(words) <= 50


@pytest.mark.e2e
def test_llm_accepts_client_traceparent(suggest_client: TestClient) -> None:
    # Browser api.js sends a hand-rolled W3C header; the server must accept it.
    traceparent = "00-" + ("a" * 32) + "-" + ("b" * 16) + "-01"
    assert TRACEPARENT_RE.match(traceparent)
    response = suggest_client.post(
        "/suggest",
        json={"board": CORNER_BOARD, "mode": "llm"},
        headers={"traceparent": traceparent},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "llm"
    assert body["move"] in legal_moves(CORNER_BOARD)


@pytest.mark.e2e
def test_metrics_expose_gen_ai_after_real_llm(suggest_client: TestClient) -> None:
    response = suggest_client.post("/suggest", json={"board": MERGE_BOARD, "mode": "llm"})
    assert response.status_code == 200
    assert response.json()["source"] == "llm"

    metrics = suggest_client.get("/metrics")
    assert metrics.status_code == 200
    text = metrics.text
    assert "gen_ai_client_request_count_total" in text
    assert 'gen_ai_request_outcome="success"' in text
    assert 'suggest_source="llm"' in text
    assert "gen_ai_client_operation_duration_seconds" in text


# --- HTTP contract (no live model required) ---------------------------------


class _UnusedLLM:
    def suggest_move(self, *args, **kwargs):
        raise AssertionError("expectimax / stuck / validation must not call the model")


def test_health_ok_without_ollama() -> None:
    client = TestClient(create_app(isolated_settings(app_env="prod"), _UnusedLLM()))
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_metrics_always_on() -> None:
    # Endpoint is registered even with no series yet (empty scrape is fine).
    client = TestClient(create_app(isolated_settings(app_env="prod"), _UnusedLLM()))
    assert client.get("/metrics").status_code == 200


def test_suggest_bad_payload_is_422_and_skips_rate_limit() -> None:
    client = TestClient(
        create_app(
            isolated_settings(
                app_env="prod",
                suggest_rate_limit_requests=1,
                suggest_rate_limit_window_seconds=60,
            ),
            _UnusedLLM(),
        )
    )
    bad = client.post("/suggest", json={"board": [[0]], "mode": "llm"})
    assert bad.status_code == 422
    # Validation must not consume the LLM cap.
    ok = client.post("/suggest", json={"board": SORTED_ROW, "mode": "expectimax"})
    assert ok.status_code == 200


def test_suggest_stuck_board_is_409() -> None:
    client = TestClient(create_app(isolated_settings(app_env="prod"), _UnusedLLM()))
    for mode in ("llm", "expectimax"):
        response = client.post("/suggest", json={"board": STUCK_BOARD, "mode": mode})
        assert response.status_code == 409, mode
        assert response.json()["detail"] == "no legal move"


def test_suggest_rate_limit_is_429_with_retry_after() -> None:
    # Real OllamaClient against a closed port so the first /suggest still
    # returns 200 fallback and consumes the LLM bucket before the 429.
    settings = isolated_settings(
        app_env="prod",
        ollama_base_url="http://127.0.0.1:1",
        ollama_model="missing-model",
        llm_max_attempts=1,
        llm_attempt_timeout_seconds=1,
        llm_suggest_budget_seconds=2,
        suggest_rate_limit_requests=1,
        suggest_rate_limit_window_seconds=60,
    )
    client = TestClient(create_app(settings))
    first = client.post("/suggest", json={"board": SORTED_ROW, "mode": "llm"})
    assert first.status_code == 200
    assert first.json()["source"] == "fallback"
    limited = client.post("/suggest", json={"board": SORTED_ROW, "mode": "llm"})
    assert limited.status_code == 429
    assert limited.json()["detail"] == "too many suggestions"
    assert limited.headers.get("retry-after") is not None


def test_expectimax_returns_a_legal_search_move() -> None:
    # Search never talks to Ollama. Keep the smoke next to the LLM e2e tests
    # so both suggest modes are wired here; do not mark it e2e or CI skips it.
    client = TestClient(create_app(isolated_settings(app_env="prod"), _UnusedLLM()))
    response = client.post("/suggest", json={"board": SORTED_ROW, "mode": "expectimax"})
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "expectimax"
    assert body["source"] == "expectimax"
    assert body["move"] == "right"
    assert body["move"] in legal_moves(SORTED_ROW)
    assert body["reason"].startswith("Score of each direction: ")
    assert "Left = N/A" in body["reason"]


def test_unreachable_ollama_falls_back_with_null_reason() -> None:
    # Real OllamaClient against a closed port — same path Compose hit on 501
    # before structured-output was disabled.
    settings = isolated_settings(
        app_env="prod",
        ollama_base_url="http://127.0.0.1:1",
        ollama_model="missing-model",
        llm_max_attempts=1,
        llm_attempt_timeout_seconds=1,
        llm_suggest_budget_seconds=2,
        suggest_rate_limit_requests=5,
    )
    client = TestClient(create_app(settings))
    response = client.post("/suggest", json={"board": CORNER_BOARD, "mode": "llm"})
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "llm"
    assert body["source"] == "fallback"
    assert body["reason"] is None
    assert body["move"] in legal_moves(CORNER_BOARD)


def test_client_events_beacons_and_metrics() -> None:
    client = TestClient(create_app(isolated_settings(app_env="prod"), _UnusedLLM()))
    assert client.post("/client-events", json={"outcome": "fail"}).status_code == 204
    assert client.post("/client-events", json={"outcome": "rate_limit"}).status_code == 204
    assert client.post("/client-events", json={"outcome": "cancel"}).status_code == 422
    assert client.post("/client-events", json={}).status_code == 422

    text = client.get("/metrics").text
    assert PROM_CLIENT_SUGGEST_OUTCOME in text
    assert 'outcome="fail"' in text
    assert 'outcome="rate_limit"' in text
