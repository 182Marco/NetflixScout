"""Small helpers shared by the normalizers."""
from __future__ import annotations

import unicodedata
from typing import Any

from ..settings import IMAGE_BASE_URL, IMAGE_SIZE


def clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return " ".join(value.split()) or None


def truncate(text: str | None, limit: int) -> str | None:
    """Cut at a sentence boundary when possible, marking the cut with an ellipsis."""
    if text is None or len(text) <= limit:
        return text
    cut = text[: limit - 1]
    boundary = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if boundary >= limit // 2:
        return cut[: boundary + 1] + " …"
    return cut.rstrip() + "…"


def year_of(date: Any) -> int | None:
    if isinstance(date, str) and len(date) >= 4 and date[:4].isdigit():
        return int(date[:4])
    return None


def image_url(path: Any, size: str = IMAGE_SIZE) -> str | None:
    if isinstance(path, str) and path.startswith("/"):
        return f"{IMAGE_BASE_URL}{size}{path}"
    return None


def language_code(api_language: str) -> str:
    return api_language.split("-")[0]


def localized(
    data: dict[str, Any],
    field: str,
    *,
    api_language: str,
    original_language: str | None,
) -> tuple[str | None, str | None]:
    """Localized value of `field`, or a fallback from the appended `translations`.

    Returns (value, fallback language). The fallback language is None when the value is
    in the requested language. Order: requested language → English → original language.
    """
    value = clean_text(data.get(field))
    if value:
        return value, None
    translations = (data.get("translations") or {}).get("translations") or []
    requested = language_code(api_language)
    for code in dict.fromkeys(("en", original_language)):
        if not code or code == requested:
            continue
        for translation in translations:
            if translation.get("iso_639_1") != code:
                continue
            candidate = clean_text((translation.get("data") or {}).get(field))
            if candidate:
                return candidate, code
    return None, None


def names(items: Any, key: str = "name", limit: int | None = None) -> list[str]:
    values = [clean_text(item.get(key)) for item in items or [] if isinstance(item, dict)]
    values = [value for value in values if value]
    return values[:limit] if limit is not None else values


def normalize_name(text: Any) -> str:
    """Casefolded, accent-free, punctuation-free form used to compare names ("&" reads "and")."""
    if not isinstance(text, str):
        return ""
    decomposed = unicodedata.normalize("NFKD", text.casefold().replace("&", " and "))
    kept = "".join(char if char.isalnum() else " " for char in decomposed if not unicodedata.combining(char))
    return " ".join(kept.split())


def strict_name(text: Any) -> str:
    """Casefolded, punctuation-free form that keeps accents: "Dűne" and "Dune" differ."""
    if not isinstance(text, str):
        return ""
    composed = unicodedata.normalize("NFKC", text.casefold().replace("&", " and "))
    kept = "".join(char if char.isalnum() or unicodedata.combining(char) else " " for char in composed)
    return " ".join(kept.split())


def positive_minutes(value: Any) -> int | None:
    """A runtime in minutes, or None: TMDb uses 0 (and sometimes null) for "unknown"."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value) if value > 0 else None


# Leading articles that titles gain or lose between catalogs ("The Dungeon of Harrow").
LEADING_ARTICLES = frozenset({
    "the", "a", "an", "il", "lo", "la", "i", "gli", "le", "l", "un", "una", "uno",
    "der", "die", "das", "les", "el", "los", "las",
})


def article_free_name(text: Any) -> str:
    """`normalize_name` without one leading article; never empties a one-word title."""
    words = normalize_name(text).split()
    if len(words) > 1 and words[0] in LEADING_ARTICLES:
        words = words[1:]
    return " ".join(words)
