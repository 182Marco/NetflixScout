"""Parity of `cinema_sql` `movielens` against the old `movie_db_search`, offline (two read-only SQLite files, no network, no model).

    python -m cinema_db.harness.tool_eval.run_movielens_parity            # the expected candidate (cinema_db/harness/candidate.py); another file needs --allow-other-file

Each case runs the OLD SQL (`tool/movie_db/sql/queries.py`, on the MovieLens file) and the NEW operation (`CinemaSqlTool.run`) with the same parameters.
The old tool drops series with up to 12 TMDb lookups; offline that step is replaced by the catalogue itself: an old result that the catalogue knows as a series,
an episode or another non-film work, or that is a MovieLens film with a documented exclusion reason, is "explained" and removed from the expected list. What remains
must match; a difference that is neither is reported as unexplained. Times: the old query on an open connection (no TMDb), the new tool end to end
(open, validate, run), median and p95 over the cases of each operation, second pass (warm file) and first pass.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from movie_db.config import QueryConfig
from tool.cinema_db.config import CinemaDbConfig
from tool.cinema_db.tool import CinemaSqlTool
from tool.movie_db.models import MovieDbOperation as Op
from tool.movie_db.models import MovieDbQuery
from tool.movie_db.sql.connection import open_readonly
from tool.movie_db.sql.repository import run_query
from tool.movie_db.titles import normalize_title

ROOT = Path(__file__).resolve().parents[3]
from cinema_db.harness.candidate import EXPECTED_PATH, identify  # noqa: E402  (the one definition of the target file)

NEW_DB = EXPECTED_PATH
OLD_DB = ROOT / "movie_db/data/movielens32m.sqlite3"
OUT = ROOT / "docs/cinema_db"
SETTINGS = QueryConfig(default_limit=10, max_limit=50, min_ratings=50, timeout_ms=2000)
FILM_KINDS = {"film", "short", "tv_film"}
GENRES = ["Action", "Adventure", "Animation", "Children", "Comedy", "Crime", "Documentary", "Drama", "Fantasy", "Film-Noir", "Horror", "IMAX", "Musical", "Mystery",
          "Romance", "Sci-Fi", "Thriller", "War", "Western"]
TITLES = ["Toy Story", "The Matrix", "Matrix", "Matrix, The", "the godfather", "Pulp Fiction", "Crash", "Love", "Halloween", "Il postino", "Amélie", "Lagaan",
          "Whiplash", "Planet Earth", "Blue Planet", "Star Wars", "100%", "_", "Kingdom", "The Kingdom", "xyzzy nonexistent title", "La Haine", "Cidade de Deus", "Parasite"]
TAGS = ["time travel", "atmospheric", "twist ending", "dark comedy", "based on a true story", "Time  Travel", "funny", "cult film", "zombies", "heist", "so bad it's good",
        "nonexistent-tag-xyz", "visually appealing", "alien invasion", "world war ii"]


def cases() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for limit in (10, 25):
        out.append({"op": "top_rated", "limit": limit})
        out.append({"op": "most_rated", "limit": limit})
    for a, b in ((1990, 1999), (2000, 2009), (1950, 1959), (2010, 2022)):
        out.append({"op": "top_rated", "year_from": a, "year_to": b})
        out.append({"op": "most_rated", "year_from": a, "year_to": b})
    for i, g in enumerate(GENRES):
        out.append({"op": "by_genre_year", "genre": g})
        out.append({"op": "by_genre_year", "genre": g, "year_from": (1970, 1990, 2000)[i % 3], "year_to": (1989, 1999, 2009)[i % 3], "limit": 10})
    for t in TITLES:
        out.append({"op": "by_title", "title": t, "limit": 10})
    out.append({"op": "by_title", "title": "Matrix", "genre": "Sci-Fi", "year_from": 1999, "year_to": 1999})
    for t in TAGS:
        out.append({"op": "by_tag", "tag": t, "limit": 10})
    out.append({"op": "by_tag", "tag": "time travel", "genre": "Comedy"})
    out.append({"op": "by_tag", "tag": "atmospheric", "year_from": 1990, "year_to": 1999})
    out.append({"op": "stats_by_genre"})
    for a, b in ((1990, 1999), (2000, 2009), (1950, 1969), (2010, 2022)):
        out.append({"op": "stats_by_genre", "year_from": a, "year_to": b})
    for g in ("Drama", "Horror"):
        out.append({"op": "stats_by_genre", "genre": g})
    return out


def old_query(case: dict[str, Any]) -> MovieDbQuery:
    fields = {k: v for k, v in case.items() if k != "op"}
    return MovieDbQuery(operation=Op(case["op"]), **fields)


def new_params(case: dict[str, Any]) -> dict[str, Any]:
    mode = {"by_genre_year": "top_rated", "stats_by_genre": "genre_stats"}.get(case["op"], case["op"])
    params = {"operation": "movielens", "ml_mode": mode, **{k: v for k, v in case.items() if k not in {"op"}}}
    return params


def classify(new: Any, movie_ids: list[int]) -> dict[int, tuple[str, str | None]]:
    """For old result ids: ('film', None) = a film of the catalogue, ('not_film', kind), ('excluded', reason), ('missing', None)."""
    if not movie_ids:
        return {}
    rows = new.execute(f"SELECT movie_id, status, work_kind, reason FROM v_ml_movie WHERE movie_id IN ({','.join('?' * len(movie_ids))})", movie_ids).fetchall()
    out = {}
    for movie_id, status, kind, reason in rows:
        out[movie_id] = ("excluded", reason) if status == "excluded" else (("film", None) if kind in FILM_KINDS else ("not_film", kind))
    return {m: out.get(m, ("missing", None)) for m in movie_ids}


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))] if ordered else 0.0


def run(db: Path, repeats: int = 3) -> dict[str, Any]:
    tool = CinemaSqlTool(config=CinemaDbConfig(enabled=True, db_path=str(db), max_queries_per_turn=40, default_limit=10))
    new_ro = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
    results, timings = [], defaultdict(lambda: {"old_first": [], "new_first": [], "old": [], "new": [], "cpu_old": [], "cpu_new": []})
    causes: Counter = Counter()
    cold_timeouts: Counter = Counter()
    for case in cases():
        q = old_query(case)
        def fetch(q=q):
            for attempt in range(4):  # the old tool's own 2 s guard can interrupt a cold query on the 1.3 GB file: counted, then retried warm
                conn = open_readonly(OLD_DB, timeout_ms=2000)  # one connection per run, as the old tool does (its 2 s guard counts from the connection)
                try:
                    return run_query(conn, q, SETTINGS, fetch_limit=50)[1]
                except sqlite3.OperationalError:
                    cold_timeouts["old"] += 1
                finally:
                    conn.close()
            raise RuntimeError("old query keeps timing out")
        t0 = time.perf_counter(); old_rows = fetch(); t_old_first = (time.perf_counter() - t0) * 1000
        params = new_params(case)
        t0 = time.perf_counter(); res = tool.run(query="parity", params=dict(params, limit=case.get("limit", 10) if case["op"] != "stats_by_genre" else 50)); t_new_first = (time.perf_counter() - t0) * 1000
        warm_old, warm_new, cpu_old, cpu_new = [], [], [], []
        new_params_warm = dict(params, limit=case.get("limit", 10) if case["op"] != "stats_by_genre" else 50)
        for _ in range(repeats):
            t0, c0 = time.perf_counter(), time.process_time(); fetch(); warm_old.append((time.perf_counter() - t0) * 1000); cpu_old.append((time.process_time() - c0) * 1000)
            t0, c0 = time.perf_counter(), time.process_time(); tool.run(query="parity", params=new_params_warm); warm_new.append((time.perf_counter() - t0) * 1000); cpu_new.append((time.process_time() - c0) * 1000)
        t = timings[case["op"]]
        t["cpu_old"].append(statistics.median(cpu_old)); t["cpu_new"].append(statistics.median(cpu_new))
        t["old_first"].append(t_old_first); t["new_first"].append(t_new_first); t["old"].append(statistics.median(warm_old)); t["new"].append(statistics.median(warm_new))
        body = res["metadata"]["cinema_db"]
        limit = case.get("limit") or 10
        entry: dict[str, Any] = {"case": case, "new_status": body["status"], "new_reason": body.get("reason")}
        if case["op"] == "stats_by_genre":
            o = {r["genre"]: (r["n_movies"], r["avg_rating"], r["n_ratings"]) for r in old_rows}
            n = {g["genre"]: (g["films"], g["avg_rating"], g["ratings"]) for g in body.get("genres", [])}
            diffs = {g: {"old": o.get(g), "new": n.get(g)} for g in sorted(set(o) | set(n)) if o.get(g) != n.get(g)}
            entry.update({"genres_old": len(o), "genres_new": len(n), "identical": not diffs, "differences": diffs,
                          "max_rel_diff_films": max([abs(o[g][0] - n[g][0]) / o[g][0] for g in o if g in n] or [0])})
        else:
            ids_old = [r["movie_id"] for r in old_rows]
            cls = classify(new_ro, ids_old)
            ranking = case["op"] in {"top_rated", "most_rated", "by_genre_year"}
            expected = [m for m in ids_old if cls[m][0] == "film"] if ranking else [m for m in ids_old]
            for m in ids_old:
                if ranking and cls[m][0] != "film":
                    causes[f"{cls[m][0]}:{cls[m][1]}"] += 1
            new_ids = []
            by_wid = {}
            if "movies" in body:
                for it in body["movies"]:
                    by_wid[it["work_id"]] = it
                wids = [w for w in by_wid if w]
                wid_to_ml = dict(new_ro.execute(f"SELECT work_id, movie_id FROM ml_movie WHERE work_id IN ({','.join('?' * len(wids))})", wids).fetchall()) if wids else {}
                new_ids = [wid_to_ml.get(it["work_id"]) if it["work_id"] else None for it in body["movies"]]
                if not ranking:  # excluded MovieLens films have no work: match them by title
                    ml_by_title = {normalize_title(r[1]): r[0] for r in new_ro.execute("SELECT movie_id, ml_title FROM ml_movie WHERE work_id IS NULL AND movie_id IN (%s)" % ",".join(str(i) for i in ids_old))} if ids_old else {}
                    new_ids = [m if m else ml_by_title.get(normalize_title(it["title"])) for m, it in zip(new_ids, body["movies"])]
            k = min(limit, 10)
            e, n = expected[:k], new_ids[:k]
            entry.update({"old_top": ids_old[:k], "expected_top": e, "new_top": n, "identical": e == n, "same_set": set(e) == set(n),
                          "overlap": len(set(e) & set(n)) if (e or n) else 1, "compared": max(len(e), 1),
                          "old_removed": {str(m): list(cls[m]) for m in ids_old[:k] if ranking and cls[m][0] != "film"}})
        results.append(entry)
    summary = {}
    for op, t in timings.items():
        summary[op] = {"cases": len(t["new"]), "old_median_ms": round(statistics.median(t["old"]), 1), "old_p95_ms": round(pct(t["old"], .95), 1),
                       "new_median_ms": round(statistics.median(t["new"]), 1), "new_p95_ms": round(pct(t["new"], .95), 1),
                       "old_first_p95_ms": round(pct(t["old_first"], .95), 1), "new_first_p95_ms": round(pct(t["new_first"], .95), 1),
                       "ratio_median": round(statistics.median(t["new"]) / max(statistics.median(t["old"]), 0.1), 2),
                       "cpu_old_median_ms": round(statistics.median(t["cpu_old"]), 1), "cpu_new_median_ms": round(statistics.median(t["cpu_new"]), 1), "cpu_new_p95_ms": round(pct(t["cpu_new"], .95), 1),
                       "cpu_ratio_median": round(statistics.median(t["cpu_new"]) / max(statistics.median(t["cpu_old"]), 0.1), 2)}
    return {"db": str(db.name), "cases": len(results), "results": results, "timings": summary, "old_results_removed_by_cause": dict(causes.most_common()), "old_tool_2s_guard_interruptions_before_retry": cold_timeouts["old"]}


def report(data: dict[str, Any]) -> str:
    res = data["results"]
    lines = [f"# MovieLens parity: old `movie_db_search` against `cinema_sql` `movielens`", "",
             f"File: `{data['db']}`. {data['cases']} cases, offline. Old = the old SQL on the MovieLens file (no TMDb); new = `CinemaSqlTool.run` end to end.", ""]
    by_op: dict[str, list] = defaultdict(list)
    for r in res:
        by_op[r["case"]["op"]].append(r)
    lines += ["## Results", "", "| operation | cases | identical top-k (after explained removals) | same set | mean overlap | no result (new) |", "|---|---|---|---|---|---|"]
    for op, rows in by_op.items():
        ident = sum(1 for r in rows if r.get("identical")); same = sum(1 for r in rows if r.get("same_set", r.get("identical")))
        ov = [r["overlap"] / r["compared"] for r in rows if r.get("compared")]
        lines.append(f"| {op} | {len(rows)} | {ident} | {same} | {round(statistics.mean(ov), 3) if ov else '-'} | {sum(1 for r in rows if r['new_status'] != 'ok')} |")
    lines += ["", "Old results removed because the catalogue knows them as non-films or documents their exclusion:", ""]
    lines += [f"- {k}: {v}" for k, v in data["old_results_removed_by_cause"].items()] or ["- none"]
    lines += ["", f"Interruptions of the OLD tool's own 2 s guard before a warm retry: {data['old_tool_2s_guard_interruptions_before_retry']}.", "", "## Timings (ms, per case: median of warm repeats; then median and p95 over the cases)", "", "| operation | cases | old median | old p95 | new median | new p95 | new/old (median) | old p95 first pass | new p95 first pass | CPU old median | CPU new median | CPU new p95 | CPU new/old |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for op, t in data["timings"].items():
        lines.append(f"| {op} | {t['cases']} | {t['old_median_ms']} | {t['old_p95_ms']} | {t['new_median_ms']} | {t['new_p95_ms']} | {t['ratio_median']} | {t['old_first_p95_ms']} | {t['new_first_p95_ms']} | {t['cpu_old_median_ms']} | {t['cpu_new_median_ms']} | {t['cpu_new_p95_ms']} | {t['cpu_ratio_median']} |")
    diff = [r for r in res if not r.get("identical")]
    lines += ["", f"## Cases that are not identical ({len(diff)})", ""]
    for r in diff:
        lines.append(f"- `{json.dumps(r['case'], ensure_ascii=False)}` status={r['new_status']}" + (f" overlap {r['overlap']}/{r['compared']} expected={r['expected_top']} new={r['new_top']}" if "overlap" in r else f" differences={json.dumps(r.get('differences'), ensure_ascii=False)[:300]}"))
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=NEW_DB)
    ap.add_argument("--name", default="PHASE10_MOVIELENS_PARITY")
    ap.add_argument("--allow-other-file", action="store_true", help="run on a file that is not the expected candidate (the identity check is skipped, and the report says so)")
    args = ap.parse_args(argv)
    if not args.allow_other_file:
        identify(args.db)  # raises CandidateMismatch: no silent fallback to another file
    data = run(args.db)
    data["identity_checked"] = not args.allow_other_file
    (OUT / f"{args.name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / f"{args.name}.md").write_text(report(data), encoding="utf-8")
    print(report(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
