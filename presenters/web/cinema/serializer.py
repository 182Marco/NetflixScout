"""JSON-ready form of the `cinema_sql_calls` step. Same content as the terminal (shared view).

The frontend must show `source` (Wikipedia and Wikidata with their licences: the provenance of the DATA), link `subject.links[].url` (public pages) and each
`licenses[].url`, and list `candidates`, `counts`, `notes` (limits of the data) and `reason`. There is no `calls`: no HTTP request is made, `no_network` says so.
`queries` holds only the SQL queries really executed (rewritten text, bound values, `display_sql` with the values inlined for reading only, rows, ms): no planned query, no HTTP call.
"""
from __future__ import annotations

from typing import Any

from turn import TraceStep

from ...cinema_view import cinema_calls_view


def serialize_cinema_sql_calls_step(step: TraceStep, language: str | None = None) -> dict[str, Any]:
    return {"kind": step.kind, **cinema_calls_view(step, language).model_dump(mode="json")}
