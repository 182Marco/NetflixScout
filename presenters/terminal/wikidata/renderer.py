"""Render the `wikidata_calls` step: source and licence, calls, work found, relations, alternatives.

The content is built by the shared `presenters/wikidata_view.py`, so the terminal and the web show
the same data; here only the terminal format.
"""
from __future__ import annotations

from turn import TraceStep

from ...wikidata_view import wikidata_calls_view
from .blocks import print_wikidata_calls


def render_wikidata_calls(step: TraceStep, language: str | None = None) -> None:
    print_wikidata_calls(wikidata_calls_view(step, language))
