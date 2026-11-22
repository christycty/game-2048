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
from app.rate_limit import LlmInFlightGate
from helpers import OPEN_BOARD, BlockingLLM, FakeLLM, isolated_settings

pytestmark = pytest.mark.load

_WORKERS = 6
_PER_WORKER = 10
_BODY = {"board": OPEN_BOARD, "mode": "llm"}
_CANCEL_WAVES = 6


def _run_load(*, max_in_flight: int) -> None:
    total = _WORKERS * _PER_WORKER
    # Stay under Settings max (120) so 429s are capacity, not hard ceiling.
    assert total <= 120
    llm = FakeLLM(forever_move="right", delay_seconds=0.02)
    gate = LlmInFlightGate(max_in_flight)
    settings = isolated_settings(
        suggest_rate_limit_requests=120,
        llm_max_in_flight=max_in_flight,
    )
    app = create_app(settings, llm, llm_in_flight=gate)
    counts = {"starts": 0, "completes": 0, "capacity_429": 0, "cancels": 0, "other": 0}
    lock = threading.Lock()

    def worker(_: int) -> None:
        with TestClient(app) as client:
            for _ in range(_PER_WORKER):
                with lock:
                    counts["starts"] += 1
                response = client.post("/suggest", json=_BODY)
                with lock:
                    if response.status_code == 200:
                        counts["completes"] += 1
                    elif response.status_code == 429:
                        # FakeLLM load has no hard-ceiling pressure; Retry-After 1 = capacity.
                        assert response.headers.get("retry-after") == "1"
                        counts["capacity_429"] += 1
                    elif response.status_code == 499:
                        counts["cancels"] += 1
                    else:
                        counts["other"] += 1

    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = [pool.submit(worker, i) for i in range(_WORKERS)]
        for future in as_completed(futures):
            future.result(timeout=60)

    assert counts["other"] == 0, counts
    assert counts["starts"] == total, counts
    accounted = counts["completes"] + counts["capacity_429"] + counts["cancels"]
    assert accounted == counts["starts"], counts
    assert counts["completes"] >= 1, counts
    # Capacity contention should appear under delay + max_in_flight < workers.
    if max_in_flight < _WORKERS:
        assert counts["capacity_429"] >= 1, counts

    probe = gate.acquire()
    assert probe.retry_after is None and probe.token is not None
    gate.release(probe.token)
    with TestClient(app) as client:
        assert client.post("/suggest", json=_BODY).status_code == 200


@pytest.mark.parametrize("max_in_flight", [1, 2])
def test_load_suggest_accounts_and_drains(max_in_flight: int) -> None:
    _run_load(max_in_flight=max_in_flight)


def test_load_mixed_429_layers_classified_by_retry_after() -> None:
    """Concurrent soak surfaces both 429 layers; classify by Retry-After (same detail today)."""
    workers = 6
    per_worker = 10
    total = workers * per_worker
    # Low enough that completes fill the window before workers finish (capacity
    # rejects refund and do not burn the ceiling).
    hard_ceiling = 3
    llm = FakeLLM(forever_move="right", delay_seconds=0.02)
    gate = LlmInFlightGate(1)
    settings = isolated_settings(
        suggest_rate_limit_requests=hard_ceiling,
        llm_max_in_flight=1,
    )
    app = create_app(settings, llm, llm_in_flight=gate)
    counts = {
        "starts": 0,
        "completes": 0,
        "capacity_429": 0,
        "hard_ceiling_429": 0,
        "cancels": 0,
        "other": 0,
    }
    lock = threading.Lock()

    def worker(_: int) -> None:
        with TestClient(app) as client:
            for _ in range(per_worker):
                with lock:
                    counts["starts"] += 1
                response = client.post("/suggest", json=_BODY)
                with lock:
                    if response.status_code == 200:
                        counts["completes"] += 1
                    elif response.status_code == 429:
                        retry = response.headers.get("retry-after")
                        if retry == "1":
                            counts["capacity_429"] += 1
                        elif retry is not None and int(retry) > 1:
                            counts["hard_ceiling_429"] += 1
                        else:
                            counts["other"] += 1
                    elif response.status_code == 499:
                        counts["cancels"] += 1
                    else:
                        counts["other"] += 1

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(worker, i) for i in range(workers)]
        for future in as_completed(futures):
            future.result(timeout=60)

    assert counts["other"] == 0, counts
    assert counts["starts"] == total, counts
    accounted = (
        counts["completes"]
        + counts["capacity_429"]
        + counts["hard_ceiling_429"]
        + counts["cancels"]
    )
    assert accounted == counts["starts"], counts
    assert counts["capacity_429"] >= 1, counts
    assert counts["hard_ceiling_429"] >= 1, counts
    # Completes cannot exceed the hard window (refunded capacity rejects do not count).
    assert counts["completes"] <= hard_ceiling, counts

    probe = gate.acquire()
    assert probe.retry_after is None and probe.token is not None
    gate.release(probe.token)


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
        # Fresh FakeLLM path after BlockingLLM waves — swap to AlwaysLLM via new app? Same app
        # still has BlockingLLM; release is set so a TestClient call completes.
        with TestClient(app) as client:
            assert client.post("/suggest", json=_BODY).status_code == 200

    asyncio.run(run())
