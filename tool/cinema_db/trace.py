"""The trace step of the tool (outside `metadata`, so outside the final prompt).

`queries` is what the guard really rewrote and ran (text, bound values, views, rows, ms): for tests and evaluations, never shown to the user, whom the
presenters give only the operation, the entity, the counts, the notes and the SOURCES of the data (Wikipedia and Wikidata, not the SQL engine).
`subject` carries the two public identifiers the presenters turn into links (`wikipedia_it`, `wikidata_id`): both are recorded in the database, none is built here.
"""
from __future__ import annotations

from typing import Any

from turn import STEP_CINEMA_SQL_CALLS

from .constants import LICENSE_TEXT

KIND = STEP_CINEMA_SQL_CALLS


def _subject(subject: dict[str, Any] | None) -> dict[str, Any] | None:
    if not subject:
        return None
    keep = ("kind", "work_id", "person_id", "company_id", "franchise_id", "title", "name", "year", "end_year", "birth_year", "wikipedia_it", "wikidata_id")
    return {k: subject[k] for k in keep if subject.get(k) is not None}


def _candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    keep = ("kind", "title", "name", "year", "end_year", "birth_year", "directors")
    return {k: candidate[k] for k in keep if candidate.get(k) not in (None, [])}


def build_trace(*, operation: str, status: str, reason: str | None, calls: list[dict[str, Any]], subject: dict[str, Any] | None, rows: int | None,
                candidates: list[dict[str, Any]] | None = None, omitted: int = 0, total: int | None = None, truncated: bool = False,
                notes: list[str] | None = None, reliability: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if not calls:
        return []
    views = sorted({v for c in calls for v in c["views"]})
    return [{
        "kind": KIND,
        "title": "Local cinema database",
        "data": {
            "operation": operation, "status": status, "reason": reason, "queries": calls, "queries_count": len(calls), "views": views, "subject": _subject(subject),
            "rows": rows, "total": total, "truncated": truncated, "candidates": [_candidate(c) for c in (candidates or [])], "candidates_omitted": omitted,
            "notes": list(notes or []), "reliability": {k: v["state"] for k, v in (reliability or {}).items()}, "elapsed_ms": sum(c["ms"] for c in calls), "license": LICENSE_TEXT,
        },
    }]
