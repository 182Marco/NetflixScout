"""Shared helpers of the A0 audit: paths, title normalisation, identifier normalisation, JSON output.

Pure and offline. Nothing here opens a network connection or writes outside the audit output folder.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Iterator

ROOT = Path(__file__).resolve().parents[3]

CINEMA_DB = ROOT / "cinema_db/data/cinema.sqlite3"
MOVIELENS_DB = ROOT / "movie_db/data/movielens32m.sqlite3"
FILM_DATA = ROOT / "pipelines/wikipedia_films/data"
SERIES_DATA = ROOT / "pipelines/wikipedia_series/data"
V3_CATALOG = FILM_DATA / "clean_v3/films.v3.jsonl"
CLEAN_CATALOG = FILM_DATA / "clean/films.clean.jsonl"
CANDIDATES = FILM_DATA / "processed/candidates.jsonl"
REJECTED = FILM_DATA / "processed/rejected.jsonl"
CLEAN_EXCLUDED = FILM_DATA / "clean/excluded.jsonl"
DUMP = FILM_DATA / "raw/itwiki-20261101-pages-articles.xml.bz2"
FILM_SNAPSHOT = FILM_DATA / "cache/wikidata/itwiki-20261101-a"
SERIES_SNAPSHOT = SERIES_DATA / "cache/wikidata/itwiki-20261101-series-a"
PHASE4_SNAPSHOT = ROOT / "cinema_db/data/wikidata_phase4"
S5 = SERIES_DATA / "s5"
OUT_DIR = ROOT / "cinema_db/data/audit_a0"
REPORT_MD = ROOT / "docs/cinema_db/PHASE9_A0_AUDIT.md"

TT = re.compile(r"^tt\d{7,9}$")
QID = re.compile(r"^Q[1-9]\d*$")

_ARTICLES = (
    "the", "a", "an", "la", "le", "les", "il", "lo", "l'", "i", "gli", "der", "die", "das", "den", "det",
    "el", "los", "las", "un", "une", "une", "de", "het", "os", "o",
)
_TRAILING_ARTICLE = re.compile(r"^(.*?),\s*(" + "|".join(re.escape(a) for a in _ARTICLES) + r")$", re.I)
_QUALIFIER = re.compile(r"\s*\((?:film|serie|miniserie|telefilm|cortometraggio|documentario|anime|(?:film\s+)?(?:\d{4}|[a-zà-ü ]+\s+\d{4})|\d{4}\s+film)[^)]*\)\s*$", re.I)


def ascii_fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def norm_title(text: str) -> str:
    """Comparable form of a title: folded, lower case, punctuation removed, trailing article moved to the front."""
    text = (text or "").strip()
    m = _TRAILING_ARTICLE.match(text)
    if m:
        text = f"{m.group(2)} {m.group(1)}"
    text = ascii_fold(text).lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def strip_qualifier(title: str) -> str:
    """Removes a Wikipedia disambiguation qualifier such as `(film)` or `(film 1999)`; keeps other parentheses."""
    return _QUALIFIER.sub("", title or "").strip()


def parse_movielens_title(raw: str) -> tuple[list[str], int | None]:
    """`City of Lost Children, The (Cité des enfants perdus, La) (1995)` -> ([names...], 1995)."""
    text = (raw or "").strip()
    year = None
    m = re.search(r"\((\d{4})\)\s*$", text)
    if m:
        year = int(m.group(1))
        text = text[: m.start()].strip()
    names: list[str] = []
    while True:
        m = re.search(r"\(([^()]*)\)\s*$", text)
        if not m or not text[: m.start()].strip():
            break
        names.append(m.group(1).strip())
        text = text[: m.start()].strip()
    names.append(text)
    names.reverse()
    return [n for n in names if n], year


def imdb_tt(value: Any) -> str | None:
    """`114709`, `0114709`, 114709 or `tt0114709` -> `tt0114709`; anything else -> None."""
    if value is None:
        return None
    text = str(value).strip()
    if TT.match(text):
        return text
    if text.isdigit() and 1 <= len(text) <= 9:
        return "tt" + text.zfill(7)
    return None


def open_ro(path: Path) -> sqlite3.Connection:
    """Read-only, immutable connection (never writes, never creates a journal)."""
    if not path.is_file():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    conn.execute("PRAGMA query_only = ON")
    return conn


def iter_jsonl(path: Path) -> Iterator[dict]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def fingerprint(path: Path, *, sha: bool = False) -> dict[str, Any]:
    st = path.stat()
    out: dict[str, Any] = {"path": str(path.relative_to(ROOT)), "bytes": st.st_size, "mtime": int(st.st_mtime)}
    if sha:
        h = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                h.update(chunk)
        out["sha256"] = h.hexdigest()
    return out


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    n = 0
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            n += 1
    tmp.replace(path)
    return n


def pct(part: int, whole: int) -> float:
    return round(100.0 * part / whole, 2) if whole else 0.0
