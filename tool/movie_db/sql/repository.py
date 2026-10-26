"""Run a validated `MovieDbQuery` on a read-only connection. Never prints."""
from __future__ import annotations

import sqlite3
from typing import Any

from movie_db.config import QueryConfig

from ..models import ExecutedQuery, MovieDbQuery
from ..titles import normalize_title
from .queries import build_query


def effective_limit(query: MovieDbQuery, settings: QueryConfig) -> int:
    """Requested limit, or the default, always clamped to `max_limit`."""
    return max(1, min(query.limit or settings.default_limit, settings.max_limit))


def run_query(
    conn: sqlite3.Connection,
    query: MovieDbQuery,
    settings: QueryConfig,
    *,
    fetch_limit: int | None = None,
) -> tuple[list[ExecutedQuery], list[dict[str, Any]]]:
    """Return the statements executed (for the trace) and the rows (for the answer)."""
    limit = effective_limit(query, settings)
    # `fetch_limit` (>= limit) reads extra candidates for the caller to filter.
    fetch_limit = max(limit, min(fetch_limit or limit, settings.max_limit))
    executed = build_query(query, limit=fetch_limit, min_ratings=settings.min_ratings)
    # `execute` runs a single statement: multi-statement text is rejected by sqlite3.
    cursor = conn.execute(executed.sql, executed.params)
    rows = [dict(row) for row in cursor.fetchmany(fetch_limit or limit)]
    for row in rows:
        # Shown form only: the stored title is not touched.
        if row.get("title"):
            row["title"] = normalize_title(row["title"])
    return [executed], rows
