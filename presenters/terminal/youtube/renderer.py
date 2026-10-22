"""Render the `youtube_calls` step: calls, searches, categories not searched, videos.

Reads only `step.data` (like `terminal/rag/`): no import of the `youtube` package and no
tool logic. Only `https://` URLs are shown; anything malformed is skipped.
"""
from __future__ import annotations

from typing import Any

from turn import TraceStep

from .blocks import print_youtube_calls


def _rows(raw: Any) -> list[dict[str, Any]]:
    return [row for row in raw or [] if isinstance(row, dict)] if isinstance(raw, list) else []


def _https(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("https://")


def render_youtube_calls(step: TraceStep, language: str | None = None) -> None:
    data = step.data
    calls = data.get("calls")
    paused = data.get("quota_paused_until")
    print_youtube_calls(
        calls=[url for url in calls if _https(url)] if isinstance(calls, list) else [],
        searches=_rows(data.get("searches")),
        not_searched=_rows(data.get("not_searched")),
        videos=[video for video in _rows(data.get("videos")) if _https(video.get("url"))],
        quota_paused_until=paused if isinstance(paused, str) else None,
        language=language,
    )
