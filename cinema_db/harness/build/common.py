"""Pure helpers of the build: name normalisation, Italian dates, wikipedia page titles. No I/O."""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import unquote

_MONTHS = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}
_DATE_FULL = re.compile(r"^(\d{1,2})\s*(?:º|°|o|ª)?\s+([a-zà-ù]+)\s+(\d{4})$")
_DATE_MONTH = re.compile(r"^([a-zà-ù]+)\s+(\d{4})$")
_YEAR = re.compile(r"^(\d{4})$")


def normalize_name(text: str) -> str:
    """Lower-case, accent-free, punctuation-free form for matching. Keeps letters of every script (a Japanese title stays)."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    out = []
    for ch in stripped.casefold():
        cat = unicodedata.category(ch)
        out.append(" " if cat[0] in "PSZC" else ch)
    return " ".join("".join(out).split())


def italian_date(text: str | None) -> str | None:
    """'23 marzo 2008' -> '2008-03-23', 'marzo 2008' -> '2008-03', '2008' -> '2008'. Anything else (ranges, notes) -> None."""
    if not text:
        return None
    t = " ".join(str(text).replace("\xa0", " ").strip().lower().split())
    t = re.sub(r"\s*\([^()]*\)$", "", t)  # "14 ottobre 2024 (Hulu)": a trailing note in brackets is not part of the date
    m = _DATE_FULL.match(t)
    if m and m.group(2) in _MONTHS and 1 <= int(m.group(1)) <= 31:
        return f"{m.group(3)}-{_MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"
    m = _DATE_MONTH.match(t)
    if m and m.group(1) in _MONTHS:
        return f"{m.group(2)}-{_MONTHS[m.group(1)]:02d}"
    m = _YEAR.match(t)
    return m.group(1) if m else None


def wikipedia_title(url: str | None) -> str | None:
    """Page title of an it.wikipedia.org URL (underscores kept as the wiki writes them, percent-decoding applied)."""
    if not url:
        return None
    m = re.match(r"^https?://it\.wikipedia\.org/wiki/(.+)$", url)
    return unquote(m.group(1)) if m else None


def year_ok(value: object) -> int | None:
    try:
        y = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return y if 1800 <= y <= 2100 else None
