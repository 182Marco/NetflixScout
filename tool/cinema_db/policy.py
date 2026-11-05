"""What the agent may read: views, their columns, the base columns behind them, functions and limits. Pure data.

The policy is the single source for the validator, the authorizer and (later) the planner prompt. It is checked
against the real database when the connection opens (`connection.verify_policy`), so it cannot drift from it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .settings import DEFAULT_FUNCTIONS, QueryLimits


@dataclass(frozen=True)
class ViewSpec:
    name: str
    columns: tuple[tuple[str, str], ...]  # (column, declared type) in the order of the view
    doc: str = ""

    @property
    def column_names(self) -> frozenset[str]:
        return frozenset(c for c, _ in self.columns)


@dataclass(frozen=True)
class Policy:
    views: tuple[ViewSpec, ...]
    # table -> columns of base tables that the views read. Anything else in a base table is never readable.
    base_columns: dict[str, frozenset[str]]
    functions: frozenset[str] = DEFAULT_FUNCTIONS
    # Base tables on which a full SCAN is refused unless the query is bounded (see executor.check_plan).
    large_tables: frozenset[str] = frozenset()
    limits: QueryLimits = field(default_factory=QueryLimits)

    def view(self, name: str) -> ViewSpec | None:
        key = name.casefold()
        return next((v for v in self.views if v.name.casefold() == key), None)

    @property
    def view_names(self) -> frozenset[str]:
        return frozenset(v.name.casefold() for v in self.views)

    @property
    def base_table_names(self) -> frozenset[str]:
        return frozenset(t.casefold() for t in self.base_columns)

    def schema_for_qualify(self) -> dict[str, dict[str, str]]:
        return {v.name: {c: t for c, t in v.columns} for v in self.views}
