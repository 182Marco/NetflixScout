"""JSON-ready form of the `youtube_calls` step. Same content as the terminal (shared view).

The frontend must name YouTube as the source (`source`), show titles, channels and URLs as
they are.
"""
from __future__ import annotations

from typing import Any

from turn import TraceStep

from ...youtube_view import youtube_calls_view


def serialize_youtube_calls_step(step: TraceStep, language: str | None = None) -> dict[str, Any]:
    return {"kind": step.kind, **youtube_calls_view(step, language).model_dump(mode="json")}
