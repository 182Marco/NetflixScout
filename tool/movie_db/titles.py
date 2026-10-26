"""Pure helpers for MovieLens titles. The stored data is never modified.

MovieLens writes a leading article at the end ("Matrix, The"). The ingestion already moves it
when the title is plain; with an alternative title in brackets it stays at the end
("Kingdom II, The (Riget II)"). These functions read both forms the same way.
"""
from __future__ import annotations

import re

# Same articles as `movie_db/harness/ingestion/load_csv.py`, kept here because the runtime tool
# never imports the harness.
_ARTICLES = "The|A|An|La|Le|Les|L'|Il|Lo|El|Los|Las|Das|Der|Die"
_TRAILING = re.compile(rf"^(?P<body>.+?), (?P<article>{_ARTICLES})(?P<rest>\s+\(.*\))?$")
_LEADING = re.compile(rf"^(?P<article>{_ARTICLES})(?:\s+|(?<=')(?=\S))(?P<body>.+)$", re.IGNORECASE)
_BRACKET = re.compile(r"\(([^()]*)\)")


def _move_article(text: str) -> str:
    match = _TRAILING.match(text)
    if not match:
        return text
    article = match.group("article")
    separator = "" if article.endswith("'") else " "
    return f"{article}{separator}{match.group('body')}{match.group('rest') or ''}"


def normalize_title(title: str) -> str:
    """"Matrix, The" → "The Matrix"; "Kingdom II, The (Riget II)" → "The Kingdom II (Riget II)".

    The article inside a bracketed alternative title is moved too ("(Cité, La)" → "(La Cité)").
    Titles without a trailing article are returned unchanged.
    """
    text = " ".join(title.split())
    text = _move_article(text)
    return _BRACKET.sub(lambda m: f"({_move_article(m.group(1))})", text)


def stored_form(title: str) -> str | None:
    """Inverse of `normalize_title` for the main title: "The Matrix" → "Matrix, The".

    None when the title does not start with an article (nothing to look up in the stored form).
    """
    text = " ".join(title.split())
    match = _LEADING.match(text)
    if not match:
        return None
    article = match.group("article")
    return f"{match.group('body')}, {article}"


def title_key(title: str) -> str:
    """Comparison key: normalized, case-folded, whitespace collapsed."""
    return normalize_title(title).casefold()
