"""Title keys for the "same title and year" check, with Unicode letters preserved.

`audit.util.norm_title` is deliberately ASCII-only (it is the format already stored in the IMDb staging file, `title.pnorm/onorm`, and used by
many audited rules): a title written only in Japanese, Korean, Cyrillic... normalises to "" there. Used as a key, "" matched every other such
work of the same year (4,132 works) and held titles that had no real counterpart. These helpers give a second key that keeps the letters of
every script; an EMPTY key (a title made only of symbols) never matches anything.
"""
from __future__ import annotations

import unicodedata

from cinema_db.harness.audit import util


def norm_title_unicode(text: str | None) -> str:
    """Lower case, accent-free, punctuation-free, trailing article moved to the front; letters and digits of every script are kept."""
    text = (text or "").strip()
    m = util._TRAILING_ARTICLE.match(text)
    if m:
        text = f"{m.group(2)} {m.group(1)}"
    out = []
    for ch in text.replace("&", " and "):
        for piece in unicodedata.normalize("NFKC", ch):
            base = unicodedata.normalize("NFKD", piece)
            # accents are dropped only where the base letter is Latin, Greek or Cyrillic (e -> e); in Japanese, Korean, Thai... a mark changes the letter
            if len(base) > 1 and unicodedata.name(base[0], "").split(" ")[0] in ("LATIN", "GREEK", "CYRILLIC"):
                piece = "".join(c for c in base if not unicodedata.combining(c))
            for c in piece.casefold():
                out.append(c if unicodedata.category(c)[0] in "LNM" else " ")  # letters, numbers and the marks that complete a letter
    return " ".join("".join(out).split())


def title_keys(text: str | None) -> set[str]:
    """Every non-empty comparable form of a title: the historical ASCII one and the Unicode one."""
    return {k for k in (util.norm_title(text or ""), norm_title_unicode(text)) if k}


def person_key(name: str | None) -> str:
    return " ".join(sorted(norm_title_unicode(name).split()))
