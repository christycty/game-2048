"""Cancellation is per-request: concurrent clients share the process, not cancel Events."""

from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient

from app.cancel import SuggestCancelled
from app.expectimax import choose_move
from app.llm import ModelSuggestion, OllamaClient
from app.main import create_app, watch_disconnect
from app.suggester import MoveSuggester
from helpers import isolated_settings

OPEN_BOARD = [
    [2, 0, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
]


class BlockingLLM:
    """Blocks until cancel fires or release is set. Records which Event cancelled it."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.cancelled_with: threading.Event | None = None
        self.calls = 0
        self._lock = threading.Lock()

    def suggest_move(
        self,
        board: list[list[int]],
        *,
        legal: list[str],
        rejected: list[str],
        invalid_reply: bool,
        cancel: threading.Event | None = None,
    ) -> ModelSuggestion:
        with self._lock:
            self.calls += 1
        self.started.set()
        while True:
            if cancel is not None and cancel.is_set():
                self.cancelled_with = cancel
                raise SuggestCancelled()
            if self.release.is_set():
                return ModelSuggestion("right", "ok")
            time.sleep(0.01)


def test_suggester_raises_when_cancel_set_before_llm() -> None:
    cancel = threading.Event()
    cancel.set()
    llm = BlockingLLM()
    suggester = MoveSuggester(llm, max_attempts=1, budget_seconds=40, attempt_timeout_seconds=20)
    with pytest.raises(SuggestCancelled):
        suggester.suggest(OPEN_BOARD, "llm", cancel)
    assert llm.calls == 0


def test_suggester_propagates_cancel_from_llm() -> None:
    cancel = threading.Event()
    llm = BlockingLLM()
    suggester = MoveSuggester(llm, max_attempts=1, budget_seconds=40, attempt_timeout_seconds=20)

    def run() -> None:
        with pytest.raises(SuggestCancelled):
            suggester.suggest(OPEN_BOARD, "llm", cancel)

    thread = threading.Thread(target=run)
    thread.start()
    assert llm.started.wait(2)
    cancel.set()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert llm.cancelled_with is cancel


def test_expectimax_raises_when_cancel_set() -> None:
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(SuggestCancelled):
        choose_move(OPEN_BOARD, cancel=cancel)


def test_cancel_one_of_two_concurrent_suggests_leaves_the_other() -> None:
    """Process-wide concurrency: aborting client A must not stop client B."""
    llm = BlockingLLM()
    suggester = MoveSuggester(llm, max_attempts=1, budget_seconds=40, attempt_timeout_seconds=20)
    cancel_a = threading.Event()
    cancel_b = threading.Event()
    outcomes: dict[str, str] = {}

    def run_a() -> None:
        try:
            suggester.suggest(OPEN_BOARD, "llm", cancel_a)
            outcomes["a"] = "ok"
        except SuggestCancelled:
            outcomes["a"] = "cancelled"

    def run_b() -> None:
        try:
            result = suggester.suggest(OPEN_BOARD, "llm", cancel_b)
            outcomes["b"] = result.move
        except SuggestCancelled:
            outcomes["b"] = "cancelled"

    with ThreadPoolExecutor(max_workers=2) as pool:
        future_a = pool.submit(run_a)
        future_b = pool.submit(run_b)
        assert llm.started.wait(2)
        # Both may not have entered yet; give the second call a moment.
        deadline = time.monotonic() + 2
        while llm.calls < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert llm.calls == 2
        cancel_a.set()
        future_a.result(timeout=2)
        llm.release.set()
        future_b.result(timeout=2)

    assert outcomes["a"] == "cancelled"
    assert outcomes["b"] == "right"


def test_ollama_client_cancel_closes_only_that_response() -> None:
    """Shared httpx client: cancelling one stream must not break a sibling POST."""
    gate = threading.Event()
    posts = {"count": 0}
    lock = threading.Lock()

    def handler(request: httpx.Request) -> httpx.Response:
        with lock:
            posts["count"] += 1
            index = posts["count"]
        if index == 1:
            gate.wait(timeout=2)
            return httpx.Response(
                200,
                json={"message": {"content": '{"move":"left","reason":"first"}'}},
            )
        return httpx.Response(
            200,
            json={"message": {"content": '{"move":"right","reason":"second"}'}},
        )

    transport = httpx.MockTransport(handler)
    settings = isolated_settings()
    with httpx.Client(transport=transport, base_url="http://ollama.test") as http:
        client = OllamaClient(settings, client=http)
        cancel = threading.Event()
        results: dict[str, object] = {}

        def slow() -> None:
            try:
                results["slow"] = client.suggest_move(
                    OPEN_BOARD,
                    legal=["left", "right", "up", "down"],
                    rejected=[],
                    invalid_reply=False,
                    cancel=cancel,
                )
            except Exception as exc:  # noqa: BLE001 - record whatever the cancel path raises
                results["slow"] = exc

        def fast() -> None:
            # Wait until the slow request has claimed the first handler slot.
            deadline = time.monotonic() + 2
            while posts["count"] < 1 and time.monotonic() < deadline:
                time.sleep(0.01)
            results["fast"] = client.suggest_move(
                OPEN_BOARD,
                legal=["left", "right", "up", "down"],
                rejected=[],
                invalid_reply=False,
            )

        slow_thread = threading.Thread(target=slow)
        fast_thread = threading.Thread(target=fast)
        slow_thread.start()
        deadline = time.monotonic() + 2
        while posts["count"] < 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        cancel.set()
        # Unblock the mock so the closed stream can finish teardown.
        gate.set()
        slow_thread.join(timeout=2)
        fast_thread.start()
        fast_thread.join(timeout=2)

    assert isinstance(results["slow"], SuggestCancelled)
    assert isinstance(results["fast"], ModelSuggestion)
    assert results["fast"].move == "right"


def test_suggest_endpoint_maps_cancel_to_499() -> None:
    class CancelLLM:
        def suggest_move(
            self,
            board: list[list[int]],
            *,
            legal: list[str],
            rejected: list[str],
            invalid_reply: bool,
            cancel: threading.Event | None = None,
        ) -> ModelSuggestion:
            raise SuggestCancelled()

    client = TestClient(create_app(isolated_settings(), CancelLLM()))
    response = client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"})
    assert response.status_code == 499
    assert response.json()["detail"] == "client cancelled"


def test_watch_disconnect_sets_cancel_event() -> None:
    cancel = threading.Event()

    class FakeRequest:
        def __init__(self) -> None:
            self.checks = 0

        async def is_disconnected(self) -> bool:
            self.checks += 1
            return self.checks >= 2

    asyncio.run(watch_disconnect(FakeRequest(), cancel))  # type: ignore[arg-type]
    assert cancel.is_set()


def test_endpoint_disconnect_watcher_cancels_blocking_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Endpoint wires watch_disconnect → cancel Event → SuggestCancelled → 499."""
    import app.main as main

    llm = BlockingLLM()

    async def watch_soon(_request: object, cancel: threading.Event) -> None:
        await asyncio.sleep(0.05)
        cancel.set()

    monkeypatch.setattr(main, "watch_disconnect", watch_soon)
    client = TestClient(main.create_app(isolated_settings(), llm))
    response = client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"})
    assert response.status_code == 499
    assert llm.cancelled_with is not None
    assert llm.calls == 1
