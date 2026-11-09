"""Streaming loaders of the IMDb bulk datasets into an AUDIT staging SQLite file (never the product database).

Each dataset is read once, line by line, from the read-only archive; only rows that matter are kept:
- `title`: every title of a screen type (movie, short, tvMovie, tvSpecial, tvShort, video, tvSeries, tvMiniSeries, tvPilot)
  plus any title of interest (cinema or MovieLens identifiers) whatever its type; per-type counters cover ALL rows.
- `crew`: directors/writers of the kept titles.
- `principal`: rows of the titles of interest only (the biggest dataset; filtered while streaming, integer sets).
- `name`: persons referenced by those principals and by the directors/writers of the titles of interest.
"""
from __future__ import annotations

import gzip
import io
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Iterable, Iterator

from . import util

NULL = "\\N"
SCREEN_TYPES = frozenset({"movie", "short", "tvMovie", "tvSpecial", "tvShort", "video", "tvSeries", "tvMiniSeries", "tvPilot"})
BATCH = 50_000

SCHEMA = """
CREATE TABLE title (tconst TEXT PRIMARY KEY, tid INTEGER, type TEXT, ptitle TEXT, otitle TEXT, adult INTEGER, start INTEGER,
                    end_year INTEGER, runtime INTEGER, genres TEXT, pnorm TEXT, onorm TEXT) WITHOUT ROWID;
CREATE TABLE crew (tconst TEXT PRIMARY KEY, directors TEXT, writers TEXT) WITHOUT ROWID;
CREATE TABLE principal (tconst TEXT, ordering INTEGER, nconst TEXT, category TEXT, job TEXT, characters TEXT,
                        PRIMARY KEY (tconst, ordering)) WITHOUT ROWID;
CREATE TABLE name (nconst TEXT PRIMARY KEY, name TEXT, birth INTEGER, death INTEGER, professions TEXT, nnorm TEXT) WITHOUT ROWID;
CREATE TABLE episode (tconst TEXT PRIMARY KEY, parent TEXT, season INTEGER, number INTEGER) WITHOUT ROWID;
CREATE TABLE rating (tconst TEXT PRIMARY KEY, average REAL, votes INTEGER) WITHOUT ROWID;
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""


def tid(tconst: str) -> int | None:
    return int(tconst[2:]) if tconst.startswith("tt") and tconst[2:].isdigit() else None


def nid(nconst: str) -> int | None:
    return int(nconst[2:]) if nconst.startswith("nm") and nconst[2:].isdigit() else None


def opt(value: str) -> str | None:
    return None if value == NULL or value == "" else value


def opt_int(value: str) -> int | None:
    return int(value) if value.isdigit() else None


def rows(path: Path) -> Iterator[list[str]]:
    """Rows of a gzip TSV (header skipped), split on tabs. No quoting rules: IMDb files do not use them."""
    with gzip.open(path, "rb") as raw:
        handle = io.TextIOWrapper(raw, encoding="utf-8", newline="\n", errors="replace")
        handle.readline()
        for line in handle:
            yield line.rstrip("\n").split("\t")


def person_norm(name: str) -> str:
    return " ".join(sorted(util.norm_title(name).split()))


def _flush(conn: sqlite3.Connection, sql: str, batch: list) -> None:
    if batch:
        conn.executemany(sql, batch)
        batch.clear()


def stage_episodes(path: Path, conn: sqlite3.Connection, parents: set[int]) -> tuple[dict, set[int]]:
    """Episodes of the given series (their own identifiers are returned so `stage_basics` keeps their titles)."""
    batch: list = []
    total = kept = 0
    episode_ids: set[int] = set()
    for r in rows(path):
        total += 1
        if tid(r[1]) in parents:
            kept += 1
            episode_ids.add(tid(r[0]))
            batch.append((r[0], r[1], opt_int(r[2]), opt_int(r[3])))
            if len(batch) >= BATCH:
                _flush(conn, "INSERT INTO episode VALUES (?,?,?,?)", batch)
    _flush(conn, "INSERT INTO episode VALUES (?,?,?,?)", batch)
    conn.commit()
    return {"rows": total, "kept": kept}, episode_ids


def stage_ratings(path: Path, conn: sqlite3.Connection, keep: set[int]) -> dict:
    batch: list = []
    total = kept = 0
    for r in rows(path):
        total += 1
        if tid(r[0]) in keep:
            kept += 1
            batch.append((r[0], float(r[1]), int(r[2])))
            if len(batch) >= BATCH:
                _flush(conn, "INSERT INTO rating VALUES (?,?,?)", batch)
    _flush(conn, "INSERT INTO rating VALUES (?,?,?)", batch)
    conn.commit()
    return {"rows": total, "kept": kept}


def stage_basics(path: Path, conn: sqlite3.Connection, interest: set[int]) -> dict:
    counters: Counter[str] = Counter()
    adult: Counter[str] = Counter()
    batch: list = []
    kept = 0
    for r in rows(path):
        t = r[1]
        counters[t] += 1
        adult[t] += r[4] == "1"
        n = tid(r[0])
        if t in SCREEN_TYPES or n in interest:
            batch.append((r[0], n, t, r[2], r[3], int(r[4]) if r[4] in "01" else None, opt_int(r[5]), opt_int(r[6]), opt_int(r[7]),
                          opt(r[8]), util.norm_title(r[2]), util.norm_title(r[3])))
            kept += 1
            if len(batch) >= BATCH:
                _flush(conn, "INSERT INTO title VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", batch)
    _flush(conn, "INSERT INTO title VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", batch)
    conn.commit()
    return {"rows": sum(counters.values()), "kept": kept, "by_type": dict(counters.most_common()), "adult_by_type": dict(adult)}


def stage_crew(path: Path, conn: sqlite3.Connection, keep: set[int]) -> dict:
    batch: list = []
    total = kept = 0
    for r in rows(path):
        total += 1
        n = tid(r[0])
        if n in keep:
            batch.append((r[0], opt(r[1]), opt(r[2])))
            kept += 1
            if len(batch) >= BATCH:
                _flush(conn, "INSERT INTO crew VALUES (?,?,?)", batch)
    _flush(conn, "INSERT INTO crew VALUES (?,?,?)", batch)
    conn.commit()
    return {"rows": total, "kept": kept}


def stage_principals(path: Path, conn: sqlite3.Connection, interest: set[int]) -> dict:
    batch: list = []
    total = kept = 0
    categories: Counter[str] = Counter()
    for r in rows(path):
        total += 1
        n = tid(r[0])
        if n in interest:
            kept += 1
            categories[r[3]] += 1
            batch.append((r[0], int(r[1]), r[2], r[3], opt(r[4]), opt(r[5])))
            if len(batch) >= BATCH:
                _flush(conn, "INSERT INTO principal VALUES (?,?,?,?,?,?)", batch)
    _flush(conn, "INSERT INTO principal VALUES (?,?,?,?,?,?)", batch)
    conn.commit()
    return {"rows": total, "kept": kept, "categories_kept": dict(categories.most_common())}


def needed_people(conn: sqlite3.Connection, titles: set[int]) -> set[int]:
    people: set[int] = set()
    for (n,) in conn.execute("SELECT nconst FROM principal"):
        v = nid(n)
        if v is not None:
            people.add(v)
    for t, d, w in conn.execute("SELECT tconst, directors, writers FROM crew"):
        if tid(t) in titles:
            for field in (d, w):
                for n in (field or "").split(","):
                    v = nid(n)
                    if v is not None:
                        people.add(v)
    return people


def stage_names(path: Path, conn: sqlite3.Connection, keep: set[int]) -> dict:
    batch: list = []
    total = kept = 0
    for r in rows(path):
        total += 1
        n = nid(r[0])
        if n in keep:
            batch.append((r[0], r[1], opt_int(r[2]), opt_int(r[3]), opt(r[4]), person_norm(r[1])))
            kept += 1
            if len(batch) >= BATCH:
                _flush(conn, "INSERT INTO name VALUES (?,?,?,?,?,?)", batch)
    _flush(conn, "INSERT INTO name VALUES (?,?,?,?,?,?)", batch)
    conn.commit()
    return {"rows": total, "kept": kept}


def create_staging(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute("PRAGMA journal_mode = OFF")
    conn.execute("PRAGMA synchronous = OFF")
    return conn


def split_ids(field: str | None) -> list[str]:
    return [x for x in (field or "").split(",") if x]


def parse_characters(raw: str | None) -> list[str]:
    """`["Tyler Durden","Narrator"]` -> list. IMDb writes a JSON-like array; anything unparsable gives []."""
    if not raw:
        return []
    import json
    try:
        value = json.loads(raw)
    except ValueError:
        return []
    return [c.strip() for c in value if isinstance(c, str) and c.strip()] if isinstance(value, list) else []
