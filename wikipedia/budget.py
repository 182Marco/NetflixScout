"""State of one turn: HTTP calls used, context handed out, sections already delivered.

A turn can run the tool several times (a first reading, then the sections the orchestrator asks
for), so the limits are the turn's, not the run's: runs with the same `turn_id` share a
`TurnState`. The registry keeps a bounded number of turns and is safe to share between the
threads of concurrent conversations; one turn is run by one thread. A run without a `turn_id`
gets a fresh state each time.
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, field

from .settings import MAX_TURN_STATES

# (language, API title) of an article.
PageKey = tuple[str, str]


@dataclass
class TurnState:
    http_used: int = 0
    context_used: int = 0
    # Normalized titles of the sections already handed out, per article.
    delivered: dict[PageKey, set[str]] = field(default_factory=dict)
    # Editions asked in this turn (a search or an opening was attempted there).
    languages_tried: set[str] = field(default_factory=set)
    # Articles whose full text was read in this turn (downloaded or served from the cache).
    opened: set[PageKey] = field(default_factory=set)
    # Requests sent in this turn that failed: (error class, safe message) by request key.
    failures: dict[object, tuple[type[Exception], str]] = field(default_factory=dict)

    def http_left(self, limit: int) -> int:
        return max(limit - self.http_used, 0)

    def try_reserve_http(self, limit: int) -> bool:
        """Count one sent request if the turn still has room for it."""
        if self.http_used >= limit:
            return False
        self.http_used += 1
        return True

    def context_left(self, budget: int) -> int:
        return max(budget - self.context_used, 0)

    def delivered_for(self, key: PageKey) -> set[str]:
        return self.delivered.setdefault(key, set())


class TurnRegistry:
    def __init__(self, max_turns: int = MAX_TURN_STATES) -> None:
        self.max_turns = max_turns
        self._turns: OrderedDict[str, TurnState] = OrderedDict()
        self._lock = threading.Lock()

    def state(self, turn_id: str | None) -> TurnState:
        if turn_id is None:
            return TurnState()
        with self._lock:
            state = self._turns.get(turn_id)
            if state is None:
                state = self._turns[turn_id] = TurnState()
                while len(self._turns) > self.max_turns:
                    self._turns.popitem(last=False)
            else:
                self._turns.move_to_end(turn_id)
            return state
