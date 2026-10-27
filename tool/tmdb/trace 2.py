"""Trace of a TMDb run: the endpoints actually called and the sources to credit.

Kept outside `metadata` (which goes into the LLM prompt): attributions are shown to the
user by the presenters, never left to the model.
"""
from __future__ import annotations

from typing import Any

from turn import STEP_TMDB_CALLS

TMDB_CALLS_TITLE = "TMDb"


def build_tmdb_trace(calls: list[str], attributions: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "kind": STEP_TMDB_CALLS,
            "title": TMDB_CALLS_TITLE,
            "data": {"calls": list(calls), "attributions": list(attributions)},
        }
    ]
