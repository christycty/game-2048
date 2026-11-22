"""Suggest HTTP contract without a live Ollama model.

Runs in the default suite (CI). Real-model cases live in ``test_suggest_e2e.py``.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.moves import legal_moves
from app.telemetry import PROM_CLIENT_SUGGEST_OUTCOME
from helpers import SORTED_ROW, isolated_settings

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
    assert client.post("/client-events", json={"outcome": "cancel"}).status_code == 204
    assert client.post("/client-events", json={}).status_code == 422
    assert client.post("/client-events", json={"outcome": "success"}).status_code == 422

    text = client.get("/metrics").text
    assert PROM_CLIENT_SUGGEST_OUTCOME in text
    assert 'outcome="fail"' in text
    assert 'outcome="rate_limit"' in text
    assert 'outcome="cancel"' in text
