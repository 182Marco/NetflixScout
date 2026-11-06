"""Render the `cinema_sql_calls` step: operation, entity found with its public links, counts, limits of the data, sources and licences.

The content is built by the shared `presenters/cinema_view.py`, so the terminal and the web show the same data; here only the terminal format.
"""
from __future__ import annotations

from turn import TraceStep

from ...cinema_view import cinema_calls_view
from .blocks import print_cinema_calls


def render_cinema_sql_calls(step: TraceStep, language: str | None = None) -> None:
    print_cinema_calls(cinema_calls_view(step, language))
