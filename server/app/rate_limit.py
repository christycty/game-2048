import math
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import NamedTuple

_Clock = Callable[[], float]


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
            self._hits = deque(
                (stamp, hit) for stamp, hit in self._hits if hit is not token
            )
