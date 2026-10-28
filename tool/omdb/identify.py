"""Which work a title search identifies. Pure: no I/O.

A score is attributed only to a work identified without doubt: the title must be the requested
one (accents, case and punctuation ignored; an article is part of the title) and, when a year is given, the
year must match. Several works that fit are `ambiguous` and nothing is guessed; works that only
resemble the title are `unverified`.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from .models import IMDB_ID
from .settings import MAX_CANDIDATES

IDENTIFIED = "identified"
AMBIGUOUS = "ambiguous"
UNVERIFIED = "unverified"
NOT_FOUND = "not_found"

_YEAR_SPAN = re.compile(r"^\s*(\d{4})\s*(?:([–—-])\s*(\d{4})?)?\s*$")


def normalize_title(text: Any) -> str:
    """Casefolded, accent-free, punctuation-free title ("&" reads "and"). The leading article is kept:
    "The Sinner" and "Sinner" can be different works, so they are not the same title here."""
    if not isinstance(text, str):
        return ""
    decomposed = unicodedata.normalize("NFKD", text.casefold().replace("&", " and "))
    kept = "".join(char if char.isalnum() else " " for char in decomposed if not unicodedata.combining(char))
    return " ".join(kept.split())


def year_matches(value: Any, year: int) -> bool:
    """`Year` of OMDb is "2010", "2008–2013" or "2019–" (running series)."""
    match = _YEAR_SPAN.match(value) if isinstance(value, str) else None
    if match is None:
        return False
    start = int(match.group(1))
    if match.group(2) is None:
        return start == year
    end = int(match.group(3)) if match.group(3) else None
    return start <= year and (end is None or year <= end)


@dataclass(frozen=True)
class Identification:
    status: str
    imdb_id: str | None = None
    title: str | None = None
    candidates: list[dict[str, str]] = field(default_factory=list)


def _candidate(row: dict[str, Any]) -> dict[str, str]:
    return {
        "title": str(row.get("Title")),
        "year": str(row.get("Year") or ""),
        "type": str(row.get("Type") or ""),
        "imdb_id": str(row["imdbID"]).lower(),
    }


def identify(results: Any, *, title: str, year: int | None, type: str | None) -> Identification:
    """Decide from the `Search` list of an `s=` answer."""
    seen: set[str] = set()
    usable: list[dict[str, Any]] = []
    for row in results if isinstance(results, list) else []:
        if not isinstance(row, dict) or not isinstance(row.get("Title"), str):
            continue
        imdb_id = row.get("imdbID")
        if not isinstance(imdb_id, str) or not IMDB_ID.match(imdb_id.lower()) or imdb_id.lower() in seen:
            continue
        # Episodes are not works the tool answers about.
        if row.get("Type") == "episode" or (type and row.get("Type") != type):
            continue
        seen.add(imdb_id.lower())
        usable.append(row)
    if not usable:
        return Identification(NOT_FOUND)
    wanted = normalize_title(title)
    fits = [row for row in usable if normalize_title(row["Title"]) == wanted]
    if year is not None:
        fits = [row for row in fits if year_matches(row.get("Year"), year)]
    if len(fits) == 1:
        found = _candidate(fits[0])
        return Identification(IDENTIFIED, imdb_id=found["imdb_id"], title=found["title"])
    if fits:
        return Identification(AMBIGUOUS, candidates=[_candidate(row) for row in fits[:MAX_CANDIDATES]])
    return Identification(UNVERIFIED, candidates=[_candidate(row) for row in usable[:MAX_CANDIDATES]])
