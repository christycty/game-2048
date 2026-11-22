"""Real-Ollama suggest paths (opt-in with ``pytest --e2e``).

Needs a local Ollama + configured model. HTTP contract coverage without a
live model lives in ``test_suggest_http_contract.py``.
"""

from __future__ import annotations

import os
import re

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.moves import legal_moves
from helpers import (
    E2E_BOARD_COUNT,
    E2E_RATE_LIMIT_REQUESTS,
    E2E_RUN_COUNT,
    E2E_SUGGEST_CALLS,
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

# One module-scoped app serves every parametrized case. Rate limit is a loose
# budget (helpers.E2E_RATE_LIMIT_REQUESTS), not an exact post count.
E2E_BOARDS = [MERGE_BOARD, CORNER_BOARD]
E2E_RUN_IDS = [1, 2, 3]
assert len(E2E_BOARDS) == E2E_BOARD_COUNT
assert len(E2E_RUN_IDS) == E2E_RUN_COUNT
assert len(E2E_BOARDS) * len(E2E_RUN_IDS) == E2E_SUGGEST_CALLS
assert E2E_RATE_LIMIT_REQUESTS > E2E_SUGGEST_CALLS

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
        suggest_rate_limit_requests=E2E_RATE_LIMIT_REQUESTS,
        suggest_rate_limit_window_seconds=60,
    )
    # Prod parses the prompt's JSON. The schema format stays off.
    assert settings.ollama_structured_output is False
    return TestClient(create_app(settings))


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
def test_llm_suggest_with_client_traceparent_header(suggest_client: TestClient) -> None:
    # Smoke: real Ollama path tolerates the browser's hand-rolled W3C header.
    # Span continuation (shared trace_id) is asserted in test_telemetry.py.
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
