"""Render the `tmdb_calls` step: endpoints called and required attributions only."""
from __future__ import annotations

from turn import TraceStep

from ..view import tmdb_calls_view
from .blocks import print_tmdb_calls


def render_tmdb_calls(step: TraceStep, language: str | None = None) -> None:
    print_tmdb_calls(tmdb_calls_view(step, language))
