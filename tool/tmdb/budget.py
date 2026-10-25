"""Per-turn budget of HTTP attempts: the only TMDb call limit.

`TmdbTool.new_context` creates one `CallBudget` per turn: a turn can run several tools
(`orchestrator.max_tool_calls_per_turn`), so every TMDb run and the RAG enrichment
(`tool/tmdb/enrich.py`) of the same `turn_id` draw on the same budget.
"""
from __future__ import annotations

import threading


class CallBudget:
    def __init__(self, limit: int) -> None:
        if limit < 1:
            raise ValueError("limit must be >= 1.")
        self.limit = limit
        self._used = 0
        self._lock = threading.Lock()

    def try_reserve(self) -> bool:
        """Reserve one attempt before it is sent; False once the limit is reached."""
        with self._lock:
            if self._used >= self.limit:
                return False
            self._used += 1
            return True

    @property
    def used(self) -> int:
        return self._used

    @property
    def remaining(self) -> int:
        return self.limit - self._used
