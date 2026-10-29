"""JSON-ready form of the `tvmaze_calls` step. Same content as the terminal (shared view).

The frontend must name TVmaze as the source (`source`, which already carries the licence name), link the
series page (`show.url`) and the licence (`license.url`), and show every call (`calls`).
"""
from __future__ import annotations

from typing import Any

from turn import TraceStep

from ...tvmaze_view import tvmaze_calls_view


def serialize_tvmaze_calls_step(step: TraceStep, language: str | None = None) -> dict[str, Any]:
    return {"kind": step.kind, **tvmaze_calls_view(step, language).model_dump(mode="json")}
