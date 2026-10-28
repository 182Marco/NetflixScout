"""Trace of an OMDb run: calls made, work identified, scores and alternatives.

Kept outside `metadata` (which goes into the LLM prompt): the presenters show the scores with
their meaning (audience or critics) and name OMDb as the source, never left to the model. The
key never appears (calls are display URLs).
"""
from __future__ import annotations

from typing import Any

from turn import STEP_OMDB_CALLS

OMDB_CALLS_TITLE = "OMDb"


def build_omdb_trace(
    calls: list[dict[str, str]],
    *,
    status: str,
    reason: str | None = None,
    title: str | None = None,
    year: str | None = None,
    work_type: str | None = None,
    imdb_id: str | None = None,
    ratings: list[dict[str, Any]] | None = None,
    candidates: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    data: dict[str, Any] = {
        "calls": list(calls),
        "status": status,
        "reason": reason,
        "title": title,
        "year": year,
        "type": work_type,
        "imdb_id": imdb_id,
        "ratings": [dict(row) for row in ratings or []],
        "candidates": [dict(row) for row in candidates or []],
    }
    return [{"kind": STEP_OMDB_CALLS, "title": OMDB_CALLS_TITLE, "data": data}]
