"""Render the `db_query` step: only the SQL executed, no rows."""
from __future__ import annotations

from turn import TraceStep

from ...db_view import db_query_view
from .blocks import print_db_queries


def render_db_query(step: TraceStep, language: str | None = None) -> None:
    view = db_query_view(step)
    print_db_queries(view.title, [query.display_sql for query in view.queries], language or "it")
