"""Independent verification of a schema-4 file against the ORIGINAL MovieLens database and against the schema-3 file it was built from (read-only, offline).

    python -m cinema_db.harness.build.verify_movielens --new cinema_db/data/cinema.v4.candidate6.sqlite3 --base cinema_db/data/cinema.v3.candidate2.sqlite3

Checks: integrity and foreign keys; every table of the base unchanged except work_rating (a superset: the base rows are all there); every MovieLens film with
statistics is either in the catalogue with the identical mean and count, or has a reason; genre sets and tag counts (count DISTINCT users) equal to the source for
every mapped film; reasons are a closed list; no work holds two MovieLens films.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ML = ROOT / "movie_db/data/movielens32m.sqlite3"
NEW_TABLES = {"ml_movie", "ml_genre", "work_ml_genre", "work_tag"}


def ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)


def table_digest(c: sqlite3.Connection, t: str, where: str = "") -> tuple[int, str]:
    h, n = hashlib.sha256(), 0
    for row in c.execute(f'SELECT * FROM "{t}" {where} ORDER BY rowid'):
        h.update(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode()); n += 1
    return n, h.hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--new", type=Path, required=True)
    ap.add_argument("--base", type=Path, default=ROOT / "cinema_db/data/cinema.v3.candidate2.sqlite3")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    new, base, ml = ro(a.new), ro(a.base), ro(ML)
    out: dict = {"new": a.new.name, "base": a.base.name, "checks": {}, "problems": []}
    P = out["problems"]
    out["checks"]["integrity"] = new.execute("PRAGMA integrity_check").fetchone()[0]
    out["checks"]["foreign_key_violations"] = len(new.execute("PRAGMA foreign_key_check").fetchall())
    if out["checks"]["integrity"] != "ok" or out["checks"]["foreign_key_violations"]:
        P.append("integrity or foreign keys")
    out["checks"]["schema_version"] = new.execute("SELECT value FROM build_info WHERE key='schema_version'").fetchone()[0]
    out["checks"]["content_sha256"] = new.execute("SELECT value FROM build_info WHERE key='content_sha256'").fetchone()[0]
    from cinema_db.harness.build import id_rules  # an identifier with the wrong shape (a person id stored as a title id) is a defect of the file, not of the sources
    shape = id_rules.violations(new)
    out["checks"]["id_shape_violations"] = [list(v) for v in shape]
    if shape:
        P.append(f"{len(shape)} identifier(s) with the wrong shape: {shape[:3]}")

    # 1. base tables unchanged. The ONLY allowed differences belong to the works whose identifier the build itself reports as replaced (invalid_ids.jsonl, an owner-approved
    #    override with evidence): every new-only or base-only row must be about such a work (first column = its id); any other difference is a problem.
    sep = a.new.with_suffix("").with_name(a.new.with_suffix("").name + ".separate") / "invalid_ids.jsonl"
    corrected = {json.loads(l)["entity_id"] for l in sep.read_text().splitlines() if l.strip() and json.loads(l).get("result") == "replaced"} if sep.exists() else set()
    out["checks"]["corrected_works"] = sorted(corrected)
    tables = [r[0] for r in base.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'entity_name_fts%' AND name <> 'build_info' ORDER BY name")]
    changed = {}
    new.execute(f"ATTACH 'file:{a.base}?mode=ro&immutable=1' AS b")  # sequential scans of both files: EXCEPT in both directions is empty when the tables are equal
    for t in tables:
        if t == "work_rating":
            continue
        n_new, n_base = new.execute(f'SELECT COUNT(*) FROM main."{t}"').fetchone()[0], new.execute(f'SELECT COUNT(*) FROM b."{t}"').fetchone()[0]
        extra = new.execute(f'SELECT COUNT(*) FROM (SELECT * FROM main."{t}" EXCEPT SELECT * FROM b."{t}")').fetchone()[0] if n_new == n_base else None
        if corrected and t in {"work", "entity_claim", "external_id", "field_provenance"}:
            only_new = [r for r in new.execute(f'SELECT * FROM main."{t}" EXCEPT SELECT * FROM b."{t}"')]
            only_base = [r for r in new.execute(f'SELECT * FROM b."{t}" EXCEPT SELECT * FROM main."{t}"')]
            if all(r[0] in corrected for r in only_new + only_base):  # the id column is first in these four tables
                out["checks"].setdefault("corrected_rows", {})[t] = {"new_only": len(only_new), "base_only": len(only_base)}
                continue
        if n_new != n_base or extra:
            changed[t] = {"base": n_base, "new": n_new, "rows_not_in_base": extra}
    out["checks"]["base_tables_changed"] = changed
    if changed:
        P.append(f"base tables changed: {sorted(changed)}")
    base_ratings = {(w, s, v, sc, n, au, ao, ref) for w, s, v, sc, n, au, ao, ref in base.execute("SELECT * FROM work_rating")}
    new_ratings = {row for row in new.execute("SELECT * FROM work_rating")}
    missing = base_ratings - new_ratings
    added = new_ratings - base_ratings
    out["checks"]["work_rating"] = {"base": len(base_ratings), "new": len(new_ratings), "base_rows_missing_in_new": len(missing), "rows_added": len(added),
                                    "added_all_movielens": all(str(r[7]).startswith("movielens:") for r in added)}
    lost_unexplained = [r for r in missing if not str(r[7]).startswith("movielens:") or new.execute("SELECT work_id FROM ml_movie WHERE movie_id = ?", (int(str(r[7])[10:]),)).fetchone()[0] is not None]
    corrected_ratings = [r for r in added if r[0] in corrected and str(r[7]).startswith("tt")]  # the IMDb rating the corrected identifier brings
    added -= set(corrected_ratings)
    out["checks"]["work_rating"]["corrected_imdb_ratings_added"] = len(corrected_ratings)
    out["checks"]["work_rating"]["added_all_movielens"] = all(str(r[7]).startswith("movielens:") for r in added)
    out["checks"]["work_rating"]["base_rows_missing_in_new_and_not_documented"] = len(lost_unexplained)
    out["checks"]["work_rating"]["base_rows_missing_are_movielens_episodes_now_excluded"] = [r[7] for r in missing]
    if lost_unexplained or not out["checks"]["work_rating"]["added_all_movielens"]:
        P.append("work_rating: base rows lost without a documented exclusion, or non-MovieLens rows added")

    # 2. MovieLens films: statistics, mapping, reasons
    stats = {m: (n, avg) for m, n, avg in ml.execute("SELECT movie_id, n_ratings, avg_rating FROM movie_stats")}
    movies = {m: (t, y, i) for m, t, y, i in ml.execute("SELECT m.movie_id, m.clean_title, m.year, l.imdb_id FROM movies m LEFT JOIN links l USING(movie_id)")}
    rows = {r[0]: r for r in new.execute("SELECT movie_id, imdb_id, ml_title, ml_year, n_ratings, avg_rating, work_id, reason FROM ml_movie")}
    c = out["checks"]
    c["ml_movies_source"], c["ml_movies_new"] = len(movies), len(rows)
    if set(rows) != set(movies):
        P.append("ml_movie does not cover every MovieLens film")
    bad_title = sum(1 for m, r in rows.items() if m in movies and (r[2], r[3]) != (movies[m][0], movies[m][1]))
    bad_stats = sum(1 for m, r in rows.items() if (r[4], r[5]) != ((stats[m][0], stats[m][1]) if m in stats else (0, None)))
    c["title_year_differences"], c["rating_differences_vs_source"] = bad_title, bad_stats
    if bad_title or bad_stats:
        P.append("ml_movie title/year/statistics differ from the source")
    mapped = {m: r[6] for m, r in rows.items() if r[6] is not None}
    c["films_in_catalogue"], c["films_excluded"] = len(mapped), len(rows) - len(mapped)
    c["films_with_statistics"] = len(stats)
    c["films_with_statistics_in_catalogue"] = sum(1 for m in stats if m in mapped)
    c["ratings_total_source"] = sum(n for n, _ in stats.values())
    c["ratings_in_catalogue"] = sum(stats[m][0] for m in stats if m in mapped)
    c["ratings_excluded"] = c["ratings_total_source"] - c["ratings_in_catalogue"]
    reasons = collections.Counter(); reasons_ratings = collections.Counter()
    for m, r in rows.items():
        if r[6] is None:
            key = r[7].split(":")[0] if r[7].startswith("outside_entry_rule") else r[7]
            key = r[7]
            reasons[key] += 1; reasons_ratings[key] += r[4]
    c["exclusion_reasons"] = {k: {"films": v, "ratings": reasons_ratings[k]} for k, v in reasons.most_common()}
    if any(r[6] is None and not r[7] for r in rows.values()):
        P.append("an excluded film without a reason")
    if any(r[7] == "not_entered_unclassified" for r in rows.values()):
        c["unclassified_reasons"] = sum(1 for r in rows.values() if r[7] == "not_entered_unclassified"); P.append("unclassified exclusions remain")
    dup = new.execute("SELECT COUNT(*) FROM (SELECT work_id FROM ml_movie WHERE work_id IS NOT NULL GROUP BY work_id HAVING COUNT(*) > 1)").fetchone()[0]
    c["works_with_two_movielens_films"] = dup
    if dup:
        P.append("a work holds two MovieLens films")
    rated = {(r[0], r[1], r[2]) for r in new.execute("SELECT work_id, value, vote_count FROM work_rating WHERE source_ref LIKE 'movielens:%'")}
    exp = {(rows[m][6], rows[m][5], rows[m][4]) for m in mapped if rows[m][4]}
    c["movielens_rating_rows"] = len(rated)
    if rated != exp:
        P.append("work_rating MovieLens rows differ from ml_movie")

    # 3. genres
    src_g = collections.defaultdict(set)
    for m, g in ml.execute("SELECT movie_id, genre FROM movie_genres"):
        src_g[m].add(g)
    new_g = collections.defaultdict(set)
    for w, g in new.execute("SELECT x.work_id, g.name FROM work_ml_genre x JOIN ml_genre g USING(ml_genre_id)"):
        new_g[w].add(g)
    gdiff = sum(1 for m, w in mapped.items() if src_g.get(m, set()) != new_g.get(w, set()))
    c["genre_set_differences_for_mapped_films"] = gdiff
    c["genre_pairs_source"] = sum(len(v) for v in src_g.values()); c["genre_pairs_new"] = sum(len(v) for v in new_g.values())
    c["genre_pairs_source_in_catalogue"] = sum(len(src_g.get(m, ())) for m in mapped)
    c["genres"] = new.execute("SELECT COUNT(*) FROM ml_genre").fetchone()[0]
    if gdiff or c["genre_pairs_new"] != c["genre_pairs_source_in_catalogue"] or set(new_g) - set(mapped.values()):
        P.append("genre sets differ")

    # 4. tags
    src_t = {(m, t): n for m, t, n in ml.execute("SELECT movie_id, tag_norm, COUNT(DISTINCT user_id) FROM tags GROUP BY movie_id, tag_norm")}
    inv = {w: m for m, w in mapped.items()}
    new_t = {(inv[w], t): n for t, w, n in new.execute("SELECT tag_norm, work_id, n_users FROM work_tag")}
    exp_t = {k: v for k, v in src_t.items() if k[0] in mapped}
    c["tag_pairs_source"], c["tag_pairs_new"], c["tag_pairs_source_in_catalogue"] = len(src_t), len(new_t), len(exp_t)
    c["tag_assignments_source"] = ml.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
    c["tag_assignments_in_catalogue"] = sum(exp_t.values()); c["tag_distinct_new"] = new.execute("SELECT COUNT(DISTINCT tag_norm) FROM work_tag").fetchone()[0]
    c["tag_distinct_source"] = ml.execute("SELECT COUNT(DISTINCT tag_norm) FROM tags").fetchone()[0]
    c["tag_pair_differences"] = sum(1 for k in set(exp_t) | set(new_t) if exp_t.get(k) != new_t.get(k))
    c["films_with_tags_source"] = len({m for m, _ in src_t}); c["films_with_tags_in_catalogue"] = len({m for m, _ in exp_t})
    if c["tag_pair_differences"]:
        P.append("tag pairs differ from the source")
    out["ok"] = not P
    text = json.dumps(out, ensure_ascii=False, indent=1)
    print(text)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
