"""Opt-in Expectimax Auto Play cadence soak (not required PR CI).

Design load: **4 concurrent Auto Play tabs**. Client cycle mirrors
``SETTLE_MS`` + ``AUTO_PLAY_GAP_MS`` in ``client/src/game.js`` (~910ms →
~65 suggests/min/tab). Default spend cap ``360`` ≈ ``4 × 65 × 1.4``.

Run: ``pytest --load -m load`` (or this file alone under ``--load``).

Pass criteria:
- At the default cap, four cadence workers finish a short soak with **no**
  spend ``429``.
- With an undersized cap, the same harness **does** trip spend ``429``
  (proves the soak is sensitive, not a no-op).
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.rate_limit import (
    DETAIL_SPEND_CAP,
    HEADER_SUGGEST_LIMIT,
    LIMIT_REASON_SPEND,
    SuggestRateLimiter,
)
from helpers import OPEN_BOARD, FakeLLM, isolated_settings

pytestmark = pytest.mark.load

# Keep in sync with client/src/game.js when Auto Play timing changes.
_SETTLE_MS = 160
_AUTO_PLAY_GAP_MS = 750
_CYCLE_S = (_SETTLE_MS + _AUTO_PLAY_GAP_MS) / 1000.0
_DEMO_CLIENTS = 4
_SOAK_SECONDS = 25
_BODY = {"board": OPEN_BOARD, "mode": "expectimax"}
_WINDOW_SECONDS = 60


def _default_expectimax_cap() -> int:
    default = Settings.model_fields["suggest_rate_limit_expectimax_requests"].default
    assert isinstance(default, int)
    return default


def _run_cadence(*, expectimax_cap: int, soak_seconds: float) -> tuple[dict[str, int], FakeLLM]:
    """Four workers: suggest → sleep(cycle) until soak ends; account statuses."""
    llm = FakeLLM(["right"] * 8)
    settings = isolated_settings(
        suggest_rate_limit_expectimax_requests=expectimax_cap,
        suggest_rate_limit_window_seconds=_WINDOW_SECONDS,
    )
    app = create_app(
        settings,
        llm,
        rate_limiters={
            "llm": SuggestRateLimiter(settings.suggest_rate_limit_requests, _WINDOW_SECONDS),
            "expectimax": SuggestRateLimiter(expectimax_cap, _WINDOW_SECONDS),
        },
    )
    counts = {"starts": 0, "ok": 0, "spend_429": 0, "other": 0}
    lock = threading.Lock()
    stop_at = time.monotonic() + soak_seconds

    def record(status: int, *, detail: object | None = None, limit: str | None = None) -> None:
        with lock:
            counts["starts"] += 1
            if status == 200:
                counts["ok"] += 1
            elif status == 429 and detail == DETAIL_SPEND_CAP and limit == LIMIT_REASON_SPEND:
                counts["spend_429"] += 1
            else:
                counts["other"] += 1

    # One TestClient lifespan for the whole soak (nested clients shut down telemetry).
    with TestClient(app) as client:

        def worker() -> None:
            while time.monotonic() < stop_at:
                response = client.post("/suggest", json=_BODY)
                detail = None
                if response.status_code == 429:
                    try:
                        detail = response.json().get("detail")
                    except Exception:
                        detail = None
                record(
                    response.status_code,
                    detail=detail,
                    limit=response.headers.get(HEADER_SUGGEST_LIMIT.lower()),
                )
                # Match Auto Play watchability pause after settle (search time is extra).
                time.sleep(_CYCLE_S)

        with ThreadPoolExecutor(max_workers=_DEMO_CLIENTS) as pool:
            futures = [pool.submit(worker) for _ in range(_DEMO_CLIENTS)]
            for future in as_completed(futures):
                future.result(timeout=soak_seconds + 30)

    return counts, llm


def test_load_expectimax_default_cap_covers_four_autoplay_tabs() -> None:
    """Design load: 4 cadence clients stay under the default expectimax spend cap."""
    cap = _default_expectimax_cap()
    assert cap == 360
    # Floor: 4 tabs × soak/cycle must be able to exceed the old 30/min default.
    min_expected = int(_DEMO_CLIENTS * (_SOAK_SECONDS / _CYCLE_S) * 0.5)
    assert min_expected > 30

    counts, llm = _run_cadence(expectimax_cap=cap, soak_seconds=_SOAK_SECONDS)
    assert llm.calls == 0
    assert counts["other"] == 0, counts
    assert counts["spend_429"] == 0, counts
    assert counts["ok"] >= min_expected, counts
    assert counts["ok"] == counts["starts"], counts


def test_load_expectimax_undersized_cap_trips_under_four_tabs() -> None:
    """Same harness with a tiny cap must produce spend 429 (soak is not a no-op)."""
    # ~4 × 65/min would burn this in well under the soak window.
    undersized = 40
    counts, llm = _run_cadence(expectimax_cap=undersized, soak_seconds=_SOAK_SECONDS)
    assert llm.calls == 0
    assert counts["other"] == 0, counts
    assert counts["spend_429"] >= 1, counts
    assert counts["ok"] + counts["spend_429"] == counts["starts"], counts
    assert counts["ok"] <= undersized, counts
