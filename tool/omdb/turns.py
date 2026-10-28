"""Sessions of the turns in progress: the budget and the memo of one turn, nothing more.

A session lives only in memory and only for the turn it belongs to (`turn_id`): a new turn
always asks OMDb again, so scores are as fresh as the API gives them. A few finished turns are
kept only so that the runs of the same turn (several steps) share one budget and one memo.
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Callable

from .http import HttpSession
from .settings import TURNS_REMEMBERED


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
