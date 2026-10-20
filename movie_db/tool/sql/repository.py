"""Run a validated `MovieDbQuery` on a read-only connection. Never prints."""
from __future__ import annotations

import sqlite3
from typing import Any

from movie_db.config import QueryConfig

from ..models import ExecutedQuery, MovieDbQuery
from .queries import build_query


def effective_limit(query: MovieDbQuery, settings: QueryConfig) -> int:
    """Requested limit, or the default, always clamped to `max_limit`."""
    return max(1, min(query.limit or settings.default_limit, settings.max_limit))


def run_query(
    conn: sqlite3.Connection,
    query: MovieDbQuery,
    settings: QueryConfig,
) -> tuple[list[ExecutedQuery], list[dict[str, Any]]]:
    """Return the statements executed (for the trace) and the rows (for the answer)."""
    limit = effective_limit(query, settings)
    executed = build_query(query, limit=limit, min_ratings=settings.min_ratings)
    # `execute` runs a single statement: multi-statement text is rejected by sqlite3.
    cursor = conn.execute(executed.sql, executed.params)
    rows = [dict(row) for row in cursor.fetchmany(limit)]
    return [executed], rows
