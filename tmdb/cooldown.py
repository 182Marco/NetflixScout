"""Pause after a 429: until it expires requests are skipped (not sent, not counted)."""
from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping

from .settings import RATE_LIMIT_COOLDOWN_MAX_SECONDS, RATE_LIMIT_COOLDOWN_SECONDS


class Cooldown:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._until = 0.0
        self._lock = threading.Lock()

    def active(self) -> bool:
        return self._clock() < self._until

    def trip(self, seconds: float) -> None:
        with self._lock:
            self._until = max(self._until, self._clock() + seconds)


def retry_after_seconds(headers: Mapping[str, str]) -> float:
    raw = next((value for key, value in headers.items() if key.lower() == "retry-after"), None)
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return RATE_LIMIT_COOLDOWN_SECONDS
    return min(max(seconds, 1.0), RATE_LIMIT_COOLDOWN_MAX_SECONDS)
