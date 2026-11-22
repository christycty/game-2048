import math
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import NamedTuple

_Clock = Callable[[], float]

# Distinct 429 details so clients can retry capacity without treating spend as busy.
DETAIL_SPEND_CAP = "too many suggestions"
DETAIL_MODEL_BUSY = "model busy"
LIMIT_REASON_SPEND = "spend"
LIMIT_REASON_CAPACITY = "capacity"
# Surfaced on capacity/spend 429s (detail is the primary contract; header is explicit).
HEADER_SUGGEST_LIMIT = "X-Suggest-Limit"


class GateDecision(NamedTuple):
    """Outcome of ``allow``: either a hit token or a Retry-After delay."""

    token: object | None
    retry_after: int | None


class SuggestRateLimiter:
    """Process-wide sliding-window cap for one suggestion mode.

    Prod nginx is the API's only caller, so a per-IP limit would not bound
    spend. The app keeps one limiter per mode (llm vs expectimax). The lock
    covers overlapping requests in the FastAPI threadpool.
    """

    def __init__(
        self,
        max_requests: int,
        window_seconds: float,
        clock: _Clock | None = None,
    ) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._clock = clock or time.monotonic
        # (timestamp, token) so cancel can release the matching hit under concurrency.
        self._hits: deque[tuple[float, object]] = deque()
        self._lock = threading.Lock()

    def allow(self) -> GateDecision:
        """Record a hit and return its token, or return Retry-After seconds."""
        with self._lock:
            now = self._clock()
            cutoff = now - self._window_seconds
            while self._hits and self._hits[0][0] <= cutoff:
                self._hits.popleft()
            if len(self._hits) >= self._max_requests:
                retry = self._hits[0][0] + self._window_seconds - now
                return GateDecision(token=None, retry_after=max(1, math.ceil(retry)))
            token = object()
            self._hits.append((now, token))
            return GateDecision(token=token, retry_after=None)

    def release(self, token: object) -> None:
        """Drop this request's hit after a client cancel so Stop does not burn the cap."""
        with self._lock:
            self._hits = deque((stamp, hit) for stamp, hit in self._hits if hit is not token)


class LlmInFlightGate:
    """Process-wide concurrency cap for LLM suggestions (Ollama capacity).

    Default max is 1: one in-flight Ollama call at a time. Non-blocking; a full
    gate returns Retry-After like the sliding-window limiter (v1: no queue).
    Held tokens are tracked so release only frees that request's slot (same
    cancel-safe pattern as SuggestRateLimiter under max_in_flight > 1).
    """

    # Busy clients should retry soon; we do not know when the holder finishes.
    _RETRY_AFTER_SECONDS = 1

    def __init__(self, max_in_flight: int) -> None:
        if max_in_flight < 1:
            raise ValueError("max_in_flight must be >= 1")
        self._max_in_flight = max_in_flight
        self._held: set[object] = set()
        self._lock = threading.Lock()

    def acquire(self) -> GateDecision:
        """Take a slot, or return Retry-After when every slot is held."""
        with self._lock:
            if len(self._held) >= self._max_in_flight:
                return GateDecision(token=None, retry_after=self._RETRY_AFTER_SECONDS)
            token = object()
            self._held.add(token)
            return GateDecision(token=token, retry_after=None)

    def release(self, token: object) -> None:
        """Free the slot acquired with ``token`` (ignore unknown / double release)."""
        if token is None:
            return
        with self._lock:
            self._held.discard(token)
