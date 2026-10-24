"""Render the `youtube_calls` step: calls, searches, categories not searched, videos.

The content is built by the shared `presenters/youtube_view.py`, so the terminal and the web
show the same data; here only the terminal format.
"""
from __future__ import annotations

from turn import TraceStep

from ...youtube_view import youtube_calls_view
from .blocks import print_youtube_calls


def render_youtube_calls(step: TraceStep, language: str | None = None) -> None:
    print_youtube_calls(youtube_calls_view(step, language))
