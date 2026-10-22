"""Per-user sliding-window rate limiter (in memory, single process)."""
from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Dict


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int = 0


class RateLimiter:
    """Allow at most `max_requests` per `window_seconds` for each user id."""

    _SWEEP_THRESHOLD = 5000

    def __init__(
        self,
        max_requests: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_requests < 1:
            raise ValueError("max_requests must be at least 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._max = max_requests
        self._window = float(window_seconds)
        self._clock = clock
        self._hits: Dict[int, Deque[float]] = {}

    def check(self, user_id: int) -> RateLimitDecision:
        """Record an attempt for `user_id` and say whether it is allowed."""
        now = self._clock()
        if len(self._hits) > self._SWEEP_THRESHOLD:
            self._sweep(now)
        hits = self._hits.setdefault(user_id, deque())
        cutoff = now - self._window
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= self._max:
            retry = max(1, math.ceil(hits[0] + self._window - now))
            return RateLimitDecision(False, retry)
        hits.append(now)
        return RateLimitDecision(True, 0)

    def reset(self, user_id: int) -> None:
        self._hits.pop(user_id, None)

    def _sweep(self, now: float) -> None:
        cutoff = now - self._window
        for uid in [u for u, h in self._hits.items() if not h or h[-1] <= cutoff]:
            del self._hits[uid]
