"""JSON-ready form of the `series_index` step. Same content as the terminal (shared view).

The frontend must show `source`, each `results[]` with its `label` and, when present, the public Wikipedia `url`, the `notes` (limits and failures), the
`status_label`/`reason`, and the licence (`license_name` linking `license_url`). There is no `calls`: no HTTP request to a third party is made.
"""
from __future__ import annotations

from typing import Any

from turn import TraceStep

from ...series_view import series_view


def serialize_series_rag_step(step: TraceStep, language: str | None = None) -> dict[str, Any]:
    return {"kind": step.kind, **series_view(step, language).model_dump(mode="json")}
