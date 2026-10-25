"""JSON-ready form of the `wikipedia_calls` step. Same content as the terminal (shared view).

The frontend must show the page titles, languages and links as they are, the `source` line and
the licence with its link (CC BY-SA asks for credit to the pages, the licence and a note that the
text was reworked).
"""
from __future__ import annotations

from typing import Any

from turn import TraceStep

from ...wikipedia_view import wikipedia_calls_view


def serialize_wikipedia_calls_step(step: TraceStep, language: str | None = None) -> dict[str, Any]:
    return {"kind": step.kind, **wikipedia_calls_view(step, language).model_dump(mode="json")}
