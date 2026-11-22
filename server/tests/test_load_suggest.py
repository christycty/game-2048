"""Opt-in load / soak for LLM /suggest (fake LLM only — not required PR CI).

Run: ``pytest --load`` (or ``pytest --load -m load``).

Pass criteria: every worker finishes; accounting closes
(``completes + capacity_429 + cancels == starts``); after drain a fresh acquire
succeeds (no leaked in-flight slots). Exercises ``LLM_MAX_IN_FLIGHT`` 1 then 2
with **sustained** capacity hold, mixed 429 layers on one app, and cancel-under-
capacity with a mid-hold capacity probe.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.rate_limit import LlmInFlightGate, SuggestRateLimiter
from helpers import OPEN_BOARD, BlockingLLM, FrozenClock, asgi_suggest, isolated_settings

pytestmark = pytest.mark.load

_WORKERS = 6
_PROBES_PER_WORKER = 8
_COMPLETES_PER_WORKER = 4
_BODY = {"board": OPEN_BOARD, "mode": "llm"}
_CANCEL_WAVES = 6
_WINDOW_SECONDS = 60


def _run_load(*, max_in_flight: int) -> None:
    """Hold every slot through a concurrent probe wave, then drain and complete."""
    probe_total = _WORKERS * _PROBES_PER_WORKER
    complete_total = _WORKERS * _COMPLETES_PER_WORKER
    # Holders + completes must stay under Settings max so 429s stay capacity.
    assert max_in_flight + complete_total <= 120
    llm = BlockingLLM()
    gate = LlmInFlightGate(max_in_flight)
    settings = isolated_settings(
        suggest_rate_limit_requests=120,
        llm_max_in_flight=max_in_flight,
    )
    app = create_app(settings, llm, llm_in_flight=gate)
    counts = {"starts": 0, "completes": 0, "capacity_429": 0, "cancels": 0, "other": 0}
    lock = threading.Lock()
    holder_codes: list[int] = []

    def record(status: int) -> None:
        with lock:
            counts["starts"] += 1
            if status == 200:
                counts["completes"] += 1
            elif status == 429:
                counts["capacity_429"] += 1
            elif status == 499:
                counts["cancels"] += 1
            else:
                counts["other"] += 1

    # One TestClient lifespan for the whole soak (nested clients shut down telemetry).
    with TestClient(app) as client:
        llm.release.clear()

        def hold() -> None:
            code = client.post("/suggest", json=_BODY).status_code
            with lock:
                holder_codes.append(code)

        holders = [threading.Thread(target=hold) for _ in range(max_in_flight)]
        for thread in holders:
            thread.start()
        deadline = time.monotonic() + 2
        while llm.calls < max_in_flight and time.monotonic() < deadline:
            time.sleep(0.01)
        assert llm.calls == max_in_flight

        def probe_worker(n: int) -> None:
            for _ in range(n):
                blocked = client.post("/suggest", json=_BODY)
                assert blocked.status_code == 429
                assert blocked.headers.get("retry-after") == "1"
                record(429)

        with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
            futures = [pool.submit(probe_worker, _PROBES_PER_WORKER) for _ in range(_WORKERS)]
            for future in as_completed(futures):
                future.result(timeout=60)

        assert counts["capacity_429"] == probe_total, counts
        # Still full after the wave (holders never released).
        still = client.post("/suggest", json=_BODY)
        assert still.status_code == 429
        assert still.headers.get("retry-after") == "1"
        record(429)
        assert not getattr(app.state, "telemetry_shutdown", False)

        llm.release.set()
        for thread in holders:
            thread.join(timeout=3)
            assert not thread.is_alive()
        assert holder_codes == [200] * max_in_flight
        for code in holder_codes:
            record(code)

        # --- Completes after drain (release stays set). Parallel workers may still
        # hit capacity 429 briefly while a sibling holds the slot — that is real
        # contention, not a failure; classify and account.
        def complete_worker(n: int) -> None:
            for _ in range(n):
                response = client.post("/suggest", json=_BODY)
                if response.status_code == 429:
                    assert response.headers.get("retry-after") == "1"
                else:
                    assert response.status_code == 200
                record(response.status_code)

        with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
            futures = [pool.submit(complete_worker, _COMPLETES_PER_WORKER) for _ in range(_WORKERS)]
            for future in as_completed(futures):
                future.result(timeout=60)

        assert counts["other"] == 0, counts
        expected_starts = probe_total + 1 + max_in_flight + complete_total
        assert counts["starts"] == expected_starts, counts
        accounted = counts["completes"] + counts["capacity_429"] + counts["cancels"]
        assert accounted == counts["starts"], counts
        assert counts["completes"] >= max_in_flight + 1, counts
        assert counts["capacity_429"] >= probe_total + 1, counts
        assert not getattr(app.state, "telemetry_shutdown", False)

        probe = gate.acquire()
        assert probe.retry_after is None and probe.token is not None
        gate.release(probe.token)
        assert client.post("/suggest", json=_BODY).status_code == 200


@pytest.mark.parametrize("max_in_flight", [1, 2])
def test_load_suggest_accounts_and_drains(max_in_flight: int) -> None:
    _run_load(max_in_flight=max_in_flight)


def test_load_mixed_429_layers_classified_by_retry_after() -> None:
    """One app: capacity 429 while held, then hard-ceiling 429 after drain.

    Details / X-Suggest-Limit distinguish layers; frozen clock keeps spend
    Retry-After at the full window (60) so Retry-After still differs in this soak.
    """
    hard_ceiling = 4
    clock = FrozenClock()
    llm = BlockingLLM()
    gate = LlmInFlightGate(1)
    limiter = SuggestRateLimiter(hard_ceiling, _WINDOW_SECONDS, clock)
    app = create_app(
        isolated_settings(
            suggest_rate_limit_requests=hard_ceiling,
            llm_max_in_flight=1,
        ),
        llm,
        rate_limiters={
            "llm": limiter,
            "expectimax": SuggestRateLimiter(30, _WINDOW_SECONDS, clock),
        },
        llm_in_flight=gate,
    )
    counts = {
        "starts": 0,
        "completes": 0,
        "capacity_429": 0,
        "hard_ceiling_429": 0,
        "other": 0,
    }
    lock = threading.Lock()

    def record(status: int, *, retry: str | None = None) -> None:
        with lock:
            counts["starts"] += 1
            if status == 200:
                counts["completes"] += 1
            elif status == 429 and retry == "1":
                counts["capacity_429"] += 1
            elif status == 429 and retry == str(_WINDOW_SECONDS):
                counts["hard_ceiling_429"] += 1
            else:
                counts["other"] += 1

    with TestClient(app) as client:
        llm.release.clear()

        def hold() -> None:
            record(client.post("/suggest", json=_BODY).status_code)

        holder = threading.Thread(target=hold)
        holder.start()
        assert llm.started.wait(2)

        def capacity_worker(n: int) -> None:
            for _ in range(n):
                blocked = client.post("/suggest", json=_BODY)
                assert blocked.status_code == 429
                retry = blocked.headers.get("retry-after")
                assert retry == "1"
                record(429, retry=retry)

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(capacity_worker, 5) for _ in range(4)]
            for future in as_completed(futures):
                future.result(timeout=60)

        assert not getattr(app.state, "telemetry_shutdown", False)
        llm.release.set()
        holder.join(timeout=3)
        assert not holder.is_alive()

        # Holder burned 1 hard-ceiling hit. Fill the rest, then assert window Retry-After.
        remaining_ok = hard_ceiling - 1
        for _ in range(remaining_ok):
            assert client.post("/suggest", json=_BODY).status_code == 200
            record(200)
        spend = client.post("/suggest", json=_BODY)
        assert spend.status_code == 429
        retry = spend.headers.get("retry-after")
        assert retry == str(_WINDOW_SECONDS)
        record(429, retry=retry)

    assert counts["other"] == 0, counts
    assert counts["capacity_429"] >= 1, counts
    assert counts["hard_ceiling_429"] >= 1, counts
    assert counts["completes"] == hard_ceiling, counts
    accounted = counts["completes"] + counts["capacity_429"] + counts["hard_ceiling_429"]
    assert accounted == counts["starts"], counts

    spend_probe = gate.acquire()
    assert spend_probe.retry_after is None and spend_probe.token is not None
    gate.release(spend_probe.token)


def test_load_cancel_under_capacity_accounts_and_drains() -> None:
    """ASGI disconnect under capacity: mid-hold capacity 429; cancels + completes account."""
    llm = BlockingLLM()
    gate = LlmInFlightGate(2)
    settings = isolated_settings(
        suggest_rate_limit_requests=120,
        llm_max_in_flight=2,
    )
    app = create_app(settings, llm, llm_in_flight=gate)
    raw_body = json.dumps(_BODY).encode()
    counts = {"starts": 0, "completes": 0, "capacity_429": 0, "cancels": 0, "other": 0}

    def record(status: int | None) -> None:
        counts["starts"] += 1
        if status == 200:
            counts["completes"] += 1
        elif status == 429:
            counts["capacity_429"] += 1
        elif status == 499:
            counts["cancels"] += 1
        else:
            counts["other"] += 1

    async def run() -> None:
        for _ in range(_CANCEL_WAVES):
            llm.release.clear()
            baseline = llm.calls
            disconnect = asyncio.Event()
            task_a = asyncio.create_task(asgi_suggest(app, raw_body, disconnect_gate=disconnect))
            task_b = asyncio.create_task(asgi_suggest(app, raw_body, disconnect_gate=None))
            deadline = time.monotonic() + 2
            while llm.calls < baseline + 2 and time.monotonic() < deadline:
                await asyncio.sleep(0.01)
            assert llm.calls >= baseline + 2

            # Both slots held: oversubscribe before cancelling A.
            # Raw ASGI — TestClient lifespan would shutdown_telemetry mid-flight.
            blocked = await asgi_suggest(app, raw_body, disconnect_gate=None)
            assert blocked.status == 429
            assert blocked.headers.get("retry-after") == "1"
            record(429)
            assert not getattr(app.state, "telemetry_shutdown", False)

            disconnect.set()
            result_a = await asyncio.wait_for(task_a, timeout=5)
            assert result_a.status == 499
            llm.release.set()
            result_b = await asyncio.wait_for(task_b, timeout=5)
            assert result_b.status == 200
            record(result_a.status)
            record(result_b.status)

        assert counts["cancels"] == _CANCEL_WAVES, counts
        assert counts["completes"] == _CANCEL_WAVES, counts
        assert counts["capacity_429"] == _CANCEL_WAVES, counts
        assert counts["other"] == 0, counts
        accounted = counts["completes"] + counts["capacity_429"] + counts["cancels"]
        assert accounted == counts["starts"], counts
        assert not getattr(app.state, "telemetry_shutdown", False)

        probe = gate.acquire()
        assert probe.retry_after is None and probe.token is not None
        gate.release(probe.token)
        with TestClient(app) as client:
            assert client.post("/suggest", json=_BODY).status_code == 200

    asyncio.run(run())
