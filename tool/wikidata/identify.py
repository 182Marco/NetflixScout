"""Which work a search or an external id identifies. Pure: no I/O.

Data is attributed only to a work identified without doubt. With a title: the title (or an alias the
search matched) must be the requested one (accents, case and punctuation ignored; an article is part
of the title) and, when given, the year must be one of the dates Wikidata records and the director one
of the directors it records; a missing date or director is NOT a match, so nothing is guessed. Several
works that fit are `ambiguous`, works that only resemble the title are `unverified`. With an IMDb or
TMDb id the id is the identity. Announced projects and works not yet released are never candidates. A single
fit in a list that was cut at its limit is not certain either: it is returned as the only alternative
(`incomplete`), because another work of the same title may be past the cut.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .normalize import Item, work_view
from .settings import MAX_CANDIDATES

IDENTIFIED = "identified"
AMBIGUOUS = "ambiguous"
UNVERIFIED = "unverified"
NOT_FOUND = "not_found"

_KINDS = {"movie": {"film"}, "tv": {"series"}, None: {"film", "series"}}


def normalize_title(text: Any) -> str:
    """Casefolded, accent-free, punctuation-free title ("&" reads "and"). The leading article is kept."""
    if not isinstance(text, str):
        return ""
    decomposed = unicodedata.normalize("NFKD", text.casefold().replace("&", " and "))
    kept = "".join(char if char.isalnum() else " " for char in decomposed if not unicodedata.combining(char))
    return " ".join(kept.split())


def parse_search(payload: Any) -> list[dict[str, Any]]:
    """Rows of `wbsearchentities`, in the order of the answer: id plus the texts the search matched."""
    rows = payload.get("search") if isinstance(payload, dict) else None
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            continue
        match = row.get("match") if isinstance(row.get("match"), dict) else {}
        texts = [value for value in (row.get("label"), match.get("text")) if isinstance(value, str)]
        out.append({"id": row["id"], "texts": texts})
    return out


@dataclass(frozen=True)
class Identification:
    status: str
    work: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    excluded_unreleased: int = 0
    # True when the only fit was not accepted because the list searched may not contain every work of that title.
    incomplete: bool = False
    # Alternatives found but not listed (only MAX_CANDIDATES are): the list shown is partial by this many.
    omitted: int = 0


def _director_fits(wanted: str, item: Item) -> bool:
    tokens = set(normalize_title(wanted).split())
    return bool(tokens) and any(tokens <= set(normalize_title(name).split()) for name in item.directors)


def identify(
    items: dict[str, Item],
    *,
    today: date,
    media: str | None,
    search: list[dict[str, Any]] | None = None,
    title: str | None = None,
    year: int | None = None,
    director: str | None = None,
    complete: bool = True,
) -> Identification:
    """Decide among `items` (the details of the searched entities, or of the item an external id names).

    `complete` is False when the list searched was cut at its limit: then a single fit is not enough to be sure it
    is the only work of that title, so it is returned as the one alternative and not as the work identified.
    """
    order = {row["id"]: position for position, row in enumerate(search or [])}
    kinds = _KINDS[media]
    released, unreleased = [], 0
    for item in sorted(items.values(), key=lambda it: order.get(it.id, len(order))):
        if item.kind not in kinds or not item.labelled:
            continue
        if item.unreleased(today):
            unreleased += 1
            continue
        released.append(item)
    if not released:
        return Identification(NOT_FOUND, excluded_unreleased=unreleased)

    if search is None:  # an external id: the id is the identity
        fits = released
    else:
        texts = {row["id"]: {normalize_title(text) for text in row["texts"]} for row in search}
        wanted = normalize_title(title)
        fits = [it for it in released if wanted in texts.get(it.id, set()) | {normalize_title(it.label)}]
        if year is not None:
            fits = [it for it in fits if year in {d.year for d in it.dates}]
        if director is not None:
            fits = [it for it in fits if _director_fits(director, it)]
    if len(fits) == 1 and complete:
        return Identification(IDENTIFIED, work=work_view(fits[0]), excluded_unreleased=unreleased)
    if len(fits) == 1:
        return Identification(AMBIGUOUS, candidates=[work_view(fits[0])], excluded_unreleased=unreleased, incomplete=True)
    shown = fits if fits else released
    ordered = sorted(shown, key=lambda it: (it.year or 9999, it.label or ""))
    return Identification(
        AMBIGUOUS if fits else UNVERIFIED,
        candidates=[work_view(it) for it in ordered[:MAX_CANDIDATES]],
        excluded_unreleased=unreleased,
        omitted=max(len(ordered) - MAX_CANDIDATES, 0),
    )
