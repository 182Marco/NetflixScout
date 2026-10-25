"""Render the `wikipedia_calls` step: calls, searches, pages read, licence.

The content is built by the shared `presenters/wikipedia_view.py`, so the terminal and the web
show the same data; here only the terminal format.
"""
from __future__ import annotations

from turn import TraceStep

from ...wikipedia_view import wikipedia_calls_view
from .blocks import print_wikipedia_calls


def render_wikipedia_calls(step: TraceStep, language: str | None = None) -> None:
    print_wikipedia_calls(wikipedia_calls_view(step, language))
