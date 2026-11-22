import threading
import time

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


class FakeLLM:
    """Queued replies for unit/API tests. Optional delay creates capacity contention."""

    def __init__(
        self,
        replies: list | None = None,
        *,
        delay_seconds: float = 0.0,
        forever_move: str | None = None,
    ) -> None:
        self._replies = None if replies is None else list(replies)
        self._delay_seconds = delay_seconds
        self._forever_move = forever_move
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
        if self._delay_seconds > 0:
            deadline = time.monotonic() + self._delay_seconds
            while time.monotonic() < deadline:
                if cancel is not None and cancel.is_set():
                    raise SuggestCancelled()
                time.sleep(0.005)
        if self._forever_move is not None:
            return ModelSuggestion(self._forever_move, "ok")
        if self._replies is None:
            raise AssertionError("FakeLLM has no replies and no forever_move")
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
