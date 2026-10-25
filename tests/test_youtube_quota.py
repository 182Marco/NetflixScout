from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from tool.youtube.quota import QuotaBucket, QuotaLatch, bucket_for, next_reset

PT = ZoneInfo("America/Los_Angeles")
UTC = ZoneInfo("UTC")


def ts(*args: int, zone: ZoneInfo = PT) -> float:
    return datetime(*args, tzinfo=zone).timestamp()


class Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.mark.parametrize(
    ("path", "bucket"),
    [("/search", QuotaBucket.search), ("/videos", QuotaBucket.default), ("/channels", QuotaBucket.default)],
)
def test_search_has_its_own_bucket(path, bucket) -> None:
    assert bucket_for(path) is bucket


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        # Ordinary day (PDT, UTC-7).
        (ts(2026, 10, 23, 15, 0), ts(2026, 10, 24, 7, 0, zone=UTC)),
        # Exactly at midnight: the next one, not now.
        (ts(2026, 10, 23, 0, 0), ts(2026, 10, 24, 7, 0, zone=UTC)),
        # Night before DST ends (2026-11-01 02:00): midnight is still PDT.
        (ts(2026, 10, 31, 22, 0), ts(2026, 11, 1, 7, 0, zone=UTC)),
        # Day DST ends: next midnight is PST (UTC-8).
        (ts(2026, 11, 1, 12, 0), ts(2026, 11, 2, 8, 0, zone=UTC)),
        # Day DST starts (2026-03-08): next midnight is PDT.
        (ts(2026, 3, 8, 12, 0), ts(2026, 3, 9, 7, 0, zone=UTC)),
        # Late evening in Italy is already the next day in UTC, still the same day in PT.
        (ts(2026, 10, 23, 23, 30, zone=ZoneInfo("Europe/Rome")), ts(2026, 10, 24, 7, 0, zone=UTC)),
    ],
)
def test_next_reset_is_the_next_midnight_pacific_time(now, expected) -> None:
    assert next_reset(now) == expected


def test_a_fresh_latch_blocks_nothing_and_never_trips_by_itself() -> None:
    latch = QuotaLatch(Clock(ts(2026, 10, 23, 15, 0)))

    # No local counter: asking many times never blocks, only an observed error does.
    for _ in range(500):
        assert latch.blocked(QuotaBucket.search) is None
    assert latch.blocked(QuotaBucket.default) is None
    assert latch.paused_until(QuotaBucket.search) is None


def test_quota_error_blocks_only_its_bucket_until_the_reset() -> None:
    clock = Clock(ts(2026, 10, 23, 15, 0))
    latch = QuotaLatch(clock)

    latch.trip_until_reset(QuotaBucket.search)

    assert latch.blocked(QuotaBucket.search) == "quota_exceeded"
    assert latch.blocked(QuotaBucket.default) is None
    assert latch.paused_until(QuotaBucket.search) == ts(2026, 10, 24, 0, 0)

    clock.now = ts(2026, 10, 23, 23, 59, 59)
    assert latch.blocked(QuotaBucket.search) == "quota_exceeded"
    clock.now = ts(2026, 10, 24, 0, 0)
    assert latch.blocked(QuotaBucket.search) is None
    assert latch.paused_until(QuotaBucket.search) is None


def test_rate_limit_is_a_short_pause() -> None:
    clock = Clock(1_000.0)
    latch = QuotaLatch(clock)

    latch.pause(QuotaBucket.default, 10.0)

    assert latch.blocked(QuotaBucket.default) == "rate_limited"
    assert latch.blocked(QuotaBucket.search) is None
    clock.now = 1_010.0
    assert latch.blocked(QuotaBucket.default) is None


def test_a_short_pause_never_shortens_the_daily_quota_latch() -> None:
    clock = Clock(ts(2026, 10, 23, 15, 0))
    latch = QuotaLatch(clock)

    latch.trip_until_reset(QuotaBucket.search)
    latch.pause(QuotaBucket.search, 10.0)

    assert latch.blocked(QuotaBucket.search) == "quota_exceeded"
    assert latch.paused_until(QuotaBucket.search) == ts(2026, 10, 24, 0, 0)


def test_quota_error_after_a_rate_limit_extends_the_pause() -> None:
    clock = Clock(ts(2026, 10, 23, 15, 0))
    latch = QuotaLatch(clock)

    latch.pause(QuotaBucket.search, 10.0)
    latch.trip_until_reset(QuotaBucket.search)

    assert latch.blocked(QuotaBucket.search) == "quota_exceeded"


def test_a_new_latch_forgets_the_state_of_a_previous_process() -> None:
    clock = Clock(ts(2026, 10, 23, 15, 0))
    old = QuotaLatch(clock)
    old.trip_until_reset(QuotaBucket.search)

    # Quota spent elsewhere is unknown until the API says so: a new process tries again.
    assert QuotaLatch(clock).blocked(QuotaBucket.search) is None
