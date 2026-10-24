"""Which references are accepted: only those the answer really presents.

A reference passes only if all hold: its key is in the index (a result of this turn's tools),
its `quote` is in the answer, the quote names the resource (title, original title; for a
video also its id), and no negation or comparison cue comes before that name in the quote.
Same-title records need the year in the quote. Each resource appears once in the turn.
The text checks are a guard, not proof: they do not understand meaning, so a comparison
without a cue word passes and a recommendation with "non" before the title is dropped.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from ..hydrate.item_key import ref_key
from ..schema.llm.list_ref import ItemRef, ListRef

_LEADING_ARTICLES = ("the ", "a ", "an ", "il ", "lo ", "la ", "i ", "gli ", "le ", "l ", "un ", "uno ", "una ")
# Normalized phrases (accents and punctuation removed) that turn a mention into a non-recommendation.
CUES = (
    "non", "tranne", "escluso", "esclusi", "invece di", "a differenza di", "rispetto a", "meglio di",
    "not", "unlike", "instead of", "except", "better than", "rather than",
)


def _norm(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.casefold().replace("&", " and "))
    kept = "".join(c if c.isalnum() else " " for c in folded if not unicodedata.combining(c))
    return " ".join(kept.split())


def _find(haystack: str, needle: str) -> int:
    """Position of `needle` as whole words in `haystack` (both normalized), or -1."""
    return f" {haystack} ".find(f" {needle} ") if needle else -1


def _name_forms(record: dict[str, Any]) -> list[str]:
    forms = []
    for title in (record.get("title"), record.get("original_title")):
        norm = _norm(title) if isinstance(title, str) else ""
        if norm:
            forms.append(norm)
            forms.extend(norm[len(a):] for a in _LEADING_ARTICLES if norm.startswith(a) and norm[len(a):])
    return forms


def _year(record: dict[str, Any]) -> str | None:
    match = re.match(r"\d{4}", str(record.get("release_date") or ""))
    return match.group() if match else None


def _shares_title(key: str, record: dict[str, Any], index: dict[str, dict[str, Any]]) -> bool:
    names = set(_name_forms(record))
    return any(k != key and names & set(_name_forms(other)) for k, other in index.items())


def _accepted(ref: ItemRef, answer: str, index: dict[str, dict[str, Any]]) -> bool:
    key = ref_key(ref)
    record = index.get(key)
    if record is None:
        return False
    quote = _norm(ref.quote)
    if not quote or _find(_norm(answer), quote) < 0:
        return False
    # What precedes the first mention of the resource (its name, or for a video its id).
    prefixes = [quote[:pos] for pos in (_find(quote, name) for name in _name_forms(record)) if pos >= 0]
    if ref.source == "youtube" and ref.video_id in ref.quote:
        prefixes.append(_norm(ref.quote[: ref.quote.index(ref.video_id)]))
    if not prefixes:
        return False
    if any(_find(min(prefixes, key=len), cue) >= 0 for cue in CUES):
        return False
    if _shares_title(key, record, index):
        year = _year(record)
        return year is not None and _find(quote, year) >= 0
    return True


def select_refs(lists: list[ListRef], answer: str, index: dict[str, dict[str, Any]]) -> list[ListRef]:
    seen: set[str] = set()
    selected = []
    for web_list in lists:
        kept = []
        for ref in web_list.items:
            key = ref_key(ref)
            if key not in seen and _accepted(ref, answer, index):
                seen.add(key)
                kept.append(ref)
        if kept:
            selected.append(web_list.model_copy(update={"items": kept}))
    return selected
