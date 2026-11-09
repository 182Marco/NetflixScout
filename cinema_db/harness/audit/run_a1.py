"""A1 command line (offline once the IMDb archive is in place; the download is `cinema_db.harness.acquire.imdb`).

    python -m cinema_db.harness.audit.run_a1 stage     # IMDb archive -> audit staging SQLite (minutes, one pass per dataset)
    python -m cinema_db.harness.audit.run_a1 run       # analyses -> results.json + candidate files
    python -m cinema_db.harness.audit.run_a1 report    # results.json -> docs/cinema_db/PHASE9_A1_REPORT.md
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from cinema_db.harness.acquire import imdb as acquire

from . import imdb_load as L
from . import imdb_sections as S
from . import util
from .sections import Context

OUT_A1 = util.ROOT / "cinema_db/data/audit_a1"
STAGING = OUT_A1 / "imdb_staging.sqlite3"
REPORT_A1 = util.ROOT / "docs/cinema_db/PHASE9_A1_REPORT.md"


def latest_snapshot() -> Path:
    dirs = sorted(p for p in acquire.SNAPSHOT_DIR.iterdir() if (p / "manifest.json").is_file())
    if not dirs:
        raise SystemExit("no IMDb snapshot: run cinema_db.harness.acquire.imdb first")
    return dirs[-1]


def page_candidates(conn, ctx: Context) -> set[int]:
    """Titles an Italian film page could correspond to (title and year within one): needed so their principals are staged."""
    records = ctx.dump_records() or []
    rejected = ctx.pages["rejected"]
    conn.execute("CREATE INDEX IF NOT EXISTS i_pn ON title(pnorm)")
    conn.execute("CREATE INDEX IF NOT EXISTS i_on ON title(onorm)")
    marks = ",".join("?" * len(S.FILMISH))
    found: set[int] = set()
    for rec in records:
        if rec["kind"] != "film_page" or rec["page_id"] not in rejected or not rec.get("year"):
            continue
        for key in {k for k in (util.norm_title(util.strip_qualifier(rec["title"])), util.norm_title(rec.get("original_title") or "")) if k}:
            for (t,) in conn.execute(f"SELECT tconst FROM title WHERE (pnorm = ? OR onorm = ?) AND type IN ({marks}) AND start BETWEEN ? AND ?",
                                     (key, key, *S.FILMISH, rec["year"] - 1, rec["year"] + 1)):
                found.add(L.tid(t))
    return found


def cmd_stage(ctx: Context) -> None:
    snap = latest_snapshot()
    manifest = acquire.read_manifest(snap)["datasets"]
    for name, entry in manifest.items():
        path = snap / entry["file"]
        if path.stat().st_size != entry["bytes"]:
            raise SystemExit(f"{name}: archive does not match its manifest")
    OUT_A1.mkdir(parents=True, exist_ok=True)
    tmp = STAGING.with_suffix(".tmp")
    conn = L.create_staging(tmp)
    t0 = time.time()
    interest = {L.tid(v) for v in ctx.ids.get("imdb_title", {})} | {L.tid(m["imdb"]) for m in ctx.ml if m["imdb"]}
    interest.discard(None)
    stats: dict = {"snapshot": snap.name, "manifest": {k: {x: v[x] for x in ("sha256", "bytes", "retrieved_at", "last_modified", "url")} for k, v in manifest.items()}}
    series_parents = {L.tid(v) for v, es in ctx.ids.get("imdb_title", {}).items() if any(ctx.works.get(e, ("",))[0] in ("series", "miniseries") for e in es)}
    series_parents.discard(None)
    stats["episodes"], episode_ids = L.stage_episodes(snap / manifest["title.episode"]["file"], conn, series_parents)
    print(f"episodes {time.time() - t0:.0f}s", file=sys.stderr, flush=True)
    stats["basics"] = L.stage_basics(snap / manifest["title.basics"]["file"], conn, interest | episode_ids)
    print(f"basics {time.time() - t0:.0f}s", file=sys.stderr, flush=True)
    candidates = page_candidates(conn, ctx)
    stats["page_candidate_titles"] = len(candidates)
    keep_titles = {tid for (tid,) in conn.execute("SELECT tid FROM title")}
    stats["crew"] = L.stage_crew(snap / manifest["title.crew"]["file"], conn, keep_titles)
    print(f"crew {time.time() - t0:.0f}s", file=sys.stderr, flush=True)
    principal_interest = interest | candidates
    stats["principals"] = L.stage_principals(snap / manifest["title.principals"]["file"], conn, principal_interest)
    print(f"principals {time.time() - t0:.0f}s", file=sys.stderr, flush=True)
    stats["ratings"] = L.stage_ratings(snap / manifest["title.ratings"]["file"], conn, {tid for (tid,) in conn.execute("SELECT tid FROM title")})
    print(f"ratings {time.time() - t0:.0f}s", file=sys.stderr, flush=True)
    people = L.needed_people(conn, principal_interest)
    stats["names"] = L.stage_names(snap / manifest["name.basics"]["file"], conn, people)
    print(f"names {time.time() - t0:.0f}s", file=sys.stderr, flush=True)
    conn.execute("CREATE INDEX IF NOT EXISTS i_pr_n ON principal(nconst)")
    conn.execute("INSERT INTO meta VALUES ('stats', ?)", (json.dumps(stats, sort_keys=True),))
    conn.commit()
    conn.close()
    tmp.replace(STAGING)
    util.write_json(OUT_A1 / "staging_stats.json", stats)
    print("staging complete:", {k: v for k, v in stats.items() if k in ("page_candidate_titles",)}, file=sys.stderr)


def cmd_run(ctx: Context) -> None:
    import sqlite3
    st = sqlite3.connect(f"file:{STAGING}?mode=ro", uri=True)
    results: dict = {"staging": json.loads(st.execute("SELECT value FROM meta WHERE key = 'stats'").fetchone()[0])}

    def step(name, fn):
        t = time.time()
        value = fn()
        print(f"[{name}] {time.time() - t:.1f}s", file=sys.stderr, flush=True)
        return value

    results["works"], doubles = step("works", lambda: S.works_vs_imdb(ctx, st))
    util.write_jsonl(OUT_A1 / "candidates_double_imdb.jsonl", doubles)
    results["people"], cand = step("people", lambda: S.people_and_cast(ctx, st))
    for k, rows in cand.items():
        if k.startswith("_"):
            continue
        util.write_jsonl(OUT_A1 / f"candidates_{k}.jsonl", rows)
    results["directors"] = step("crew", lambda: S.crew_check(ctx, st))
    results["movielens"], rows = step("movielens", lambda: S.ml_missing_classification(ctx, st))
    util.write_jsonl(OUT_A1 / "ml_missing_classified.jsonl", rows)
    results["italian_pages"], rows = step("pages", lambda: S.italian_pages(ctx, st))
    util.write_jsonl(OUT_A1 / "italian_pages_classified.jsonl", rows)
    results["dubious_pages"], archive, recovered = step("dubious", lambda: S.dubious_pages(ctx, st))
    util.write_jsonl(OUT_A1 / "dubious_pages_archive.jsonl", archive)
    util.write_jsonl(OUT_A1 / "dubious_pages_recovered_by_rule.jsonl", recovered)
    results["losses"], rows = step("losses", lambda: S.build_losses(ctx, st))
    util.write_jsonl(OUT_A1 / "build_losses.jsonl", rows)
    results["new_films"] = S.new_film_estimate(list(util.iter_jsonl(OUT_A1 / "ml_missing_classified.jsonl")),
                                               list(util.iter_jsonl(OUT_A1 / "italian_pages_classified.jsonl")))
    util.write_json(OUT_A1 / "results.json", results)
    print("results ->", OUT_A1 / "results.json")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["stage", "run", "reconcile", "report", "v3compare", "v3report"])
    args = ap.parse_args(argv)
    ctx = Context(util.OUT_DIR)
    if args.command == "stage":
        cmd_stage(ctx)
    elif args.command == "run":
        cmd_run(ctx)
    elif args.command == "v3compare":
        from . import v3_compare
        d = v3_compare.compare(util.CINEMA_DB, util.ROOT / "cinema_db/data/cinema.v3.sqlite3")
        util.write_json(OUT_A1 / "v3_compare.json", d)
        print("v3_compare.json written")
    elif args.command == "v3report":
        from . import v3_report
        v3_report.write()
    elif args.command == "reconcile":
        from . import reconcile
        print(json.dumps(reconcile.run(ctx, STAGING, OUT_A1), indent=1))
    else:
        from . import a1_report
        a1_report.write(OUT_A1 / "results.json", REPORT_A1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
