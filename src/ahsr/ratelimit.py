"""In-memory token-bucket rate limiter (per client key, thread-safe).

Cheap endpoints cost 1 token, expensive ones (agent, re-index, eval) cost more, so one budget covers
everything. For multi-replica deployments put a shared limiter (Redis, API gateway) in front instead.
"""
from __future__ import annotations

import threading
import time
from typing import Callable


class TokenBucketLimiter:
    def __init__(self, per_minute: int, burst: int | None = None, clock: Callable[[], float] = time.monotonic):
        self.per_minute = per_minute
        self.capacity = float(burst or per_minute)
        self.rate = per_minute / 60.0                    # tokens per second
        self.clock = clock
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.per_minute > 0

    def check(self, key: str, cost: float = 1.0) -> tuple[bool, float]:
        """Try to spend ``cost`` tokens. Returns (allowed, seconds_until_retry)."""
        if not self.enabled:
            return True, 0.0
        cost = min(cost, self.capacity)
        now = self.clock()
        with self._lock:
            tokens, last = self._buckets.get(key, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            if tokens >= cost:
                self._buckets[key] = (tokens - cost, now)
                self._prune(now)
                return True, 0.0
            self._buckets[key] = (tokens, now)
            return False, (cost - tokens) / self.rate

    def _prune(self, now: float) -> None:
        if len(self._buckets) < 10_000:
            return
        horizon = self.capacity / self.rate
        for k in [k for k, (_, last) in self._buckets.items() if now - last > horizon]:
            del self._buckets[k]
