"""One run of the tool against the database: every statement goes through the validator, the guarded connection and the executor.

The tool never touches SQLite directly. A session holds the open (read-only, immutable) connection of ONE run, the turn's query budget and
the record of what was really executed (rewritten SQL text, parameters, views, rows, milliseconds), which is what the trace shows.
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from .connection import GuardedConnection
from .constants import TURNS_REMEMBERED
from .errors import CinemaSqlError
from .executor import QueryResult, execute
from .validator import validate


class TurnLimit(CinemaSqlError):
    code = "turn_limit"


@dataclass
class TurnBudget:
    """Queries still allowed in one turn: shared by every run with the same `turn_id`."""

    limit: int
    used: int = 0

    def reserve(self) -> None:
        if self.used >= self.limit:
            raise TurnLimit("The query limit of this turn was reached.")
        self.used += 1


class TurnBudgets:
    """Budgets by `turn_id`, bounded and locked (two conversations running together never share one)."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._budgets: OrderedDict[str, TurnBudget] = OrderedDict()
        self._lock = threading.Lock()

    def for_turn(self, turn_id: str | None) -> TurnBudget:
        if turn_id is None:
            return TurnBudget(self.limit)  # no turn: every run has its own
        with self._lock:
            budget = self._budgets.get(turn_id)
            if budget is None:
                budget = self._budgets[turn_id] = TurnBudget(self.limit)
                while len(self._budgets) > TURNS_REMEMBERED:
                    self._budgets.popitem(last=False)
            else:
                self._budgets.move_to_end(turn_id)
            return budget


@dataclass
class Session:
    guarded: GuardedConnection
    budget: TurnBudget
    calls: list[dict[str, Any]] = field(default_factory=list)
    schema: int = 2  # 3 = the reconciled IMDb layer: ratings, identification level, provenance
    movielens: bool = False  # schema 4: MovieLens films, genres and tags

    def query(self, sql: str, params: list[Any] | tuple[Any, ...] = ()) -> QueryResult:
        """Validate, reserve a query of the turn's budget, run. Raises a typed `CinemaSqlError`; the engine's own text is never exposed."""
        checked = validate(sql, list(params), self.guarded.policy)
        self.budget.reserve()
        result = execute(self.guarded, checked)
        self.calls.append(
            {"sql": result.sql, "params": list(result.params), "views": list(result.views), "rows": len(result.rows), "ms": result.elapsed_ms, "truncated": result.truncated}
        )
        return result

    def rows(self, sql: str, params: list[Any] | tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        result = self.query(sql, params)
        return [dict(zip(result.columns, row)) for row in result.rows]

    def close(self) -> None:
        self.guarded.close()
