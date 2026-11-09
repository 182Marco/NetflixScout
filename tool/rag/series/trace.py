"""The series step (wire name in `turn.STEP_SERIES_RAG`): what was searched and what came back. Outside `metadata` (which reaches the LLM prompt)."""
from __future__ import annotations

from typing import Any

from turn import STEP_SERIES_RAG


def build_series_rag_trace(*, level: str | None, query: str, items: list[dict[str, Any]], notes: dict[str, Any], status: str,
                             reason: str | None, engine: str, signals: dict[str, Any] | None, timings: dict[str, int]) -> list[dict[str, Any]]:
    return [{
        "kind": STEP_SERIES_RAG,
        "title": "Series search",
        "data": {"status": status, "reason": reason, "level": level, "query": query, "engine": engine, "items": items, "notes": notes,
                 "signals": signals or {}, "timings_ms": timings},
    }]
