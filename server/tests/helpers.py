from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from typing import Any

from app.cancel import SuggestCancelled
from app.config import Settings
from app.llm import ModelSuggestion

# Right-hand column. Left only slides it, which is also the fallback direction.
COLUMN_PAIR = [
    [0, 0, 0, 4],
    [0, 0, 0, 4],
    [0, 0, 0, 8],
    [0, 0, 0, 0],
]

# Sorted top row, plus a 2 in the opposite corner. Up wrecks the row.
# Right only slides that 2, and up is the fallback.
SORTED_ROW = [
    [16, 8, 4, 2],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
    [2, 0, 0, 0],
]

OPEN_BOARD = [
    [2, 0, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
]

# test_suggest_e2e shares one app across every parametrized /suggest.
# Keep these equal to len(E2E_BOARDS) * len(E2E_RUN_IDS) in that file.
E2E_BOARD_COUNT = 2
E2E_RUN_COUNT = 3
E2E_SUGGEST_CALLS = E2E_BOARD_COUNT * E2E_RUN_COUNT
# Shared e2e suggest_client rate-limit budget. Intentionally loose above the
# parametrized matrix so adding another @pytest.mark.e2e LLM POST does not
# require a paired constant bump (extras: traceparent, metrics, cancel beacon,
# ASGI disconnect cancel). Stay well under the LLM hard-ceiling default (60).
E2E_RATE_LIMIT_REQUESTS = 24
assert E2E_RATE_LIMIT_REQUESTS > E2E_SUGGEST_CALLS

# Every Settings field must appear here. Init kwargs beat env; omitted fields
# still read SUGGEST_RATE_LIMIT_* / .env and the helper stops being isolated.
ISOLATED_SETTINGS_DEFAULTS: dict[str, object] = {
    "app_env": "dev",
    "ollama_base_url": "http://ollama.test",
    "ollama_model": "test-model",
    "ollama_structured_output": False,
    "llm_max_attempts": 3,
    "llm_attempt_timeout_seconds": 20,
    "llm_suggest_budget_seconds": 40,
    "suggest_rate_limit_requests": 60,
    "suggest_rate_limit_expectimax_requests": 30,
    "suggest_rate_limit_window_seconds": 60,
    "llm_max_in_flight": 1,
    "client_events_rate_limit_requests": 60,
    "client_events_rate_limit_window_seconds": 60,
    "client_host_port": 5173,
    "phoenix_collector_endpoint": "http://phoenix.test",
    "phoenix_api_key": None,
    "export_traces": False,
}


def isolated_settings(**overrides: object) -> Settings:
    """Settings from explicit values, so a developer .env cannot change the test."""
    values = dict(ISOLATED_SETTINGS_DEFAULTS)
    values.update(overrides)
    return Settings(**values)


class FrozenClock:
    """Injectable clock for rate-limit tests. Advance ``now`` to control Retry-After."""

    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@dataclass(frozen=True)
class AsgiSuggestResult:
    status: int | None
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        import json

        return json.loads(self.body)


async def asgi_suggest(
    app: Any,
    raw_body: bytes,
    *,
    disconnect_gate: asyncio.Event | None = None,
) -> AsgiSuggestResult:
    """POST /suggest via raw ASGI (no TestClient lifespan).

    Use this while other /suggest calls are in flight on the same app — a
    ``with TestClient(app)`` would run lifespan shutdown and call
    ``shutdown_telemetry`` mid-request.
    """
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
    status: int | None = None
    headers: dict[str, str] = {}
    body = b""
    for message in sent:
        if message.get("type") == "http.response.start":
            status = message.get("status")
            headers = {
                key.decode().lower(): value.decode() for key, value in message.get("headers", [])
            }
        elif message.get("type") == "http.response.body":
            body += message.get("body") or b""
    return AsgiSuggestResult(status=status, headers=headers, body=body)


class FakeLLM:
    """Queued replies for unit/API tests. Use BlockingLLM when you need a held slot."""

    def __init__(self, replies: list) -> None:
        self._replies = list(replies)
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
        self.legal = legal
        self.rejected = list(rejected)
        self.invalid_reply = invalid_reply
        if cancel is not None and cancel.is_set():
            raise SuggestCancelled()
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, str):
            return ModelSuggestion(reply, "ok")
        return reply


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
