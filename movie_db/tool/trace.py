"""Trace of a movie DB tool run: only the SQL statements executed.

Rows, limits and guard settings stay out on purpose, to keep the report short.
Same shape as `turn.TraceStep`; `handle_query` turns it into one.
"""
from __future__ import annotations

from typing import Any

from turn import STEP_DB_QUERY

from .models import ExecutedQuery

DB_QUERY_TITLE = "Query DB"


def build_db_query_trace(executed: list[ExecutedQuery]) -> list[dict[str, Any]]:
    return [
        {
            "kind": STEP_DB_QUERY,
            "title": DB_QUERY_TITLE,
            "data": {"queries": [query.model_dump(mode="json") for query in executed]},
        }
    ]
