"""Per-user token-bucket rate limiter (in-process, injectable clock)."""
from __future__ import annotations

import threading
import time
from collections.abc import Callable


class RateLimited(Exception):
    def __init__(self, retry_after: float) -> None:
        super().__init__(f"rate_limited: retry after {retry_after:.1f}s")
        self.retry_after = retry_after


class TokenBucketLimiter:
    """``rpm`` sustained requests per minute per user, with ``burst`` capacity."""

    def __init__(self, rpm: float, burst: int | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if rpm <= 0:
            raise ValueError("rpm must be positive")
        self.rate = rpm / 60.0
        self.capacity = float(burst if burst is not None else max(1, int(rpm // 4)))
        self._clock = clock
        self._state: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def acquire(self, user: str, cost: float = 1.0) -> None:
        with self._lock:
            now = self._clock()
            tokens, last = self._state.get(user, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            if tokens < cost:
                self._state[user] = (tokens, now)
                raise RateLimited((cost - tokens) / self.rate)
            self._state[user] = (tokens - cost, now)
