"""Name normalisation, identical to the one the build stores in `entity_name.name_norm` (a test compares the two on real titles)."""
from __future__ import annotations

import re
import unicodedata


def normalize_name(text: str) -> str:
    """Lower-case, accent-free, punctuation-free form for matching; letters of every script are kept."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    out = []
    for ch in stripped.casefold():
        out.append(" " if unicodedata.category(ch)[0] in "PSZC" else ch)
    return " ".join("".join(out).split())


_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


def fts_query(text: str, *, max_tokens: int = 6) -> str | None:
    """A safe FTS5 expression for the title search: quoted tokens ANDed, the last one a prefix. Never raw user text."""
    tokens = _TOKEN.findall(normalize_name(text))[:max_tokens]
    if not tokens:
        return None
    parts = [f'"{t}"' for t in tokens[:-1]] + [f'"{tokens[-1]}"*']
    return " ".join(parts)
