"""Stable /suggest HTTP contract for gates and cancel (fake LLM only).

Until multi-client splits capacity vs spend ``detail``, clients distinguish layers
by ``Retry-After``: capacity is short (1); hard-ceiling is the remaining window
(typically larger, default 60 when the window just filled).
"""

from __future__ import annotations

import threading

from fastapi.testclient import TestClient

from app.main import create_app
from app.rate_limit import LlmInFlightGate, SuggestRateLimiter
from helpers import OPEN_BOARD, BlockingLLM, FakeLLM, isolated_settings


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_hard_ceiling_429_uses_window_retry_after() -> None:
    llm = FakeLLM(["right", "right"])
    clock = _Clock()
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
    assert blocked.json()["detail"] == "too many suggestions"
    assert blocked.headers["retry-after"] == "60"


def test_capacity_429_uses_short_retry_after() -> None:
    """Capacity full today shares detail with hard ceiling; Retry-After is the tell."""
    llm = BlockingLLM()
    settings = isolated_settings(suggest_rate_limit_requests=10, llm_max_in_flight=1)
    app = create_app(settings, llm, llm_in_flight=LlmInFlightGate(1))
    body = {"board": OPEN_BOARD, "mode": "llm"}

    def hold() -> None:
        with TestClient(app) as client:
            client.post("/suggest", json=body)

    holder = threading.Thread(target=hold)
    holder.start()
    assert llm.started.wait(2)

    with TestClient(app) as client:
        blocked = client.post("/suggest", json=body)
        assert blocked.status_code == 429
        assert blocked.json()["detail"] == "too many suggestions"
        assert blocked.headers["retry-after"] == "1"

    llm.release.set()
    holder.join(timeout=3)


def test_capacity_and_hard_ceiling_429_classified_by_retry_after() -> None:
    """One scenario surfaces both 429 layers; same detail, Retry-After distinguishes them."""
    clock = _Clock()
    limiter = SuggestRateLimiter(2, 60, clock)
    llm = BlockingLLM()
    app = create_app(
        isolated_settings(suggest_rate_limit_requests=2, llm_max_in_flight=1),
        llm,
        rate_limiters={"llm": limiter, "expectimax": SuggestRateLimiter(30, 60, clock)},
        llm_in_flight=LlmInFlightGate(1),
    )
    body = {"board": OPEN_BOARD, "mode": "llm"}

    def hold() -> None:
        with TestClient(app) as client:
            client.post("/suggest", json=body)

    holder = threading.Thread(target=hold)
    holder.start()
    assert llm.started.wait(2)

    with TestClient(app) as client:
        capacity = client.post("/suggest", json=body)
        assert capacity.status_code == 429
        assert capacity.json()["detail"] == "too many suggestions"
        assert capacity.headers["retry-after"] == "1"

    llm.release.set()
    holder.join(timeout=3)

    with TestClient(app) as client:
        # Holder used 1 hard-ceiling hit; one more success fills the window of 2.
        assert client.post("/suggest", json=body).status_code == 200
        spend = client.post("/suggest", json=body)
        assert spend.status_code == 429
        assert spend.json()["detail"] == "too many suggestions"
        assert spend.headers["retry-after"] == "60"

    # Clients must not treat every 429 alike before multi-client splits detail.
    assert capacity.headers["retry-after"] != spend.headers["retry-after"]


def test_cancel_maps_to_499_detail() -> None:
    class InstantCancel:
        def suggest_move(self, *args: object, **kwargs: object):
            from app.cancel import SuggestCancelled

            raise SuggestCancelled()

    client = TestClient(create_app(isolated_settings(), InstantCancel()))
    response = client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"})
    assert response.status_code == 499
    assert response.json()["detail"] == "client cancelled"
