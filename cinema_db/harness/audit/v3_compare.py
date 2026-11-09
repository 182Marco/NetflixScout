"""Before/after measurement of the v3 layer: base (v2) file against the new v3 file. Read-only on both."""
from __future__ import annotations

import collections
import json
import sqlite3
from pathlib import Path

from . import util
from .util import pct


def _q(c: sqlite3.Connection, sql: str, *a):
    return c.execute(sql, a).fetchall()


def snapshot(path: Path, movielens: Path = util.MOVIELENS_DB) -> dict:
    c = util.open_ro(path)
    out: dict = {"file_bytes": path.stat().st_size}
    out["works_by_kind"] = dict(_q(c, "SELECT kind, COUNT(*) FROM work GROUP BY kind ORDER BY 2 DESC"))
    out["works"], out["persons"], out["credits"] = (c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("work", "person", "credit"))
    out["credits_with_billing_order"] = c.execute("SELECT COUNT(*) FROM credit WHERE billing_order IS NOT NULL").fetchone()[0]
    out["cast_credits_with_character"] = c.execute("SELECT COUNT(*) FROM credit WHERE role = 'cast' AND character_name IS NOT NULL").fetchone()[0]
    out["cast_credits"] = c.execute("SELECT COUNT(*) FROM credit WHERE role = 'cast'").fetchone()[0]
    out["external_ids"] = {s: n for s, n in _q(c, "SELECT scheme, COUNT(*) FROM external_id GROUP BY scheme")}
    out["persons_with_imdb_name"] = c.execute("SELECT COUNT(DISTINCT entity_id) FROM external_id WHERE scheme = 'imdb_name'").fetchone()[0]
    out["works_with_imdb_id"] = c.execute("SELECT COUNT(DISTINCT entity_id) FROM external_id WHERE scheme = 'imdb_title'").fetchone()[0]
    out["screen_works_without_imdb_id"] = c.execute("SELECT COUNT(*) FROM work w WHERE w.kind IN ('film','short','tv_film','series','miniseries') "
                                                    "AND NOT EXISTS (SELECT 1 FROM external_id x WHERE x.entity_id = w.work_id AND x.scheme = 'imdb_title')").fetchone()[0]
    out["episodes_with_imdb_id"] = c.execute("SELECT COUNT(*) FROM work w WHERE w.kind = 'episode' AND EXISTS (SELECT 1 FROM external_id x WHERE x.entity_id = w.work_id AND x.scheme = 'imdb_title')").fetchone()[0]
    out["films_with_runtime"] = c.execute("SELECT COUNT(*) FROM work WHERE kind = 'film' AND runtime_min IS NOT NULL").fetchone()[0]
    out["films_by_decade"] = {f"{d}s": n for d, n in _q(c, "SELECT (release_year / 10) * 10, COUNT(*) FROM work WHERE kind = 'film' AND release_year IS NOT NULL GROUP BY 1")}
    homonym = c.execute("SELECT COUNT(*) FROM (SELECT n.name_norm, w.release_year FROM work w JOIN entity_name n ON n.entity_id = w.work_id AND n.is_primary = 1 "
                        "WHERE w.kind = 'film' AND w.release_year IS NOT NULL GROUP BY 1, 2 HAVING COUNT(*) > 1)").fetchone()[0]
    out["film_groups_with_same_title_and_year"] = homonym
    out["tables"] = sorted(n for (n,) in _q(c, "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'entity_name_fts%' AND name NOT LIKE 'sqlite_%'"))
    if "work_rating" in out["tables"]:
        out["ratings_by_source"] = {s: n for s, n in _q(c, "SELECT s.name, COUNT(*) FROM work_rating r JOIN source s USING(source_id) GROUP BY 1")}
        out["works_with_two_or_more_ratings"] = c.execute("SELECT COUNT(*) FROM (SELECT work_id FROM work_rating GROUP BY work_id HAVING COUNT(*) > 1)").fetchone()[0]
        out["claims_by_field"] = {f: n for f, n in _q(c, "SELECT field, COUNT(*) FROM entity_claim GROUP BY field")}
        out["candidates_by_tier"] = {f: n for f, n in _q(c, "SELECT tier, COUNT(*) FROM external_id_candidate GROUP BY tier")}
        out["status"] = {f"{a}|{b}|{p}": n for a, b, p, n in _q(c, "SELECT entry_route, completeness, COALESCE(plot_status,'-'), COUNT(*) FROM work_status GROUP BY 1, 2, 3")}
        out["identification"] = {a: n for a, n in _q(c, "SELECT identification, COUNT(*) FROM work_status GROUP BY 1")}
        out["completeness_screen_works"] = {a: n for a, n in _q(c, "SELECT s.completeness, COUNT(*) FROM work_status s JOIN work w USING(work_id) WHERE w.kind IN ('film','short','tv_film','series','miniseries') GROUP BY 1")}
        out["new_works_by_route_kind"] = {f"{a}|{b}": n for a, b, n in _q(c, "SELECT s.entry_route, w.kind, COUNT(*) FROM work_status s JOIN work w USING(work_id) WHERE s.entry_route <> 'catalogue' GROUP BY 1, 2")}
        # same title + year between a NEW work and an OLD one (must be zero: such titles are held back)
        out["new_vs_old_same_title_year"] = c.execute(
            "SELECT COUNT(*) FROM work_status a JOIN entity_name na ON na.entity_id = a.work_id AND na.is_primary = 1 JOIN work wa ON wa.work_id = a.work_id "
            "JOIN entity_name nb ON nb.name_norm = na.name_norm JOIN work wb ON wb.work_id = nb.entity_id AND wb.release_year = wa.release_year "
            "JOIN work_status b ON b.work_id = wb.work_id WHERE a.entry_route <> 'catalogue' AND b.entry_route = 'catalogue' AND wb.kind NOT IN ('episode','season')").fetchone()[0]
    # same title + year among film-like works: homonyms or duplicates? (compare director NAMES: new and old works have different person ids)
    groups = collections.defaultdict(list)
    for w, n, y in _q(c, "SELECT w.work_id, n.name_norm, w.release_year FROM work w JOIN entity_name n ON n.entity_id = w.work_id AND n.is_primary = 1 "
                          "WHERE w.kind IN ('film','short','tv_film') AND w.release_year IS NOT NULL"):
        groups[(n, y)].append(w)
    multi = {k: v for k, v in groups.items() if len(v) > 1}
    ids = {w for v in multi.values() for w in v}
    dirs = collections.defaultdict(set)
    for w, nm in _q(c, "SELECT cr.work_id, n.name_norm FROM credit cr JOIN entity_name n ON n.entity_id = cr.person_id AND n.is_primary = 1 WHERE cr.role = 'director'"):
        if w in ids:
            dirs[w].add(" ".join(sorted(nm.split())))
    kinds = collections.Counter()
    for v in multi.values():
        a, b2 = v[0], v[1]
        kinds["same_director_probable_duplicate" if dirs[a] & dirs[b2] else "different_directors_homonyms" if dirs[a] and dirs[b2] else "director_unknown"] += 1
    out["same_title_year_groups_by_director"] = dict(kinds)
    # MovieLens relevance coverage
    ml = util.open_ro(movielens)
    imdb = {v for (v,) in _q(c, "SELECT value FROM external_id WHERE scheme = 'imdb_title'")}
    rows = ml.execute("SELECT l.imdb_id, s.n_ratings FROM links l JOIN movie_stats s USING(movie_id)").fetchall()
    cov = {}
    for t in (1, 10, 50, 100, 1000):
        pool = [r for r in rows if r[1] >= t]
        have = sum(1 for r in pool if util.imdb_tt(r[0]) in imdb)
        cov[str(t)] = {"movielens_films": len(pool), "in_cinema": have, "pct": pct(have, len(pool))}
    out["movielens_coverage_by_min_votes"] = cov
    return out


def compare(base: Path, v3: Path, movielens: Path = util.MOVIELENS_DB) -> dict:
    return {"base": snapshot(base, movielens), "v3": snapshot(v3, movielens)}
