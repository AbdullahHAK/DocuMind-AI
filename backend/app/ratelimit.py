"""In-memory rate limits that protect the public demo (and the API bill).

Two layers:
- SlidingWindowLimiter: N requests per IP per window (stops one person spamming)
- DailyBudget: N LLM questions per day across everyone (caps worst-case cost)

In-memory is fine for a single-instance deployment. With several instances
you'd move these counters to Redis so they're shared.
"""

import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Callable


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self.window = window_seconds
        self.clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, int]:
        """Record a hit for key. Returns (allowed, retry_after_seconds)."""
        now = self.clock()
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False, max(1, int(hits[0] + self.window - now) + 1)
            hits.append(now)
            return True, 0


class DailyBudget:
    def __init__(self, limit: int, today: Callable[[], str] | None = None) -> None:
        self.limit = limit
        self.today = today or (lambda: datetime.now(timezone.utc).date().isoformat())
        self._day, self._used = self.today(), 0
        self._lock = threading.Lock()

    def try_spend(self) -> bool:
        with self._lock:
            if self.today() != self._day:
                self._day, self._used = self.today(), 0
            if self._used >= self.limit:
                return False
            self._used += 1
            return True
