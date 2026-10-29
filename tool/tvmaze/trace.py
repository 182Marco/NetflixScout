"""Trace of a TVmaze run: calls made, series identified, what was read, alternatives and licence.

Kept outside `metadata` (which goes into the LLM prompt): the presenters show the source, the link to
the series page and the licence, never left to the model. Calls are the URLs actually sent.
"""
from __future__ import annotations

from typing import Any

from turn import STEP_TVMAZE_CALLS

from .settings import LICENSE_NAME, LICENSE_URL

TVMAZE_CALLS_TITLE = "TVmaze"


def build_tvmaze_trace(
    calls: list[dict[str, str]],
    *,
    status: str,
    reason: str | None = None,
    show: dict[str, Any] | None = None,
    facets: list[str] | None = None,
    candidates: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    data: dict[str, Any] = {
        "calls": list(calls),
        "status": status,
        "reason": reason,
        # {"name", "url", "status", "premiered", "network"} of the series identified.
        "show": dict(show) if show else None,
        "facets": list(facets or []),
        "candidates": [dict(row) for row in candidates or []],
        "license": {"name": LICENSE_NAME, "url": LICENSE_URL},
    }
    return [{"kind": STEP_TVMAZE_CALLS, "title": TVMAZE_CALLS_TITLE, "data": data}]
