"""Render the `omdb_calls` step: calls, status, scores and alternatives.

The content is built by the shared `presenters/omdb_view.py`, so the terminal and the web show
the same data; here only the terminal format.
"""
from __future__ import annotations

from turn import TraceStep

from ...omdb_view import omdb_calls_view
from .blocks import print_omdb_calls


def render_omdb_calls(step: TraceStep, language: str | None = None) -> None:
    print_omdb_calls(omdb_calls_view(step, language))
