"""MovieLens layer of the v4 file: every MovieLens film, its genres and its tags, tied to the catalogue works, with a verifiable reason for each film left out.

Runs inside `imdb_layer.Layer` after the episodes are imported (the id -> work map is read from the database, NOT from the early dictionaries: that is
what lost 174 films whose IMDb episode ids were attached later). Rules, all decided by the owner on 2026-11-09:
- a film becomes a work's MovieLens film ONLY through the IMDb id MovieLens gives; never by title (`ml_movie.work_id`), one film per work;
- a film whose id belongs to an EPISODE counts only if MovieLens' own title and year agree with the IMDb record of that id (`RR.movielens_confirms_identity`);
- films that did not enter the catalogue keep the reason the entry rule gave (`not_entered` archive) or a reason of this module; none is invented;
- genres are MovieLens' own (`ml_genre`), tags are aggregated by (work, tag) as the number of DISTINCT users; no user, no date.
"""
from __future__ import annotations

import collections
from datetime import datetime, timezone
from typing import Any

from cinema_db import schema_v3 as V3
from cinema_db.harness.audit import util
from cinema_db.harness.build import reconcile_rules as RR
from cinema_db.harness.build.common import normalize_name

ENTRY_TYPES_FOR_REASON = ("movie", "short", "tvShort", "tvMovie", "tvSpecial")

R_NO_ID = "no_imdb_id_in_movielens"
R_UNKNOWN_ID = "imdb_id_not_in_the_imdb_snapshot"
R_UNCLASSIFIED = "not_entered_unclassified"
R_EPISODE = "id_belongs_to_an_episode_not_confirmed_by_title_and_year"
R_NO_SEARCHABLE_TITLE = "imdb_title_without_searchable_characters"
R_DUPLICATE = "another_movielens_film_has_the_primary_id_of_the_same_work"
R_AMBIGUOUS = "several_movielens_films_share_the_work_without_a_primary_id"


def episode_confirmed(movie_id: int, title: str, year: int | None, row: tuple | None) -> bool:
    """An id that belongs to an IMDb episode counts for MovieLens' film only if MovieLens' own title and year agree with the IMDb record of that id: the whole title,
    or the part after a series prefix ("Family Guy Presents: Blue Harvest" -> "Blue Harvest", "Doctor Who: The Day of the Doctor"); IMDb type tvEpisode only."""
    if not (row and row[0] == "tvEpisode"):
        return False
    if RR.movielens_confirms_identity([(movie_id, title, year)], [row[1], row[2]], row[4]):
        return True
    base = title.rsplit(" (", 1)[0] if title.rstrip().endswith(")") and title.rstrip()[-5:-1].isdigit() else title
    return any(RR.movielens_confirms_identity([(movie_id, base.rsplit(sep, 1)[1], year)], [row[1], row[2]], row[4]) for sep in (": ", " - ") if sep in base)


def apply(layer: Any) -> dict[str, Any]:
    db, counts = layer.db, layer.counts
    for ddl in V3.TABLES_ML:
        db.execute(ddl)
    ml = util.open_ro(layer.inp.movielens)
    work_of: dict[str, int] = {}
    for w, value in db.execute("SELECT entity_id, value FROM external_id WHERE scheme = 'imdb_title' ORDER BY is_primary, entity_id"):
        work_of[value] = w
    kind_of = {w: k for w, k in db.execute("SELECT work_id, kind FROM work")}
    entry_reason = {}
    for rec in layer.separate.get("not_entered", []):
        if rec.get("route") == "movielens" and rec.get("imdb"):
            entry_reason[rec["imdb"]] = rec["reason"]
    last = ml.execute("SELECT MAX(last_rated_at) FROM movie_stats").fetchone()[0]
    as_of = datetime.fromtimestamp(last, timezone.utc).strftime("%Y-%m-%d") if last else "2023-10-13"

    movies = ml.execute("SELECT m.movie_id, m.title, m.clean_title, m.year, l.imdb_id, COALESCE(s.n_ratings, 0), s.avg_rating "
                        "FROM movies m LEFT JOIN links l USING(movie_id) LEFT JOIN movie_stats s USING(movie_id) ORDER BY m.movie_id").fetchall()
    by_work: dict[int, list[tuple]] = collections.defaultdict(list)
    reason: dict[int, str] = {}
    for movie_id, title, clean, year, imdb, n, avg in movies:
        tt = util.imdb_tt(imdb)
        if not tt:
            reason[movie_id] = R_NO_ID
            continue
        w = work_of.get(tt)
        if w is None:
            row = layer.title_row(tt)
            if tt in entry_reason:
                reason[movie_id] = entry_reason[tt]
            elif row is None:
                reason[movie_id] = R_UNKNOWN_ID
            elif row[0] in ENTRY_TYPES_FOR_REASON and not normalize_name(" ".join(str(row[1] or row[2] or "").split())):
                reason[movie_id] = R_NO_SEARCHABLE_TITLE  # a work needs a primary name; IMDb's is only punctuation ("$", "()")
            else:
                reason[movie_id] = R_UNCLASSIFIED
            continue
        if kind_of.get(w) == "episode":
            if not episode_confirmed(movie_id, title, year, layer.title_row(tt)):
                reason[movie_id] = R_EPISODE
                continue
        by_work[w].append((movie_id, tt))
    work_of_movie: dict[int, int] = {}
    for w, rows in sorted(by_work.items()):
        primary = [r for r in rows if r[1] == layer.primary_tconst.get(w)]
        chosen = primary[0] if primary else (rows[0] if len(rows) == 1 else None)
        for movie_id, _tt in rows:
            if chosen is not None and movie_id == chosen[0]:
                work_of_movie[movie_id] = w
            else:
                reason[movie_id] = R_DUPLICATE if chosen is not None else R_AMBIGUOUS

    rows_out = []
    for movie_id, title, clean, year, imdb, n, avg in movies:
        w = work_of_movie.get(movie_id)
        rows_out.append((movie_id, util.imdb_tt(imdb), clean, year, n, avg if n else None, w, None if w is not None else reason[movie_id]))
        if w is not None and n:
            db.execute("INSERT OR IGNORE INTO work_rating VALUES (?,?,?,?,?,?,?,?)", (w, layer.src_ml, avg, 5.0, n, "audience", as_of, f"movielens:{movie_id}"))
            counts["ratings_movielens"] += 1
            if layer.primary_tconst.get(w) != util.imdb_tt(imdb):
                counts["ratings_movielens_through_an_alias"] += 1
        counts[f"ml_movie:{'in_catalogue' if w is not None else 'excluded:' + reason[movie_id].split(':')[0]}"] += 1
        if w is None and n:
            counts["ml_ratings_of_excluded_films"] += n
    db.executemany("INSERT INTO ml_movie VALUES (?,?,?,?,?,?,?,?)", rows_out)

    genres = [g for (g,) in ml.execute("SELECT DISTINCT genre FROM movie_genres ORDER BY genre")]
    db.executemany("INSERT INTO ml_genre (ml_genre_id, name) VALUES (?,?)", list(enumerate(genres, 1)))
    gid = {g: i for i, g in enumerate(genres, 1)}
    pairs = [(work_of_movie[m], gid[g]) for m, g in ml.execute("SELECT movie_id, genre FROM movie_genres ORDER BY movie_id, genre") if m in work_of_movie]
    db.executemany("INSERT INTO work_ml_genre VALUES (?,?)", sorted(set(pairs), key=lambda p: (p[0], p[1])))
    counts["ml_genre_pairs"] = len(pairs)
    tags = []
    for m, tag, n_users in ml.execute("SELECT movie_id, tag_norm, COUNT(DISTINCT user_id) FROM tags GROUP BY movie_id, tag_norm ORDER BY movie_id, tag_norm"):
        if m in work_of_movie:
            tags.append((tag, work_of_movie[m], n_users))
        else:
            counts["ml_tag_pairs_of_excluded_films"] += 1
    db.executemany("INSERT INTO work_tag VALUES (?,?,?)", tags)
    counts["ml_tag_pairs"] = len(tags)
    for ddl in V3.INDEXES_ML:
        db.execute(ddl)
    ml.close()
    return {"mapped": len(work_of_movie), "excluded": len(movies) - len(work_of_movie)}


def check(c) -> list[str]:
    """Invariants of the layer, run on the finished database: the stored mean and count equal the work_rating row, one film per work, closed reason list."""
    problems = []
    bad = c.execute("""SELECT COUNT(*) FROM ml_movie m JOIN work_rating r ON r.work_id = m.work_id AND r.source_ref = 'movielens:' || m.movie_id
                       WHERE r.vote_count <> m.n_ratings OR abs(r.value - m.avg_rating) > 1e-9""").fetchone()[0]
    if bad:
        problems.append(f"ml_movie differs from work_rating in {bad} rows")
    missing = c.execute("SELECT COUNT(*) FROM ml_movie m WHERE m.work_id IS NOT NULL AND m.n_ratings > 0 AND NOT EXISTS "
                        "(SELECT 1 FROM work_rating r WHERE r.work_id = m.work_id AND r.source_ref = 'movielens:' || m.movie_id)").fetchone()[0]
    if missing:
        problems.append(f"{missing} mapped MovieLens films have no work_rating row")
    extra = c.execute("SELECT COUNT(*) FROM work_rating r WHERE r.source_ref LIKE 'movielens:%' AND NOT EXISTS "
                      "(SELECT 1 FROM ml_movie m WHERE m.work_id = r.work_id AND 'movielens:' || m.movie_id = r.source_ref)").fetchone()[0]
    if extra:
        problems.append(f"{extra} MovieLens ratings have no ml_movie row")
    if c.execute("SELECT COUNT(*) FROM ml_movie WHERE work_id IS NULL AND reason IS NULL").fetchone()[0]:
        problems.append("excluded MovieLens film without a reason")
    return problems


def add_indexes(src, dst) -> dict[str, Any]:
    """`dst` = a copy of the schema-4 file `src` with the current ML indexes and fresh statistics, and the data digest checked unchanged (indexes are not data).
    Used to bring a built file up to date without the 16-minute build; a new build creates the same indexes."""
    import shutil
    import sqlite3
    from pathlib import Path

    from cinema_db.harness.build.build import content_digest

    src, dst = Path(src), Path(dst)
    if dst.exists():
        raise FileExistsError(dst)
    shutil.copyfile(src, dst)
    c = sqlite3.connect(dst)
    before = c.execute("SELECT value FROM build_info WHERE key = 'content_sha256'").fetchone()[0]
    for ddl in V3.INDEXES_ML:
        c.execute(ddl.replace("CREATE UNIQUE INDEX", "CREATE UNIQUE INDEX IF NOT EXISTS").replace("CREATE INDEX", "CREATE INDEX IF NOT EXISTS"))
    c.execute("ANALYZE ml_movie")
    c.execute("INSERT OR REPLACE INTO build_info VALUES ('derived_from', ?)", (src.name,))
    c.commit()
    after = content_digest(c)
    c.close()
    if after != before:
        dst.unlink()
        raise RuntimeError("the data digest changed: indexes must not change data")
    return {"content_sha256": after, "derived_from": src.name}


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description=add_indexes.__doc__)
    ap.add_argument("src")
    ap.add_argument("dst")
    a = ap.parse_args()
    print(json.dumps(add_indexes(a.src, a.dst)))
