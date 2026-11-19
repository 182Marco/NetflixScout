#!/usr/bin/env python3
"""Where are you in docs/REBUILD.md? A read-only report: which stages are done, what is missing, and the next command to run.

    python scripts/rebuild_status.py            # a table, then the next command
    python scripts/rebuild_status.py --json     # the same as JSON
    python scripts/rebuild_status.py --strict   # exit code 1 unless every stage is done

It only looks at files and counts rows. It never calls an API, never costs anything and never reads `.env` (it only checks that the file exists).
The one network access is a GET to the LOCAL Qdrant server to read the point counts of the two collections (VECTORSTORE_QDRANT_URL or
http://127.0.0.1:6333); if the server is down the Qdrant checks are reported as not running.
"""
from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILMS_COLLECTION = "wikipedia_films_it_v3"
SERIES_COLLECTION = "wikipedia_series_it_v1"
MOVIELENS = {"movies": 87_585, "ratings": 32_000_204, "tags": 2_000_066}  # MovieLens 32M is static: these never change
IMDB_DATASETS = ("title.basics", "name.basics", "title.principals", "title.crew", "title.ratings", "title.episode")
IMDB_DIR = "cinema_db/data/imdb_snapshot/2026-11-08"  # the folder name the layer build looks for (docs/REBUILD.md, stage 4.3)
PACKAGES = ("yaml", "mwparserfromhell", "tiktoken", "qdrant_client", "openai", "sqlglot", "pydantic", "numpy", "fastapi")
DONE, PARTIAL, TODO = "done", "partial", "todo"


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    fix: str = ""  # the command (or action) that makes this check pass


@dataclass
class Stage:
    key: str
    title: str
    checks: list[Check] = field(default_factory=list)

    @property
    def status(self) -> str:
        oks = [c.ok for c in self.checks]
        return DONE if oks and all(oks) else PARTIAL if any(oks) else TODO

    @property
    def next(self) -> str:
        return next((c.fix for c in self.checks if not c.ok and c.fix), "")


# ---------------------------------------------------------------- readers (all read-only)

def count_lines(path: Path) -> int:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as fh:
        return sum(1 for _ in fh)


def qdrant_points(url: str, name: str) -> int | None:
    """Point count of a collection on the local server, None when the server is down or the collection does not exist."""
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/collections/{name}", timeout=3) as r:  # noqa: S310 (a local URL)
            return int(json.load(r)["result"]["points_count"])
    except (urllib.error.URLError, OSError, KeyError, ValueError, TypeError):
        return None


def qdrant_up(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/collections", timeout=3):  # noqa: S310
            return True
    except (urllib.error.URLError, OSError):
        return False


def sqlite_scalar(path: Path, sql: str):
    if not path.is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    except sqlite3.Error:
        return None
    try:
        row = conn.execute(sql).fetchone()
        return row[0] if row else None
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def has(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def files_in(path: Path, pattern: str) -> int:
    return len(list(path.glob(pattern))) if path.is_dir() else 0


def expected_digest(root: Path) -> str | None:
    """The digest pinned in cinema_db/harness/candidate.py (read as text: no import of project code)."""
    f = root / "cinema_db/harness/candidate.py"
    m = re.search(r'"content_sha256":\s*"([0-9a-f]{64})"', f.read_text(encoding="utf-8")) if f.is_file() else None
    return m.group(1) if m else None


# ---------------------------------------------------------------- stages

def stage0(root: Path, url: str) -> Stage:
    s = Stage("0", "Environment and Qdrant")
    s.checks.append(Check("python >= 3.11", sys.version_info >= (3, 11), sys.version.split()[0], "install Python 3.11 and recreate .venv"))
    missing = [p for p in PACKAGES if importlib.util.find_spec(p) is None]
    s.checks.append(Check("packages", not missing, "all importable" if not missing else "missing: " + ", ".join(missing),
                          "pip install -r requirements-pipelines.txt pytest"))
    binary = os.environ.get("QDRANT_BIN") or (str(root / "bin/qdrant") if (root / "bin/qdrant").is_file() else shutil.which("qdrant"))
    s.checks.append(Check("Qdrant binary", bool(binary), binary or "not found", "put the Qdrant 1.20.0 binary in bin/qdrant (see docs/REBUILD.md, stage 0)"))
    s.checks.append(Check("Qdrant running", qdrant_up(url), url, "./scripts/start_qdrant.sh"))
    s.checks.append(Check(".env exists", (root / ".env").is_file(), "(contents are never read)", "cp .env.example .env and fill OPENAI_API_KEY"))
    return s


def stage1(root: Path, url: str, dump_date: str) -> Stage:
    f = root / "pipelines/wikipedia_films"
    d = f / "data"
    dump = d / "raw" / f"itwiki-{dump_date}-pages-articles.xml.bz2"
    s = Stage("1", "Films: wikipedia_films_it_v3")
    pipe = f"python -m pipelines.wikipedia_films.pipeline --set dump.date={dump_date}"
    s.checks += [
        Check("dump downloaded", has(dump) and not dump.with_name(dump.name + ".part").exists(), dump.name, f"{pipe} download"),
        Check("films.jsonl (extract + enrich)", has(d / "processed/films.jsonl"), "", f"{pipe} extract ; {pipe} --set wikidata.mode=online enrich"),
        Check("build manifest", has(f / "manifests/build_manifest.json"), "", f"{pipe} manifest"),
        Check("audit inputs", has(d / "audit/section_fix.jsonl") and has(d / "audit/classification.jsonl"), "",
              "python -m pipelines.wikipedia_films.audit.section_scan ; python -m pipelines.wikipedia_films.audit.run_audit ; git checkout -- pipelines/wikipedia_films/audit"),
        Check("clean catalogue", has(d / "clean/films.clean.jsonl"), "", "python -m pipelines.wikipedia_films.audit.build_clean build"),
    ]
    v3 = d / "clean_v3/films.v3.jsonl"
    n = count_lines(v3) if has(v3) else 0
    s.checks.append(Check("v3 catalogue", n > 0, f"{n} films" if n else "", "python -m pipelines.wikipedia_films.audit.build_v3 build"))
    emb = d / "embeddings"
    have_vectors = files_in(emb / "itwiki-20261101-large1536/shards", "shard_*.npz") > 0 or has(emb / "itwiki-20261101-large1536-v3/new_vectors.npz")
    points = qdrant_points(url, FILMS_COLLECTION)
    s.checks.append(Check("vectors", have_vectors or points is not None, "Phase 3 shards or new_vectors.npz" if have_vectors else "",
                          "FILMS_EMBED_AUTHORIZED=yes python -m pipelines.wikipedia_films.indexing.v3 embed   (read the `plan` first)"))
    ok = points is not None and n > 0 and points == n
    detail = "Qdrant not running or collection missing" if points is None else f"{points} points" + ("" if points == n or not n else f" (catalogue: {n})")
    s.checks.append(Check(f"collection {FILMS_COLLECTION}", ok, detail,
                          "python -m pipelines.wikipedia_films.indexing.v3 index ; python -m pipelines.wikipedia_films.indexing.v3 check"))
    return s


def stage2(root: Path, url: str, dump_date: str) -> Stage:
    d = root / "pipelines/wikipedia_series/data"
    s = Stage("2", "Series: wikipedia_series_it_v1")
    m = "python -m pipelines.wikipedia_series"
    dump = root / "pipelines/wikipedia_films/data/raw" / f"itwiki-{dump_date}-pages-articles.xml.bz2"
    s.checks += [
        Check("dump (from stage 1)", has(dump), dump.name, "complete stage 1 first"),
        Check("dump scan + harvest", files_in(d / "phase0/full", "scan_*.jsonl") > 0, "", f"{m}.phase0.scan_dump ; {m}.phase0.harvest ; {m}.harvest_animation"),
        Check("extraction (S1)", has(d / "s1/series.jsonl"), "", f"{m}.extract_series"),
        Check("Wikidata snapshot (S2)", (d / "cache/wikidata/itwiki-20261101-series-a").is_dir(), "", f"{m}.enrich_wikidata"),
        Check("clean catalogue (S5)", has(d / "s5/series.jsonl") and has(d / "s5/manifest.json"), "",
              f"{m}.build_relations ; {m}.audit_series ; {m}.build_clean build ; {m}.check_catalog ; {m}.build_clean verify"),
    ]
    units = d / "s6/units.jsonl.gz"
    n = count_lines(units) if has(units) else 0
    s.checks.append(Check("embedding units (S6)", n > 0, f"{n} units" if n else "", f"{m}.embedding_units"))
    shards = files_in(d / "s7/shards", "*.npz")
    s.checks.append(Check("vectors (S7)", shards > 0, f"{shards} shards" if shards else "",
                          f"{m}.embed plan ; SERIES_EMBED_AUTHORIZED=yes {m}.embed run ; {m}.embed verify"))
    points = qdrant_points(url, SERIES_COLLECTION)
    detail = "Qdrant not running or collection missing" if points is None else f"{points} points" + ("" if points == n or not n else f" (units: {n})")
    s.checks.append(Check(f"collection {SERIES_COLLECTION}", points is not None and n > 0 and points == n, detail, f"{m}.index plan ; {m}.index build ; {m}.index check"))
    return s


def stage3(root: Path) -> Stage:
    raw = root / "movie_db/data/raw/ml-32m"
    db = root / "movie_db/data/movielens32m.sqlite3"
    s = Stage("3", "MovieLens")
    missing = [f for f in ("movies.csv", "ratings.csv", "tags.csv", "links.csv") if not has(raw / f)]
    s.checks.append(Check("CSV files", not missing, "ml-32m complete" if not missing else "missing: " + ", ".join(missing),
                          "curl -O https://files.grouplens.org/datasets/movielens/ml-32m.zip, unzip it into movie_db/data/raw/"))
    got = {}
    if has(db):
        got = {"movies": sqlite_scalar(db, "SELECT count(*) FROM movies"), "ratings": sqlite_scalar(db, "SELECT sum(n_ratings) FROM movie_stats"),
               "tags": sqlite_scalar(db, "SELECT count(*) FROM tags")}
    ok = got == MOVIELENS
    s.checks.append(Check("movielens32m.sqlite3", ok, ", ".join(f"{k} {v}" for k, v in got.items()) if got else "",
                          "python -m movie_db.harness.ingestion.build"))
    return s


def stage4(root: Path) -> Stage:
    c = root / "cinema_db/data"
    s = Stage("4", "cinema_db")
    f = "python -m cinema_db.harness"
    s.checks.append(Check("Wikidata phase-4 requests", has(c / "wikidata_phase4/plan.json"), "", f"{f}.enrich.fetch plan ; {f}.enrich.fetch run --category <each>"))
    s.checks.append(Check("base catalogue (schema 2)", has(c / "cinema.sqlite3"), "", f"{f}.build.build --force"))
    snap = root / IMDB_DIR
    miss = [d for d in IMDB_DATASETS if not has(snap / f"{d}.tsv.gz")]
    s.checks.append(Check("IMDb datasets", has(snap / "manifest.json") and not miss, f"missing: {', '.join(miss)}" if miss else "",
                          f"{f}.acquire.imdb fetch <dataset> --dir {IMDB_DIR}   (each of the six)"))
    s.checks.append(Check("A0 audit", has(c / "audit_a0/dump_scan.jsonl"), "", f"{f}.audit.run_audit targets ; ... scan ; ... run"))
    s.checks.append(Check("IMDb staging", has(c / "audit_a1/imdb_staging.sqlite3"), "", f"{f}.audit.run_a1 stage"))
    final = c / "cinema.v4.candidate6.sqlite3"
    version = sqlite_scalar(final, "SELECT value FROM build_info WHERE key='schema_version'") if has(final) else None
    s.checks.append(Check("schema-4 database", version == "4", f"schema_version {version}" if version else "",
                          f"{f}.build.imdb_layer --movielens --out cinema_db/data/cinema.v4.candidate6.sqlite3"))
    return s


def build_report(root: Path = ROOT, url: str | None = None, dump_date: str | None = None) -> list[Stage]:
    url = url or os.environ.get("VECTORSTORE_QDRANT_URL") or "http://127.0.0.1:6333"
    dump_date = dump_date or os.environ.get("ITWIKI_DUMP_DATE") or "20261101"
    stages = [stage0(root, url), stage1(root, url, dump_date), stage2(root, url, dump_date), stage3(root), stage4(root)]
    final = Stage("5", "Run")
    ready = all(s.status == DONE for s in stages)
    digest = sqlite_scalar(root / "cinema_db/data/cinema.v4.candidate6.sqlite3", "SELECT value FROM build_info WHERE key='content_sha256'")
    pinned = expected_digest(root)
    final.checks.append(Check("all stages done", ready, "", "complete the first stage that is not done"))
    if ready and digest and pinned and digest != pinned:
        final.checks.append(Check("evaluation scripts", True, f"database digest differs from candidate.py: set EXPECTED['content_sha256'] to {digest[:16]}... to use them", ""))
    final.checks.append(Check("start check", ready, "", "./scripts/start_integrated.sh --check ; python app.py"))
    return stages + [final]


def render(stages: list[Stage]) -> str:
    mark = {DONE: "[done]   ", PARTIAL: "[partial]", TODO: "[todo]   "}
    lines = []
    for s in stages:
        lines.append(f"{mark[s.status]} Stage {s.key}: {s.title}")
        for c in s.checks:
            lines.append(f"      {'ok ' if c.ok else '-- '} {c.name}" + (f": {c.detail}" if c.detail else ""))
    nxt = next(((s, s.next) for s in stages if s.status != DONE and s.next), None)
    lines.append("")
    lines.append(f"Next (stage {nxt[0].key}): {nxt[1]}" if nxt else "Every stage is done.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", type=Path, default=ROOT, help="repository root (default: this repository)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--strict", action="store_true", help="exit 1 unless every stage is done")
    a = p.parse_args(argv)
    stages = build_report(a.root)
    if a.json:
        print(json.dumps([{**asdict(s), "status": s.status, "next": s.next} for s in stages], indent=1))
    else:
        print(render(stages))
    return 1 if a.strict and any(s.status != DONE for s in stages) else 0


if __name__ == "__main__":
    sys.exit(main())
