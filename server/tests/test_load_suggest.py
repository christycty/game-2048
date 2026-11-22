"""Opt-in load / soak for LLM /suggest (fake LLM only — not required PR CI).

Run: ``pytest --load`` (or ``pytest --load -m load``).

Pass criteria: every worker finishes; accounting closes
(``completes + capacity_429 + cancels == starts``); after drain a fresh acquire
succeeds (no leaked in-flight slots). Exercises ``LLM_MAX_IN_FLIGHT`` 1 then 2,
including a cancel-under-capacity soak.
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
from helpers import OPEN_BOARD, BlockingLLM, FakeLLM, isolated_settings

pytestmark = pytest.mark.load

_WORKERS = 6
_PER_WORKER = 10
_BODY = {"board": OPEN_BOARD, "mode": "llm"}
_CANCEL_WAVES = 6
_WINDOW_SECONDS = 60


class _Clock:
    """Frozen clock so hard-ceiling Retry-After stays ``window`` (never collapses to 1)."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _run_load(*, max_in_flight: int) -> None:
    """Soak with forced capacity contention, then fast completes (no timing races)."""
    total = _WORKERS * _PER_WORKER
    # Stay under Settings max (120) so 429s are capacity, not hard ceiling.
    assert total <= 120
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

    # --- Guaranteed capacity: hold every slot, then probe ---
    llm.release.clear()

    def hold() -> None:
        with TestClient(app) as client:
            holder_codes.append(client.post("/suggest", json=_BODY).status_code)

    holders = [threading.Thread(target=hold) for _ in range(max_in_flight)]
    for thread in holders:
        thread.start()
    deadline = time.monotonic() + 2
    while llm.calls < max_in_flight and time.monotonic() < deadline:
        time.sleep(0.01)
    assert llm.calls == max_in_flight

    capacity_probes = max(1, _WORKERS - max_in_flight)
    with TestClient(app) as client:
        for _ in range(capacity_probes):
            blocked = client.post("/suggest", json=_BODY)
            assert blocked.status_code == 429
            assert blocked.headers.get("retry-after") == "1"
            record(429)

    llm.release.set()
    for thread in holders:
        thread.join(timeout=3)
        assert not thread.is_alive()
    assert holder_codes == [200] * max_in_flight
    for code in holder_codes:
        record(code)

    # --- Remaining soak: release is set, so BlockingLLM returns immediately ---
    remaining = total - counts["starts"]
    assert remaining >= 0

    def worker(n: int) -> None:
        with TestClient(app) as client:
            for _ in range(n):
                response = client.post("/suggest", json=_BODY)
                if response.status_code == 429:
                    assert response.headers.get("retry-after") == "1"
                record(response.status_code)

    # Split remaining across workers (some may get 0).
    per = [remaining // _WORKERS] * _WORKERS
    for i in range(remaining % _WORKERS):
        per[i] += 1
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = [pool.submit(worker, n) for n in per if n > 0]
        for future in as_completed(futures):
            future.result(timeout=60)

    assert counts["other"] == 0, counts
    assert counts["starts"] == total, counts
    accounted = counts["completes"] + counts["capacity_429"] + counts["cancels"]
    assert accounted == counts["starts"], counts
    assert counts["completes"] >= 1, counts
    assert counts["capacity_429"] >= capacity_probes, counts

    probe = gate.acquire()
    assert probe.retry_after is None and probe.token is not None
    gate.release(probe.token)
    with TestClient(app) as client:
        assert client.post("/suggest", json=_BODY).status_code == 200


@pytest.mark.parametrize("max_in_flight", [1, 2])
def test_load_suggest_accounts_and_drains(max_in_flight: int) -> None:
    _run_load(max_in_flight=max_in_flight)


def test_load_mixed_429_layers_classified_by_retry_after() -> None:
    """Both 429 layers under load pressure; classify by Retry-After without ambiguity.

    Frozen clock keeps hard-ceiling Retry-After at the full window (60). Without that,
    ``SuggestRateLimiter`` can return ``1`` near window end — the same value as capacity.
    Capacity is forced with BlockingLLM holders (no delay races).
    """
    hard_ceiling = 3
    clock = _Clock()
    counts = {
        "starts": 0,
        "completes": 0,
        "capacity_429": 0,
        "hard_ceiling_429": 0,
        "other": 0,
    }

    def record(status: int, *, retry: str | None = None) -> None:
        counts["starts"] += 1
        if status == 200:
            counts["completes"] += 1
        elif status == 429 and retry == "1":
            counts["capacity_429"] += 1
        elif status == 429 and retry == str(_WINDOW_SECONDS):
            counts["hard_ceiling_429"] += 1
        else:
            counts["other"] += 1

    # --- Capacity layer (BlockingLLM hold) ---
    blocking = BlockingLLM()
    gate = LlmInFlightGate(1)
    capacity_app = create_app(
        isolated_settings(suggest_rate_limit_requests=120, llm_max_in_flight=1),
        blocking,
        llm_in_flight=gate,
    )

    def hold() -> None:
        with TestClient(capacity_app) as client:
            record(client.post("/suggest", json=_BODY).status_code)

    holder = threading.Thread(target=hold)
    holder.start()
    assert blocking.started.wait(2)
    with TestClient(capacity_app) as client:
        for _ in range(8):
            blocked = client.post("/suggest", json=_BODY)
            assert blocked.status_code == 429
            retry = blocked.headers.get("retry-after")
            assert retry == "1"
            record(429, retry=retry)
    blocking.release.set()
    holder.join(timeout=3)
    assert not holder.is_alive()

    probe = gate.acquire()
    assert probe.retry_after is None and probe.token is not None
    gate.release(probe.token)

    # --- Hard-ceiling layer (frozen clock ⇒ Retry-After always window) ---
    llm = FakeLLM(forever_move="right")
    spend_gate = LlmInFlightGate(4)
    limiter = SuggestRateLimiter(hard_ceiling, _WINDOW_SECONDS, clock)
    spend_app = create_app(
        isolated_settings(
            suggest_rate_limit_requests=hard_ceiling,
            llm_max_in_flight=4,
        ),
        llm,
        rate_limiters={
            "llm": limiter,
            "expectimax": SuggestRateLimiter(30, _WINDOW_SECONDS, clock),
        },
        llm_in_flight=spend_gate,
    )

    spend_lock = threading.Lock()
    spend_counts = {"starts": 0, "completes": 0, "hard_ceiling_429": 0, "other": 0}

    def spend_worker(_: int) -> None:
        with TestClient(spend_app) as client:
            for _ in range(10):
                response = client.post("/suggest", json=_BODY)
                with spend_lock:
                    spend_counts["starts"] += 1
                    if response.status_code == 200:
                        spend_counts["completes"] += 1
                    elif response.status_code == 429 and response.headers.get("retry-after") == str(
                        _WINDOW_SECONDS
                    ):
                        spend_counts["hard_ceiling_429"] += 1
                    else:
                        spend_counts["other"] += 1

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(spend_worker, i) for i in range(6)]
        for future in as_completed(futures):
            future.result(timeout=60)

    assert spend_counts["other"] == 0, spend_counts
    assert spend_counts["completes"] == hard_ceiling, spend_counts
    assert spend_counts["hard_ceiling_429"] >= 1, spend_counts
    counts["starts"] += spend_counts["starts"]
    counts["completes"] += spend_counts["completes"]
    counts["hard_ceiling_429"] += spend_counts["hard_ceiling_429"]

    assert counts["other"] == 0, counts
    assert counts["capacity_429"] >= 1, counts
    assert counts["hard_ceiling_429"] >= 1, counts
    assert counts["completes"] >= 1, counts

    spend_probe = spend_gate.acquire()
    assert spend_probe.retry_after is None and spend_probe.token is not None
    spend_gate.release(spend_probe.token)


def test_load_cancel_under_capacity_accounts_and_drains() -> None:
    """ASGI disconnect under capacity: cancels + completes account; no leaked slots."""
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

    async def one_call(*, disconnect_gate: asyncio.Event | None) -> int | None:
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/suggest",
            "raw_path": b"/suggest",
            "query_string": b"",
            "headers": [
                (b"host", b"test"),
                (b"content-type", b"application/json"),
                (b"content-length", str(len(raw_body)).encode()),
            ],
            "client": ("127.0.0.1", 50000),
            "server": ("test", 80),
            "state": {},
        }
        messages: list[dict] = [{"type": "http.request", "body": raw_body, "more_body": False}]
        sent: list[dict] = []

        async def receive() -> dict:
            if messages:
                return messages.pop(0)
            if disconnect_gate is not None:
                await disconnect_gate.wait()
                return {"type": "http.disconnect"}
            await asyncio.sleep(60)
            return {"type": "http.disconnect"}

        async def send(message: dict) -> None:
            sent.append(message)

        await app(scope, receive, send)
        return next(
            (m.get("status") for m in sent if m.get("type") == "http.response.start"),
            None,
        )

    async def run() -> None:
        for _ in range(_CANCEL_WAVES):
            llm.release.clear()
            baseline = llm.calls
            disconnect = asyncio.Event()
            task_a = asyncio.create_task(one_call(disconnect_gate=disconnect))
            task_b = asyncio.create_task(one_call(disconnect_gate=None))
            deadline = time.monotonic() + 2
            while llm.calls < baseline + 2 and time.monotonic() < deadline:
                await asyncio.sleep(0.01)
            assert llm.calls >= baseline + 2
            disconnect.set()
            status_a = await asyncio.wait_for(task_a, timeout=5)
            assert status_a == 499
            llm.release.set()
            status_b = await asyncio.wait_for(task_b, timeout=5)
            assert status_b == 200
            record(status_a)
            record(status_b)

        assert counts["cancels"] == _CANCEL_WAVES, counts
        assert counts["completes"] == _CANCEL_WAVES, counts
        assert counts["other"] == 0, counts
        accounted = counts["completes"] + counts["capacity_429"] + counts["cancels"]
        assert accounted == counts["starts"], counts

        probe = gate.acquire()
        assert probe.retry_after is None and probe.token is not None
        gate.release(probe.token)
        # release is set, so BlockingLLM completes a fresh TestClient suggest.
        with TestClient(app) as client:
            assert client.post("/suggest", json=_BODY).status_code == 200

    asyncio.run(run())
