"""Decisions about search results: which pages are kept and how sure the match is.

Permissive, like the YouTube filter: a page is dropped only with strong proof (disambiguation
page, no text); everything else is kept and labelled `confirmed` or `to_verify`. Pure functions.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from .models import PageHit, Subject, WikipediaToolInput, normalize_text

_QUALIFIER = re.compile(r"\s*\(([^()]*)\)\s*$")
_YEAR = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")
_ARTICLES = ("the ", "a ", "an ", "il ", "lo ", "la ", "i ", "gli ", "le ", "l ", "un ", "uno ", "una ")

# Notes that make a page `to_verify`.
TO_VERIFY_NOTES = frozenset({"title_partial", "title_differs", "year_conflict"})


class Screened(BaseModel):
    page: PageHit
    verification: str
    notes: list[str] = Field(default_factory=list)


def _without_article(text: str) -> str:
    return next((text[len(a):] for a in _ARTICLES if text.startswith(a) and text[len(a):]), text)


def strip_qualifier(title: str) -> tuple[str, str | None]:
    """`("Parasite", "film 2019")` for "Parasite (film 2019)"; the qualifier is None without one."""
    match = _QUALIFIER.search(title)
    return (title[: match.start()], match.group(1)) if match else (title, None)


def match_title(topic: str, title: str) -> str:
    """`exact`, `qualified` (same name plus a parenthetical), `partial` or `differs`."""
    wanted = _without_article(normalize_text(topic))
    base, qualifier = strip_qualifier(title)
    name = _without_article(normalize_text(base))
    if not wanted or not name:
        return "differs"
    if name == wanted:
        return "qualified" if qualifier else "exact"
    wanted_words, name_words = set(wanted.split()), set(name.split())
    return "partial" if wanted_words <= name_words or name_words <= wanted_words else "differs"


def verification(notes: list[str]) -> str:
    return "to_verify" if any(note in TO_VERIFY_NOTES for note in notes) else "confirmed"


def _notes(request: WikipediaToolInput, page: PageHit) -> list[str]:
    match = match_title(request.topic, page.title)
    notes = {"partial": ["title_partial"], "differs": ["title_differs"]}.get(match, [])
    if request.kind is Subject.film and request.year is not None and match in ("exact", "qualified"):
        _, qualifier = strip_qualifier(page.title)
        years = [int(year) for year in _YEAR.findall(qualifier or "")]
        if years and request.year not in years:
            notes = [*notes, "year_conflict"]
    return notes


def screen_pages(request: WikipediaToolInput, pages: list[PageHit]) -> tuple[list[Screened], dict[str, int]]:
    """Kept pages (confirmed first, search order inside each group) and the count of dropped ones."""
    kept: list[Screened] = []
    dropped: dict[str, int] = {}
    for page in sorted(pages, key=lambda hit: hit.index):
        reason = "disambiguation" if page.disambiguation else ("empty_extract" if not page.extract.strip() else None)
        if reason:
            dropped[reason] = dropped.get(reason, 0) + 1
            continue
        notes = _notes(request, page)
        kept.append(Screened(page=page, verification=verification(notes), notes=notes))
    kept.sort(key=lambda row: row.verification != "confirmed")
    return kept, dropped


def lookup_hints(request: WikipediaToolInput, kept: list[Screened], dropped: dict[str, int]) -> list[str]:
    """What the user could add to get surer results; never a value the tool made up."""
    hints = []
    unsure = len(kept) > 1 or any(row.verification == "to_verify" for row in kept) or "disambiguation" in dropped
    if request.kind is Subject.film and request.year is None and unsure:
        hints.append("specify_year")
    if not kept and "disambiguation" in dropped:
        hints.append("add_context")
    return hints
