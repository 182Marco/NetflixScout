"""v3 catalogue: the Phase 6 clean dataset rebuilt with the decisions of 2026-11-04 plus the fields the new retriever needs.

    python -m tool.RAGWikipediaFilm.audit.build_v3 build     # writes data/clean_v3/{films.v3.jsonl, build_v3_manifest.json}
    python -m tool.RAGWikipediaFilm.audit.build_v3 verify    # rebuilds in memory, compares byte for byte, checks it against the v2 clean file

`data/clean/` (the input of the v2 collection) is NOT touched. New fields per film: work_format, format_confidence, franchise_id,
franchise_ids, franchise_size, franchise_basis, title/actor/director/original-title/genre normalised forms. Offline, no API."""
from __future__ import annotations

import hashlib
import json
import sys
import unicodedata
import re
from collections import Counter
from pathlib import Path

from . import build_clean as B
from . import franchise as FR

ROOT = B.ROOT
OVERRIDES_V3 = ROOT / "audit/plan_overrides_v3.json"
OUT = ROOT / "data/clean_v3"
VERSION = 3
AFTERSHOCK = "Q2421745"
MANUAL_FORMAT = {AFTERSHOCK: ("tv_film", "manual")}
FILM_FORMATS = {"feature", "short", "animated", "tv_film", "silent", "tv_special", "video_film", "music_film", "serial", "documentary",
                "unreleased", "unknown"}
TV_RELATED = {"manga", "ova", "anime", "anime_series", "anime_film_series", "miniseries", "tv_programme", "tv_series", "title_marks_series"}


def norm(text: str | None) -> str:
    t = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", t.lower())).strip()


def work_format(film_id: str, cls: dict | None, unverified: bool) -> tuple[str, str]:
    if film_id in MANUAL_FORMAT:
        return MANUAL_FORMAT[film_id]
    if not cls:
        return "unknown", "low"
    verdict, sub, conf = cls["verdict"], cls["subtype"], cls["confidence"]
    if verdict == "film" and sub in FILM_FORMATS:
        fmt = sub
    elif sub in FILM_FORMATS and verdict == "doubtful":
        fmt, conf = sub, "low"
    elif sub in TV_RELATED:
        fmt, conf = "tv_related", "low"
    else:
        fmt, conf = "other", "low"
    if unverified and conf != "manual":
        conf = "low"
    return fmt, conf


def enrich(row: dict, cls: dict | None, fr: dict | None) -> dict:
    fmt, conf = work_format(row["film_id"], cls, row["catalog_status"] == "unverified")
    row["work_format"], row["format_confidence"] = fmt, conf
    f = fr or {}
    row["franchise_id"] = f.get("franchise_id")
    row["franchise_ids"] = f.get("franchise_ids", [])
    row["franchise_size"] = f.get("franchise_size")
    row["franchise_basis"] = f.get("franchise_basis")
    row["actor_names_norm"] = sorted({norm(a["name"]) for a in row.get("actors", []) if a.get("name")})
    row["director_names_norm"] = sorted({norm(d["name"]) for d in row.get("director", []) if d.get("name")})
    row["original_title_norm"] = norm(row.get("original_title"))
    row["genres_norm"] = sorted({norm(g) for g in row.get("genres", []) if g})
    return row


def build_rows() -> tuple[list[str], dict]:
    plan = B.load_plan(OVERRIDES_V3)
    clean, excluded, stats = B.build_rows(plan)
    cls = {}
    for line in B.CLASSIFICATION.open(encoding="utf-8"):
        d = json.loads(line)
        cls[d["film_id"]] = d
    rows = [json.loads(l) for l in clean]
    films = {r["film_id"]: {"year": r.get("year"), "title": r["title"]} for r in rows}
    links = FR.read_links(set(films))
    fr = FR.assign(films, links)
    out = [B._dumps(enrich(r, cls.get(r["film_id"]), fr.get(r["film_id"]))) + "\n" for r in rows]
    summary = {
        "records": len(out), "excluded": len(excluded), "plots_corrected": stats["plots_corrected"],
        "unverified": stats["unverified"], "with_franchise": sum(1 for r in rows if fr.get(r["film_id"])),
        "work_format": dict(Counter(json.loads(l)["work_format"] for l in out)),
        "format_confidence": dict(Counter(json.loads(l)["format_confidence"] for l in out)),
        "franchise_basis": dict(Counter(str(json.loads(l)["franchise_basis"]) for l in out)),
        "overrides_sha256": plan["overrides_sha"], "source_sha256": B._sha(B.SOURCE.read_bytes()),
        "classification_sha256": B._sha(B.CLASSIFICATION.read_bytes()),
        "films_sha256": B._sha("".join(out).encode()), "version": VERSION,
    }
    return out, summary


def build() -> dict:
    rows, summary = build_rows()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "films.v3.jsonl").write_text("".join(rows), encoding="utf-8")
    (OUT / "build_v3_manifest.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def verify() -> list[str]:
    problems = []
    rows, summary = build_rows()
    if (OUT / "films.v3.jsonl").read_bytes() != "".join(rows).encode():
        problems.append("films.v3.jsonl is not what the plan produces")
    if json.loads((OUT / "build_v3_manifest.json").read_text()) != summary:
        problems.append("build_v3_manifest.json is out of date")
    v2 = {json.loads(l)["film_id"]: json.loads(l) for l in (B.OUT / "films.clean.jsonl").open(encoding="utf-8")}
    v3 = {json.loads(l)["film_id"]: json.loads(l) for l in rows}
    if set(v3) - set(v2) != {AFTERSHOCK} or set(v2) - set(v3):
        problems.append(f"difference with v2 clean is not exactly Aftershock: +{sorted(set(v3) - set(v2))} -{sorted(set(v2) - set(v3))}")
    for fid, r in v2.items():
        for k, v in r.items():
            if v3[fid].get(k) != v:
                problems.append(f"{fid}: original field {k} differs from v2 clean")
                break
    src = {json.loads(l)["film_id"]: json.loads(l) for l in B.SOURCE.open(encoding="utf-8")}
    a = v3.get(AFTERSHOCK)
    if a is None or a["synopsis"] != src[AFTERSHOCK]["synopsis"] or a["catalog_status"] != "verified":
        problems.append("Aftershock is missing, altered or not verified")
    return problems


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "build"
    if cmd == "build":
        print(json.dumps(build(), indent=1))
        return 0
    if cmd == "verify":
        p = verify()
        print("OK: v3 catalogue reproduces byte for byte and differs from v2 only by Aftershock and the new fields" if not p else "\n".join(p[:20]))
        return 1 if p else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
