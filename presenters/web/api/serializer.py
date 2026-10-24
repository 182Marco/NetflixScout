"""JSON-ready form of the `tmdb_calls` step for a future web response.

Wired into `payload.STEP_SERIALIZERS` (no FastAPI route exists yet). Same content as the terminal, from the shared view. A web frontend must keep the
`attributions` visible next to the answer.
"""
from __future__ import annotations

from typing import Any

from turn import TraceStep

from ...api_view import tmdb_calls_view


def serialize_tmdb_calls_step(step: TraceStep, language: str | None = None) -> dict[str, Any]:
    view = tmdb_calls_view(step, language)
    return {
        "kind": step.kind,
        "title": view.title,
        "calls": [{"label": view.called_label, "url": url} for url in view.calls],
        "attributions": [attribution.model_dump() for attribution in view.attributions],
    }
