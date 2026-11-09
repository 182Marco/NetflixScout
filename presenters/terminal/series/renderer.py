"""Render the `series_index` step; the content is built by the shared `presenters/series_view.py`."""
from __future__ import annotations

from turn import TraceStep

from ...series_view import series_view
from .blocks import print_series


def render_series_rag(step: TraceStep, language: str | None = None) -> None:
    print_series(series_view(step, language))
