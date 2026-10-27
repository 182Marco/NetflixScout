"""In-memory pause after a quota or rate-limit error observed from the YouTube API.

The quota belongs to the Google Cloud project and is also spent by other processes and
applications, so it is never counted here: the only authority is the API answer. After a
`quotaExceeded` the latch avoids calls that would fail anyway until the daily reset
(midnight Pacific Time); a restart forgets it and the next call finds the real state.

Quotas are per bucket: `search.list` has its own daily bucket, every other endpoint
shares the default one, so an exhausted search quota does not block `/videos`.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from enum import Enum
from zoneinfo import ZoneInfo

from .errors import YoutubeQuotaExceeded, YoutubeRateLimited
from .settings import QUOTA_TIMEZONE

SEARCH_PATH = "/search"


class QuotaBucket(str, Enum):
    search = "search"
    default = "default"


def bucket_for(path: str) -> QuotaBucket:
    return QuotaBucket.search if path == SEARCH_PATH else QuotaBucket.default


def next_reset(now: float) -> float:
    """Timestamp of the next midnight in the quota time zone, strictly after `now`."""
    zone = ZoneInfo(QUOTA_TIMEZONE)
    today = datetime.fromtimestamp(now, zone).date()
    # Midnight always exists there: DST changes happen at 02:00.
    return datetime.combine(today + timedelta(days=1), datetime.min.time(), zone).timestamp()


class QuotaLatch:
    """Per-bucket deadline before which no request is sent; shared across the turns of one tool."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        # Wall clock: the daily reset is a time of day, not a duration.
        self._clock = clock
        self._until: dict[QuotaBucket, tuple[float, str]] = {}
        self._lock = threading.Lock()

    def _active(self, bucket: QuotaBucket) -> tuple[float, str] | None:
        with self._lock:
            item = self._until.get(bucket)
            if item is not None and self._clock() >= item[0]:
                del self._until[bucket]
                return None
            return item

    def blocked(self, bucket: QuotaBucket) -> str | None:
        """Error code of the active pause (`quota_exceeded` | `rate_limited`), or None."""
        item = self._active(bucket)
        return item[1] if item else None

    def paused_until(self, bucket: QuotaBucket) -> float | None:
        item = self._active(bucket)
        return item[0] if item else None

    def trip_until_reset(self, bucket: QuotaBucket) -> None:
        """The API answered that the daily quota of `bucket` is spent."""
        self._set(bucket, next_reset(self._clock()), YoutubeQuotaExceeded.code)

    def pause(self, bucket: QuotaBucket, seconds: float) -> None:
        """The API answered with a short-term rate limit."""
        self._set(bucket, self._clock() + seconds, YoutubeRateLimited.code)

    def _set(self, bucket: QuotaBucket, until: float, code: str) -> None:
        with self._lock:
            current = self._until.get(bucket)
            # A short pause never shortens a longer one (e.g. the daily quota).
            if current is None or until > current[0]:
                self._until[bucket] = (until, code)
