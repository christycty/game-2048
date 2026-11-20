"""Cancellation is per-request: concurrent clients share the process, not cancel Events."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient

from app.cancel import SuggestCancelled
from app.expectimax import choose_move
from app.llm import ModelSuggestion, OllamaClient
from app.main import DisconnectCancelMiddleware, create_app
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


def test_ollama_client_raises_when_cancel_already_set() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            json={"message": {"content": '{"move":"right","reason":"ok"}'}},
        )
    )
    settings = isolated_settings()
    cancel = threading.Event()
    cancel.set()
    with httpx.Client(transport=transport, base_url="http://ollama.test") as http:
        client = OllamaClient(settings, client=http)
        with pytest.raises(SuggestCancelled):
            client.suggest_move(
                OPEN_BOARD,
                legal=["left", "right", "up", "down"],
                rejected=[],
                invalid_reply=False,
                cancel=cancel,
            )


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


def test_disconnect_middleware_sets_cancel_on_disconnect() -> None:
    """Pump owns receive: disconnect sets the Event even while the app is busy."""
    seen: dict[str, object] = {}

    async def inner(scope, receive, send):  # noqa: ANN001
        cancel = scope["state"]["suggest_cancel"]
        seen["cancel"] = cancel
        # Drain the request body through the bridge.
        while True:
            message = await receive()
            if message.get("type") == "http.request" and not message.get("more_body", False):
                break
        # Pump may already have read disconnect (parallel); wait until it lands.
        deadline = time.monotonic() + 2
        while not cancel.is_set() and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        assert cancel.is_set()
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    app = DisconnectCancelMiddleware(inner)
    body = b"{}"
    messages = [
        {"type": "http.request", "body": body, "more_body": False},
        {"type": "http.disconnect"},
    ]

    async def receive() -> dict:
        return messages.pop(0)

    sent: list[dict] = []

    async def send(message: dict) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "path": "/suggest",
        "raw_path": b"/suggest",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1),
        "server": ("test", 80),
        "state": {},
    }
    asyncio.run(app(scope, receive, send))
    assert seen["cancel"].is_set()  # type: ignore[union-attr]
    assert sent[0]["status"] == 204


def test_asgi_disconnect_cancels_blocking_llm() -> None:
    """Full stack: disconnect while BlockingLLM runs → 499, sibling still OK."""
    llm = BlockingLLM()
    settings = isolated_settings(
        suggest_rate_limit_requests=10,
        suggest_rate_limit_expectimax_requests=10,
    )
    app = create_app(settings, llm)
    body = json.dumps({"board": OPEN_BOARD, "mode": "llm"}).encode()

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
                (b"content-length", str(len(body)).encode()),
            ],
            "client": ("127.0.0.1", 50000),
            "server": ("test", 80),
            "state": {},
        }
        messages: list[dict] = [{"type": "http.request", "body": body, "more_body": False}]
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
        gate = asyncio.Event()
        task_a = asyncio.create_task(one_call(disconnect_gate=gate))
        assert await asyncio.to_thread(llm.started.wait, 2)
        gate.set()
        status_a = await asyncio.wait_for(task_a, timeout=3)
        assert llm.cancelled_with is not None
        assert status_a == 499
        llm.release.set()
        task_b = asyncio.create_task(one_call(disconnect_gate=None))
        status_b = await asyncio.wait_for(task_b, timeout=3)
        assert status_b == 200

    asyncio.run(run())
