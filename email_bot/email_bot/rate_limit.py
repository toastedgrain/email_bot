"""Simple token-bucket rate limiter for outbound email."""

from __future__ import annotations

import time


class RateLimiter:
    """Enforce *max_per_minute* by sleeping between calls when necessary."""

    def __init__(self, max_per_minute: int) -> None:
        self.interval = 60.0 / max_per_minute if max_per_minute > 0 else 0.0
        self._last: float = 0.0

    def wait(self) -> None:
        """Block until the next send is allowed."""
        if self.interval <= 0:
            return
        now = time.monotonic()
        elapsed = now - self._last
        if elapsed < self.interval:
            time.sleep(self.interval - elapsed)
        self._last = time.monotonic()
