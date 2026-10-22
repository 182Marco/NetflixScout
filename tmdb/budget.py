"""Per-turn budget of HTTP attempts: the only TMDb call limit.

`TmdbTool.new_context` creates one `CallBudget` per run. A turn has at most one TMDb run:
the orchestrator runs exactly one tool per turn (guarded by `tests/test_orchestrator.py`),
and the RAG enrichment (`tmdb/enrich.py`) runs only after `rag_search`, never in a
`tmdb_search` turn. If a multi-step agent loop is ever added, the budget must move to a
turn-scoped context.
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
