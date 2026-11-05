"""The trace step of the tool (outside `metadata`, so outside the final prompt): the statements really executed, as `db_query` does for MovieLens.

Nothing is rebuilt from a description: `sql` is the text the guard rewrote and ran, `params` are the bound values. The presenters that show this
step are part of wiring the tool in (not done yet): until then the step is only data.
"""
from __future__ import annotations

from typing import Any

from .constants import LICENSE_TEXT

KIND = "cinema_sql_calls"


def _subject(subject: dict[str, Any] | None) -> dict[str, Any] | None:
    if not subject:
        return None
    keep = ("kind", "work_id", "person_id", "company_id", "franchise_id", "title", "name", "year", "birth_year")
    return {k: subject[k] for k in keep if subject.get(k) is not None}


def build_trace(*, operation: str, status: str, reason: str | None, calls: list[dict[str, Any]], subject: dict[str, Any] | None, rows: int | None) -> list[dict[str, Any]]:
    if not calls:
        return []
    views = sorted({v for c in calls for v in c["views"]})
    return [{
        "kind": KIND,
        "title": "Local cinema database",
        "data": {
            "operation": operation, "status": status, "reason": reason, "queries": calls, "views": views, "subject": _subject(subject), "rows": rows,
            "elapsed_ms": sum(c["ms"] for c in calls), "license": LICENSE_TEXT,
        },
    }]
