import math
import threading
import time
from collections import deque
from collections.abc import Callable

_Clock = Callable[[], float]


class SuggestRateLimiter:
    """Process-wide cap on suggestion calls.

    Prod nginx is the API's only caller, so a per-IP limit would not bound
    model spend. The lock covers overlapping requests in the FastAPI threadpool.
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
        self._hits: deque[float] = deque()
        self._lock = threading.Lock()

    def allow(self) -> int | None:
        """Record a hit and return None, or return Retry-After seconds."""
        with self._lock:
            now = self._clock()
            cutoff = now - self._window_seconds
            while self._hits and self._hits[0] <= cutoff:
                self._hits.popleft()
            if len(self._hits) >= self._max_requests:
                retry = self._hits[0] + self._window_seconds - now
                return max(1, math.ceil(retry))
            self._hits.append(now)
            return None
