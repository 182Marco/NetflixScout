"""Which series a title search identifies. Pure: no I/O.

Data is attributed only to a series identified without doubt: the name must be the requested
title (accents, case and punctuation ignored; an article is part of the title) and, when a year is
given, it must be the year of the premiere. Several series that fit are `ambiguous` and nothing is
guessed; series that only resemble the title are `unverified`.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any

from .settings import MAX_CANDIDATES

IDENTIFIED = "identified"
AMBIGUOUS = "ambiguous"
UNVERIFIED = "unverified"
NOT_FOUND = "not_found"


def normalize_title(text: Any) -> str:
    """Casefolded, accent-free, punctuation-free title ("&" reads "and"). The leading article is kept."""
    if not isinstance(text, str):
        return ""
    decomposed = unicodedata.normalize("NFKD", text.casefold().replace("&", " and "))
    kept = "".join(char if char.isalnum() else " " for char in decomposed if not unicodedata.combining(char))
    return " ".join(kept.split())


def premiere_year(show: dict[str, Any]) -> int | None:
    premiered = show.get("premiered")
    if isinstance(premiered, str) and len(premiered) >= 4 and premiered[:4].isdigit():
        return int(premiered[:4])
    return None


@dataclass(frozen=True)
class Identification:
    status: str
    show: dict[str, Any] | None = None
    candidates: list[dict[str, str]] = field(default_factory=list)


def _candidate(show: dict[str, Any]) -> dict[str, str]:
    network = show.get("network") if isinstance(show.get("network"), dict) else None
    web = show.get("webChannel") if isinstance(show.get("webChannel"), dict) else None
    channel = (network or web or {}).get("name")
    year = premiere_year(show)
    return {
        "name": str(show.get("name")),
        "year": str(year) if year else "",
        "channel": channel if isinstance(channel, str) else "",
        "id": str(show["id"]),
    }


def identify(results: Any, *, title: str, year: int | None) -> Identification:
    """Decide from the list answered by `/search/shows` (`[{"score", "show"}]`)."""
    seen: set[int] = set()
    usable: list[dict[str, Any]] = []
    for row in results if isinstance(results, list) else []:
        show = row.get("show") if isinstance(row, dict) else None
        if not isinstance(show, dict) or not isinstance(show.get("name"), str):
            continue
        show_id = show.get("id")
        if not isinstance(show_id, int) or isinstance(show_id, bool) or show_id in seen:
            continue
        seen.add(show_id)
        usable.append(show)
    if not usable:
        return Identification(NOT_FOUND)
    wanted = normalize_title(title)
    fits = [show for show in usable if normalize_title(show["name"]) == wanted]
    if year is not None:
        fits = [show for show in fits if premiere_year(show) == year]
    if len(fits) == 1:
        return Identification(IDENTIFIED, show=fits[0])
    if fits:
        return Identification(AMBIGUOUS, candidates=[_candidate(show) for show in fits[:MAX_CANDIDATES]])
    return Identification(UNVERIFIED, candidates=[_candidate(show) for show in usable[:MAX_CANDIDATES]])
