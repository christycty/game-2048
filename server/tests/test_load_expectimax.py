"""Opt-in Expectimax Auto Play cadence soak (not required PR CI).

Design load: **4 concurrent Auto Play tabs**. Client cycle is read from
``client/src/game/game.js`` (``SETTLE_MS`` + ``AUTO_PLAY_GAP_MS``, ~910ms). That
cadence is an **upper bound** if search were free (~65 suggests/min/tab);
real Auto Play is slower because suggest latency is extra. Default spend
cap ``360`` ≈ ``4 × 65 × 1.4`` uses the upper bound so demos do not false-trip.

Run: ``pytest --load -m load`` (or this file alone under ``--load``).

Pass criteria:
- At the default cap, four cadence workers run for **one full rate-limit
  window** with **no** spend ``429``, and ``ok`` clears the interim
  single-tab-ish bar of 120 (``main`` was 30; an early branch draft used
  120 — this soak must fail under either).
- Soft throughput floor: ≥50% of ideal settle+gap volume (search + CI
  contention headroom).
- With an undersized cap, the same harness **does** trip spend ``429``
  (proves the soak is sensitive, not a no-op).
"""

from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

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

_CLIENT_GAME_JS = Path(__file__).resolve().parents[2] / "client" / "src" / "game" / "game.js"
_DEMO_CLIENTS = 4
# Match Settings / Compose window so the positive soak fills one sliding window.
_WINDOW_SECONDS = 60
_SOAK_SECONDS = _WINDOW_SECONDS
# Undersized trip does not need a full window once spend 429s appear.
_TRIP_SOAK_SECONDS = 20
_BODY = {"board": OPEN_BOARD, "mode": "expectimax"}
# Interim single-tab-ish ceiling on an early draft of this branch (main was 30).
# Design load must clear this volume so a 120 default would fail the soak.
_PRIOR_EXPECTIMAX_CAP = 120
# Soft floor vs ideal settle+gap volume (search time + CI contention).
_THROUGHPUT_FRACTION = 0.5


def _autoplay_cycle_seconds() -> float:
    """Settle + Auto Play gap from the client source of truth."""
    text = _CLIENT_GAME_JS.read_text(encoding="utf-8")
    slide = int(re.search(r"^export const SLIDE_MS = (\d+);", text, re.M).group(1))
    gap = int(re.search(r"^export const AUTO_PLAY_GAP_MS = (\d+);", text, re.M).group(1))
    # game.js: export const SETTLE_MS = SLIDE_MS + 20;
    assert re.search(r"^export const SETTLE_MS = SLIDE_MS \+ 20;", text, re.M), (
        "SETTLE_MS formula drifted; update this parser"
    )
    settle_ms = slide + 20
    return (settle_ms + gap) / 1000.0


def _default_expectimax_cap() -> int:
    default = Settings.model_fields["suggest_rate_limit_expectimax_requests"].default
    assert isinstance(default, int)
    return default


def _run_cadence(*, expectimax_cap: int, soak_seconds: float) -> tuple[dict[str, int], FakeLLM]:
    """Four workers: suggest → sleep(cycle) until soak ends; account statuses."""
    cycle_s = _autoplay_cycle_seconds()
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
                time.sleep(cycle_s)

        with ThreadPoolExecutor(max_workers=_DEMO_CLIENTS) as pool:
            futures = [pool.submit(worker) for _ in range(_DEMO_CLIENTS)]
            for future in as_completed(futures):
                future.result(timeout=soak_seconds + 60)

    return counts, llm


def test_load_expectimax_default_cap_covers_four_autoplay_tabs() -> None:
    """Design load: 4 cadence clients stay under the default expectimax spend cap."""
    cap = _default_expectimax_cap()
    assert cap == 360
    cycle_s = _autoplay_cycle_seconds()
    assert cycle_s == pytest.approx(0.91, abs=0.001)
    # Ideal if search were free; soft floor leaves headroom for expectimax + CI.
    ideal = _DEMO_CLIENTS * (_SOAK_SECONDS / cycle_s)
    min_expected = int(ideal * _THROUGHPUT_FRACTION)
    # Must exceed the interim 120 bar so this soak would fail under that default.
    assert min_expected > _PRIOR_EXPECTIMAX_CAP, (min_expected, ideal)

    counts, llm = _run_cadence(expectimax_cap=cap, soak_seconds=_SOAK_SECONDS)
    assert llm.calls == 0
    assert counts["other"] == 0, counts
    # Primary: no spend 429 at design load; clear the 120 bar.
    assert counts["spend_429"] == 0, counts
    assert counts["ok"] > _PRIOR_EXPECTIMAX_CAP, counts
    assert counts["ok"] == counts["starts"], counts
    # Soft throughput floor (not the primary gate).
    assert counts["ok"] >= min_expected, counts


def test_load_expectimax_undersized_cap_trips_under_four_tabs() -> None:
    """Same harness with a tiny cap must produce spend 429 (soak is not a no-op)."""
    # ~4 × 65/min burns this well before a short soak ends.
    undersized = 40
    counts, llm = _run_cadence(expectimax_cap=undersized, soak_seconds=_TRIP_SOAK_SECONDS)
    assert llm.calls == 0
    assert counts["other"] == 0, counts
    assert counts["spend_429"] >= 1, counts
    assert counts["ok"] + counts["spend_429"] == counts["starts"], counts
    assert counts["ok"] <= undersized, counts
