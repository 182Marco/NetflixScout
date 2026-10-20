"""JSON-ready form of the `db_query` step for the future FastAPI response.

Not wired into `payload.to_payload` yet (still `NotImplementedError`). Same content as
the terminal output, from the shared `movie_db_view`: only the SQL executed.
"""
from __future__ import annotations

from typing import Any

from turn import TraceStep

from ...movie_db_view import db_query_view


def serialize_db_query_step(step: TraceStep) -> dict[str, Any]:
    view = db_query_view(step)
    return {
        "kind": step.kind,
        "title": view.title,
        "queries": [
            {"sql": query.sql, "params": query.params, "display_sql": query.display_sql}
            for query in view.queries
        ],
    }
