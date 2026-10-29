"""Render the `tvmaze_calls` step: source and licence, calls, series found, what was read.

The content is built by the shared `presenters/tvmaze_view.py`, so the terminal and the web show
the same data; here only the terminal format.
"""
from __future__ import annotations

from turn import TraceStep

from ...tvmaze_view import tvmaze_calls_view
from .blocks import print_tvmaze_calls


def render_tvmaze_calls(step: TraceStep, language: str | None = None) -> None:
    print_tvmaze_calls(tvmaze_calls_view(step, language))
