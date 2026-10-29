"""JSON-ready form of the `wikidata_calls` step. Same content as the terminal (shared view).

The frontend must name Wikidata as the source (`source`, which already carries the licence name), link the
Wikidata page of the work and of each related work (`work.url`, `groups[].items[].url`, `candidates[].url`),
link the licence (`license.url`) and show every call (`calls`).
"""
from __future__ import annotations

from typing import Any

from turn import TraceStep

from ...wikidata_view import wikidata_calls_view


def serialize_wikidata_calls_step(step: TraceStep, language: str | None = None) -> dict[str, Any]:
    return {"kind": step.kind, **wikidata_calls_view(step, language).model_dump(mode="json")}
