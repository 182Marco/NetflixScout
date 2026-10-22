"""Channel-neutral view of a `db_query` step, shared by the terminal and web presenters.

The only place that reads `step.data` of a movie DB step, so both channels show the
same queries. Pure: no printing, no import of the `movie_db` package.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from turn import TraceStep

SqlParam = str | int | float | None


class DbQueryItem(BaseModel):
    sql: str
    params: list[SqlParam] = Field(default_factory=list)

    @property
    def display_sql(self) -> str:
        return format_sql(self.sql, self.params)


class DbQueryView(BaseModel):
    title: str
    queries: list[DbQueryItem] = Field(default_factory=list)


def _literal(value: SqlParam) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def format_sql(sql: str, params: list[SqlParam]) -> str:
    """Inline the bind parameters for reading only: the result is never executed.

    `?` inside quoted SQL literals is left alone; if the placeholders do not match the
    parameters, the original SQL is returned unchanged.
    """
    if sql.count("?") < len(params):
        return sql
    out: list[str] = []
    values = iter(params)
    used = 0
    quote: str | None = None
    for char in sql:
        if quote:
            out.append(char)
            if char == quote:
                quote = None
        elif char in ("'", '"'):
            quote = char
            out.append(char)
        elif char == "?":
            try:
                out.append(_literal(next(values)))
                used += 1
            except StopIteration:
                return sql
        else:
            out.append(char)
    return "".join(out) if used == len(params) else sql


def db_query_view(step: TraceStep) -> DbQueryView:
    raw: Any = step.data.get("queries") or []
    return DbQueryView(title=step.title, queries=[DbQueryItem.model_validate(item) for item in raw])
