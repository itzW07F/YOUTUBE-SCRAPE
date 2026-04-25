"""Monotonic clock adapter."""

from __future__ import annotations

import time


class MonotonicClock:
    """Default clock using ``time.monotonic``."""

    def monotonic(self) -> float:
        return time.monotonic()
