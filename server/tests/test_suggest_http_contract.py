"""Suggest HTTP contract without a live Ollama model.

Runs in the default suite (CI). Real-model cases live in ``test_suggest_e2e.py``.

Capacity vs spend use distinct ``detail`` / ``X-Suggest-Limit`` values. Spend
``Retry-After`` is remaining window seconds (often ``60`` when just filled) but
also collapses to ``1`` near window end — do not treat ``Retry-After: 1`` alone
as capacity-only when classifying without the header/detail.
"""

from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.moves import legal_moves
from app.rate_limit import (
    DETAIL_MODEL_BUSY,
    DETAIL_SPEND_CAP,
    HEADER_SUGGEST_LIMIT,
    LIMIT_REASON_CAPACITY,
    LIMIT_REASON_SPEND,
    InFlightGate,
    SuggestRateLimiter,
)
from app.telemetry import PROM_CLIENT_SUGGEST_OUTCOME, PROM_SUGGEST_LIMIT_REJECT
from helpers import (
    OPEN_BOARD,
    SORTED_ROW,
    STUCK_BOARD,
    BlockingExpectimax,
    BlockingLLM,
    FakeLLM,
    FrozenClock,
    UnusedLLM,
    isolated_settings,
    labeled_counter,
)


def test_health_ok_without_ollama() -> None:
    client = TestClient(create_app(isolated_settings(app_env="prod"), UnusedLLM()))
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_metrics_always_on() -> None:
    # Endpoint is registered even with no series yet (empty scrape is fine).
    client = TestClient(create_app(isolated_settings(app_env="prod"), UnusedLLM()))
    assert client.get("/metrics").status_code == 200


_BAD_TILE_BOARDS = [
    [[1, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]],
    [[3, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]],
    [[6, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]],
]


@pytest.mark.parametrize("board", _BAD_TILE_BOARDS)
def test_suggest_non_power_of_two_tile_is_422(board: list[list[int]]) -> None:
    client = TestClient(create_app(isolated_settings(app_env="prod"), UnusedLLM()))
    response = client.post("/suggest", json={"board": board, "mode": "expectimax"})
    assert response.status_code == 422


def test_suggest_bad_payload_is_422_and_skips_rate_limit() -> None:
    llm = FakeLLM(["right"])
    client = TestClient(
        create_app(
            isolated_settings(
                app_env="prod",
                suggest_rate_limit_requests=1,
                suggest_rate_limit_expectimax_requests=1,
                suggest_rate_limit_window_seconds=60,
            ),
            llm,
        )
    )
    bad_llm = client.post("/suggest", json={"board": [[0]], "mode": "llm"})
    assert bad_llm.status_code == 422
    assert llm.calls == 0
    # Validation must not consume the LLM cap.
    ok_llm = client.post("/suggest", json={"board": SORTED_ROW, "mode": "llm"})
    assert ok_llm.status_code == 200
    assert ok_llm.json()["source"] == "llm"
    assert llm.calls == 1
    limited_llm = client.post("/suggest", json={"board": SORTED_ROW, "mode": "llm"})
    assert limited_llm.status_code == 429
    assert limited_llm.headers.get(HEADER_SUGGEST_LIMIT.lower()) == LIMIT_REASON_SPEND

    bad_ex = client.post("/suggest", json={"board": [[0]], "mode": "expectimax"})
    assert bad_ex.status_code == 422
    # Validation must not consume the Expectimax cap either.
    ok_ex = client.post("/suggest", json={"board": SORTED_ROW, "mode": "expectimax"})
    assert ok_ex.status_code == 200
    assert ok_ex.json()["source"] == "expectimax"
    limited_ex = client.post("/suggest", json={"board": SORTED_ROW, "mode": "expectimax"})
    assert limited_ex.status_code == 429
    assert limited_ex.headers.get(HEADER_SUGGEST_LIMIT.lower()) == LIMIT_REASON_SPEND
    assert llm.calls == 1


def test_suggest_stuck_board_is_409() -> None:
    client = TestClient(create_app(isolated_settings(app_env="prod"), UnusedLLM()))
    for mode in ("llm", "expectimax"):
        response = client.post("/suggest", json={"board": STUCK_BOARD, "mode": mode})
        assert response.status_code == 409, mode
        assert response.json()["detail"] == "no legal move"


def test_suggest_stuck_board_does_not_consume_rate_limit() -> None:
    llm = FakeLLM(["right"])
    client = TestClient(
        create_app(
            isolated_settings(
                app_env="prod",
                suggest_rate_limit_requests=1,
                suggest_rate_limit_expectimax_requests=1,
                suggest_rate_limit_window_seconds=60,
            ),
            llm,
        )
    )
    stuck_llm = client.post("/suggest", json={"board": STUCK_BOARD, "mode": "llm"})
    assert stuck_llm.status_code == 409
    assert stuck_llm.json()["detail"] == "no legal move"
    assert llm.calls == 0

    ok_llm = client.post("/suggest", json={"board": SORTED_ROW, "mode": "llm"})
    assert ok_llm.status_code == 200
    assert ok_llm.json()["source"] == "llm"
    assert llm.calls == 1
    limited_llm = client.post("/suggest", json={"board": SORTED_ROW, "mode": "llm"})
    assert limited_llm.status_code == 429
    assert limited_llm.headers.get(HEADER_SUGGEST_LIMIT.lower()) == LIMIT_REASON_SPEND

    stuck_ex = client.post("/suggest", json={"board": STUCK_BOARD, "mode": "expectimax"})
    assert stuck_ex.status_code == 409
    assert stuck_ex.json()["detail"] == "no legal move"

    ok_ex = client.post("/suggest", json={"board": SORTED_ROW, "mode": "expectimax"})
    assert ok_ex.status_code == 200
    assert ok_ex.json()["source"] == "expectimax"
    limited_ex = client.post("/suggest", json={"board": SORTED_ROW, "mode": "expectimax"})
    assert limited_ex.status_code == 429
    assert limited_ex.headers.get(HEADER_SUGGEST_LIMIT.lower()) == LIMIT_REASON_SPEND
    assert llm.calls == 1


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
    assert limited.json()["detail"] == DETAIL_SPEND_CAP
    assert limited.headers.get("retry-after") is not None
    assert limited.headers.get(HEADER_SUGGEST_LIMIT.lower()) == LIMIT_REASON_SPEND
    metrics = client.get("/metrics").text
    assert (
        labeled_counter(metrics, PROM_SUGGEST_LIMIT_REJECT, f'reason="{LIMIT_REASON_SPEND}"') == 1.0
    )
    assert (
        labeled_counter(metrics, PROM_SUGGEST_LIMIT_REJECT, f'reason="{LIMIT_REASON_CAPACITY}"')
        == 0.0
    )


def test_capacity_429_uses_model_busy_detail() -> None:
    """Capacity full is distinct from spend: detail + X-Suggest-Limit + short Retry-After."""
    llm = BlockingLLM()
    settings = isolated_settings(
        app_env="prod",
        suggest_rate_limit_requests=10,
        llm_max_in_flight=1,
    )
    app = create_app(settings, llm, llm_in_flight=InFlightGate(1))
    body = {"board": OPEN_BOARD, "mode": "llm"}
    holder_status: dict[str, int] = {}

    # One TestClient lifespan for holder + probe (nested clients shut down telemetry).
    with TestClient(app) as client:

        def hold() -> None:
            holder_status["code"] = client.post("/suggest", json=body).status_code

        holder = threading.Thread(target=hold)
        holder.start()
        assert llm.started.wait(2)

        blocked = client.post("/suggest", json=body)
        assert blocked.status_code == 429
        assert blocked.json()["detail"] == DETAIL_MODEL_BUSY
        assert blocked.headers["retry-after"] == "1"
        assert blocked.headers[HEADER_SUGGEST_LIMIT.lower()] == LIMIT_REASON_CAPACITY
        metrics = client.get("/metrics").text
        assert (
            labeled_counter(metrics, PROM_SUGGEST_LIMIT_REJECT, f'reason="{LIMIT_REASON_CAPACITY}"')
            == 1.0
        )
        assert (
            labeled_counter(metrics, PROM_SUGGEST_LIMIT_REJECT, f'reason="{LIMIT_REASON_SPEND}"')
            == 0.0
        )
        assert not getattr(app.state, "telemetry_shutdown", False)

        llm.release.set()
        holder.join(timeout=3)
        assert not holder.is_alive()
        assert holder_status == {"code": 200}


def test_expectimax_capacity_429_uses_model_busy_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expectimax capacity uses the same 429 contract as LLM (detail / header / Retry-After)."""
    search = BlockingExpectimax()
    monkeypatch.setattr("app.suggester.choose_move", search)
    settings = isolated_settings(
        app_env="prod",
        suggest_rate_limit_expectimax_requests=10,
        expectimax_max_in_flight=1,
    )
    app = create_app(
        settings,
        UnusedLLM(),
        expectimax_in_flight=InFlightGate(1),
    )
    body = {"board": OPEN_BOARD, "mode": "expectimax"}
    holder_status: dict[str, int] = {}

    with TestClient(app) as client:

        def hold() -> None:
            holder_status["code"] = client.post("/suggest", json=body).status_code

        holder = threading.Thread(target=hold)
        holder.start()
        assert search.started.wait(2)

        blocked = client.post("/suggest", json=body)
        assert blocked.status_code == 429
        assert blocked.json()["detail"] == DETAIL_MODEL_BUSY
        assert blocked.headers["retry-after"] == "1"
        assert blocked.headers[HEADER_SUGGEST_LIMIT.lower()] == LIMIT_REASON_CAPACITY
        metrics = client.get("/metrics").text
        assert (
            labeled_counter(metrics, PROM_SUGGEST_LIMIT_REJECT, f'reason="{LIMIT_REASON_CAPACITY}"')
            == 1.0
        )
        assert (
            labeled_counter(metrics, PROM_SUGGEST_LIMIT_REJECT, f'reason="{LIMIT_REASON_SPEND}"')
            == 0.0
        )
        assert not getattr(app.state, "telemetry_shutdown", False)

        search.release.set()
        holder.join(timeout=3)
        assert not holder.is_alive()
        assert holder_status == {"code": 200}


def test_capacity_and_spend_429_have_distinct_details() -> None:
    """One scenario surfaces both layers; clients must not treat every 429 alike."""
    clock = FrozenClock()
    limiter = SuggestRateLimiter(2, 60, clock)
    llm = BlockingLLM()
    app = create_app(
        isolated_settings(app_env="prod", suggest_rate_limit_requests=2, llm_max_in_flight=1),
        llm,
        rate_limiters={"llm": limiter, "expectimax": SuggestRateLimiter(30, 60, clock)},
        llm_in_flight=InFlightGate(1),
    )
    body = {"board": OPEN_BOARD, "mode": "llm"}
    holder_status: dict[str, int] = {}

    with TestClient(app) as client:

        def hold() -> None:
            holder_status["code"] = client.post("/suggest", json=body).status_code

        holder = threading.Thread(target=hold)
        holder.start()
        assert llm.started.wait(2)

        capacity = client.post("/suggest", json=body)
        assert capacity.status_code == 429
        assert capacity.json()["detail"] == DETAIL_MODEL_BUSY
        assert capacity.headers["retry-after"] == "1"
        assert capacity.headers[HEADER_SUGGEST_LIMIT.lower()] == LIMIT_REASON_CAPACITY
        assert not getattr(app.state, "telemetry_shutdown", False)

        llm.release.set()
        holder.join(timeout=3)
        assert not holder.is_alive()
        assert holder_status == {"code": 200}

        assert client.post("/suggest", json=body).status_code == 200
        spend = client.post("/suggest", json=body)
        assert spend.status_code == 429
        assert spend.json()["detail"] == DETAIL_SPEND_CAP
        assert spend.headers["retry-after"] == "60"
        assert spend.headers[HEADER_SUGGEST_LIMIT.lower()] == LIMIT_REASON_SPEND
        metrics = client.get("/metrics").text
        assert (
            labeled_counter(metrics, PROM_SUGGEST_LIMIT_REJECT, f'reason="{LIMIT_REASON_CAPACITY}"')
            == 1.0
        )
        assert (
            labeled_counter(metrics, PROM_SUGGEST_LIMIT_REJECT, f'reason="{LIMIT_REASON_SPEND}"')
            == 1.0
        )

    assert capacity.json()["detail"] != spend.json()["detail"]


def test_expectimax_capacity_and_spend_429_have_distinct_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expectimax also surfaces distinct capacity vs spend 429 details on one app."""
    clock = FrozenClock()
    limiter = SuggestRateLimiter(2, 60, clock)
    search = BlockingExpectimax()
    monkeypatch.setattr("app.suggester.choose_move", search)
    app = create_app(
        isolated_settings(
            app_env="prod",
            suggest_rate_limit_expectimax_requests=2,
            expectimax_max_in_flight=1,
        ),
        UnusedLLM(),
        rate_limiters={"llm": SuggestRateLimiter(30, 60, clock), "expectimax": limiter},
        expectimax_in_flight=InFlightGate(1),
    )
    body = {"board": OPEN_BOARD, "mode": "expectimax"}
    holder_status: dict[str, int] = {}

    with TestClient(app) as client:

        def hold() -> None:
            holder_status["code"] = client.post("/suggest", json=body).status_code

        holder = threading.Thread(target=hold)
        holder.start()
        assert search.started.wait(2)

        capacity = client.post("/suggest", json=body)
        assert capacity.status_code == 429
        assert capacity.json()["detail"] == DETAIL_MODEL_BUSY
        assert capacity.headers["retry-after"] == "1"
        assert capacity.headers[HEADER_SUGGEST_LIMIT.lower()] == LIMIT_REASON_CAPACITY
        assert not getattr(app.state, "telemetry_shutdown", False)

        search.release.set()
        holder.join(timeout=3)
        assert not holder.is_alive()
        assert holder_status == {"code": 200}

        assert client.post("/suggest", json=body).status_code == 200
        spend = client.post("/suggest", json=body)
        assert spend.status_code == 429
        assert spend.json()["detail"] == DETAIL_SPEND_CAP
        assert spend.headers["retry-after"] == "60"
        assert spend.headers[HEADER_SUGGEST_LIMIT.lower()] == LIMIT_REASON_SPEND
        metrics = client.get("/metrics").text
        assert (
            labeled_counter(metrics, PROM_SUGGEST_LIMIT_REJECT, f'reason="{LIMIT_REASON_CAPACITY}"')
            == 1.0
        )
        assert (
            labeled_counter(metrics, PROM_SUGGEST_LIMIT_REJECT, f'reason="{LIMIT_REASON_SPEND}"')
            == 1.0
        )

    assert capacity.json()["detail"] != spend.json()["detail"]


def test_hard_ceiling_429_uses_window_retry_after() -> None:
    llm = FakeLLM(["right", "right"])
    clock = FrozenClock()
    limiter = SuggestRateLimiter(1, 60, clock)
    client = TestClient(
        create_app(
            isolated_settings(),
            llm,
            rate_limiters={"llm": limiter, "expectimax": SuggestRateLimiter(30, 60, clock)},
        )
    )
    assert client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"}).status_code == 200
    blocked = client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"})
    assert blocked.status_code == 429
    assert blocked.json()["detail"] == DETAIL_SPEND_CAP
    assert blocked.headers["retry-after"] == "60"
    assert blocked.headers[HEADER_SUGGEST_LIMIT.lower()] == LIMIT_REASON_SPEND


def test_hard_ceiling_retry_after_can_collapse_to_one() -> None:
    """Near window end, spend Retry-After is also 1 — distinct detail still tells layers apart."""
    llm = FakeLLM(["right", "right"])
    clock = FrozenClock()
    limiter = SuggestRateLimiter(1, 60, clock)
    client = TestClient(
        create_app(
            isolated_settings(),
            llm,
            rate_limiters={"llm": limiter, "expectimax": SuggestRateLimiter(30, 60, clock)},
        )
    )
    assert client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"}).status_code == 200
    clock.now = 59.5  # remaining 0.5s → ceil → 1
    blocked = client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"})
    assert blocked.status_code == 429
    assert blocked.json()["detail"] == DETAIL_SPEND_CAP
    assert blocked.headers["retry-after"] == "1"
    assert blocked.headers[HEADER_SUGGEST_LIMIT.lower()] == LIMIT_REASON_SPEND


def test_expectimax_returns_a_legal_search_move() -> None:
    client = TestClient(create_app(isolated_settings(app_env="prod"), UnusedLLM()))
    response = client.post("/suggest", json={"board": SORTED_ROW, "mode": "expectimax"})
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "expectimax"
    assert body["source"] == "expectimax"
    assert body["move"] == "right"
    assert body["move"] in legal_moves(SORTED_ROW)
    assert body["reason"].startswith("Expected score vs Right: ")
    assert "Left not possible" in body["reason"]


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
    response = client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"})
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "llm"
    assert body["source"] == "fallback"
    assert body["reason"] is None
    assert body["move"] in legal_moves(OPEN_BOARD)


def test_client_events_beacons_and_metrics() -> None:
    client = TestClient(create_app(isolated_settings(app_env="prod"), UnusedLLM()))
    assert client.post("/client-events", json={"outcome": "fail"}).status_code == 204
    assert client.post("/client-events", json={"outcome": "rate_limit"}).status_code == 204
    assert client.post("/client-events", json={"outcome": "model_busy"}).status_code == 204
    assert client.post("/client-events", json={"outcome": "cancel"}).status_code == 204
    assert client.post("/client-events", json={}).status_code == 422
    assert client.post("/client-events", json={"outcome": "success"}).status_code == 422

    text = client.get("/metrics").text
    assert labeled_counter(text, PROM_CLIENT_SUGGEST_OUTCOME, 'outcome="fail"') == 1.0
    assert labeled_counter(text, PROM_CLIENT_SUGGEST_OUTCOME, 'outcome="rate_limit"') == 1.0
    assert labeled_counter(text, PROM_CLIENT_SUGGEST_OUTCOME, 'outcome="model_busy"') == 1.0
    assert labeled_counter(text, PROM_CLIENT_SUGGEST_OUTCOME, 'outcome="cancel"') == 1.0
    assert labeled_counter(text, PROM_CLIENT_SUGGEST_OUTCOME, 'outcome="success"') == 0.0


def test_client_events_rate_limit_is_429_and_skips_counter() -> None:
    limiter = SuggestRateLimiter(1, 60)
    client = TestClient(
        create_app(
            isolated_settings(app_env="prod"),
            UnusedLLM(),
            client_events_rate_limiter=limiter,
        )
    )
    assert client.post("/client-events", json={"outcome": "fail"}).status_code == 204
    limited = client.post("/client-events", json={"outcome": "fail"})
    assert limited.status_code == 429
    assert limited.json()["detail"] == "too many client events"
    assert limited.headers.get("retry-after") is not None

    text = client.get("/metrics").text
    assert labeled_counter(text, PROM_CLIENT_SUGGEST_OUTCOME, 'outcome="fail"') == 1.0


def test_client_events_bad_payload_is_422_and_skips_rate_limit() -> None:
    client = TestClient(
        create_app(
            isolated_settings(
                app_env="prod",
                client_events_rate_limit_requests=1,
                client_events_rate_limit_window_seconds=60,
            ),
            UnusedLLM(),
        )
    )
    assert client.post("/client-events", json={"outcome": "success"}).status_code == 422
    assert client.post("/client-events", json={}).status_code == 422
    # Validation must not consume the beacon integrity cap.
    assert client.post("/client-events", json={"outcome": "fail"}).status_code == 204


def test_client_events_and_suggest_rate_limits_are_independent() -> None:
    settings = isolated_settings(
        app_env="prod",
        ollama_base_url="http://127.0.0.1:1",
        ollama_model="missing-model",
        llm_max_attempts=1,
        llm_attempt_timeout_seconds=1,
        llm_suggest_budget_seconds=2,
        suggest_rate_limit_requests=1,
        suggest_rate_limit_window_seconds=60,
        client_events_rate_limit_requests=1,
        client_events_rate_limit_window_seconds=60,
    )
    client = TestClient(create_app(settings))

    # Exhaust the beacon bucket; /suggest must still admit.
    assert client.post("/client-events", json={"outcome": "cancel"}).status_code == 204
    assert client.post("/client-events", json={"outcome": "cancel"}).status_code == 429
    suggest = client.post("/suggest", json={"board": SORTED_ROW, "mode": "llm"})
    assert suggest.status_code == 200
    assert suggest.json()["source"] == "fallback"

    # Exhaust the LLM suggest bucket; beacons must still admit on a fresh limiter app.
    client2 = TestClient(
        create_app(
            isolated_settings(
                app_env="prod",
                ollama_base_url="http://127.0.0.1:1",
                ollama_model="missing-model",
                llm_max_attempts=1,
                llm_attempt_timeout_seconds=1,
                llm_suggest_budget_seconds=2,
                suggest_rate_limit_requests=1,
                client_events_rate_limit_requests=2,
            )
        )
    )
    assert client2.post("/suggest", json={"board": SORTED_ROW, "mode": "llm"}).status_code == 200
    assert client2.post("/suggest", json={"board": SORTED_ROW, "mode": "llm"}).status_code == 429
    assert client2.post("/client-events", json={"outcome": "rate_limit"}).status_code == 204
