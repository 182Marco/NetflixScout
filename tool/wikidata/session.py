"""State kept in memory: the session of one turn and the pause after a rate limit.

A session (call budget, memo of answers and failures, calls made) lives only for the turn it
belongs to (`turn_id`): a new turn asks Wikidata again, nothing is written to disk. A few finished
turns are kept only so that the runs of the same turn share one budget and one memo.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .errors import WikidataError
from .settings import (
    RATE_LIMIT_PAUSE_DEFAULT_SECONDS,
    RATE_LIMIT_PAUSE_MAX_SECONDS,
    RATE_LIMIT_PAUSE_MIN_SECONDS,
    TURNS_REMEMBERED,
)

# (url, headers, timeout) -> (status, response headers, body)
Transport = Callable[[str, Mapping[str, str], float], tuple[int, Mapping[str, str], bytes]]
MemoKey = tuple[str, tuple[tuple[str, str], ...]]


class RateLimitPause:
    """After an HTTP 429 nothing is sent for a few seconds (the limit is per IP, so it is shared)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._until = 0.0
        self._lock = threading.Lock()

    def trip(self, retry_after: str | None) -> None:
        try:
            seconds = float(retry_after) if retry_after is not None else RATE_LIMIT_PAUSE_DEFAULT_SECONDS
        except ValueError:
            seconds = RATE_LIMIT_PAUSE_DEFAULT_SECONDS
        seconds = min(max(seconds, RATE_LIMIT_PAUSE_MIN_SECONDS), RATE_LIMIT_PAUSE_MAX_SECONDS)
        with self._lock:
            self._until = max(self._until, self._clock() + seconds)

    def active(self) -> bool:
        with self._lock:
            return self._clock() < self._until


# One per process: the limit it mirrors is per IP address.
PROCESS_PAUSE = RateLimitPause()


@dataclass(kw_only=True)
class HttpSession:
    """State of one turn: dependencies, the call budget, what was already asked and what was sent."""

    transport: Transport
    max_calls: int
    pause: RateLimitPause = field(default_factory=lambda: PROCESS_PAUSE)
    # Requests actually sent, as shown to the user: {"method", "url"}.
    calls: list[dict[str, str]] = field(default_factory=list)
    # Answers already obtained in this turn (a 404 is stored as None): never requested twice.
    memo: dict[MemoKey, Any] = field(default_factory=dict)
    # Requests sent in this turn that failed: never sent again (no retries).
    failures: dict[MemoKey, WikidataError] = field(default_factory=dict)


class TurnSessions:
    def __init__(self, limit: int = TURNS_REMEMBERED) -> None:
        self._limit = limit
        self._sessions: OrderedDict[str, HttpSession] = OrderedDict()
        self._lock = threading.Lock()

    def session_for(self, turn_id: str | None, make: Callable[[], HttpSession]) -> HttpSession:
        """The session of `turn_id`; without a turn id every run has its own."""
        if turn_id is None:
            return make()
        with self._lock:
            session = self._sessions.get(turn_id)
            if session is None:
                session = self._sessions[turn_id] = make()
                while len(self._sessions) > self._limit:
                    self._sessions.popitem(last=False)
            return session
