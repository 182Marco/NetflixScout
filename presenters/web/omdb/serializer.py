"""JSON-ready form of the `omdb_calls` step. Same content as the terminal (shared view).

The frontend must name OMDb as the source (`source`) and show each score with what it measures
(`kind_label`), or `value` when OMDb has none, exactly as received.
"""
from __future__ import annotations

from typing import Any

from turn import TraceStep

from ...omdb_view import omdb_calls_view


def serialize_omdb_calls_step(step: TraceStep, language: str | None = None) -> dict[str, Any]:
    return {"kind": step.kind, **omdb_calls_view(step, language).model_dump(mode="json")}
