"""Trace of a Wikidata run: calls made, work identified, relations read, alternatives and licence.

Kept outside `metadata` (which goes into the LLM prompt): the presenters show the source, the link to
the Wikidata page of each work and the licence, never left to the model. Calls are the URLs actually
sent (the SPARQL text is part of the URL, as sent).
"""
from __future__ import annotations

from typing import Any

from turn import STEP_WIKIDATA_CALLS

from .normalize import entity_url
from .settings import LICENSE_NAME, LICENSE_URL

WIKIDATA_CALLS_TITLE = "Wikidata"


def _page(row: dict[str, Any]) -> dict[str, Any]:
    """A work as the presenters show it: title, year, kind and the link to its Wikidata page."""
    return {
        "title": row.get("title"),
        "year": row.get("year"),
        "kind": row.get("kind"),
        "url": entity_url(row["id"]) if isinstance(row.get("id"), str) else None,
    }


def build_wikidata_trace(
    calls: list[dict[str, str]],
    *,
    status: str,
    reason: str | None = None,
    operation: str | None = None,
    work: dict[str, Any] | None = None,
    relations: dict[str, list[dict[str, Any]]] | None = None,
    franchises: list[dict[str, Any]] | None = None,
    candidates: list[dict[str, Any]] | None = None,
    unavailable: dict[str, str] | None = None,
    candidates_omitted: int = 0,
    incomplete: bool = False,
) -> list[dict[str, Any]]:
    data: dict[str, Any] = {
        "calls": list(calls),
        "status": status,
        "reason": reason,
        "operation": operation,
        # {"title", "year", "kind", "url", "imdb_id", "tmdb_id"} of the work identified.
        "work": {**_page(work), "imdb_id": work.get("imdb_id"), "tmdb_id": work.get("tmdb_id")} if work else None,
        # group -> works, each {"title", "year", "kind", "url"}.
        "relations": {name: [_page(row) for row in rows] for name, rows in (relations or {}).items()},
        "franchises": [
            {**_page(row), "works": [_page(member) for member in row.get("members", [])], "omitted": row.get("omitted", 0)}
            for row in franchises or []
        ],
        "candidates": [
            {**_page(row), "directors": list(row.get("directors") or []), "imdb_id": row.get("imdb_id"), "tmdb_id": row.get("tmdb_id")}
            for row in candidates or []
        ],
        # Alternatives found but not listed; True when the list searched was cut at its limit.
        "candidates_omitted": candidates_omitted,
        "incomplete": incomplete,
        "unavailable": dict(unavailable or {}),
        "license": {"name": LICENSE_NAME, "url": LICENSE_URL},
    }
    return [{"kind": STEP_WIKIDATA_CALLS, "title": WIKIDATA_CALLS_TITLE, "data": data}]
