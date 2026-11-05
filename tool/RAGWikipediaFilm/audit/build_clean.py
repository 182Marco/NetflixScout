"""Phase 6: build the CLEAN catalogue from the untouched Phase 1 dataset. Deterministic, offline, reversible.

    python -m tool.RAGWikipediaFilm.audit.build_clean build     # writes data/clean/{films.clean.jsonl, excluded.jsonl, clean_manifest.json}
    python -m tool.RAGWikipediaFilm.audit.build_clean verify    # rebuilds in memory; compares byte for byte with the files and checks reversibility

Inputs (read-only): data/processed/films.jsonl, audit/exclusions.json (the 259 certain non-films), data/audit/section_fix.jsonl
(corrected plots of the 25 contaminated pages), data/audit/classification.jsonl (to flag the doubtful records) and
audit/plan_overrides.json (decisions the owner approves later: extra exclusions, records taken back, extra unverified flags).

Nothing in data/processed or data/embeddings is written. `films.jsonl` is the source of truth: clean + excluded, with the 25 plots put
back, reproduce it exactly (that is what `verify` checks). No network, no API."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/processed/films.jsonl"
EXCLUSIONS = ROOT / "audit/exclusions.json"
SECTION_FIX = ROOT / "data/audit/section_fix.jsonl"
CLASSIFICATION = ROOT / "data/audit/classification.jsonl"
OVERRIDES = ROOT / "audit/plan_overrides.json"
OUT = ROOT / "data/clean"
VERSION = 1

# Manual plot exceptions: the automatic cut is wrong for these pages (see PHASE6_REPORT).
# Nero-Fumo e i sette nani neri: the section called "Trama" comes AFTER the production text, so the plot is the five paragraphs
# between these two markers of the current synopsis.
MANUAL_PLOT = {
    "Q3821447": ("Il corto si apre con la sagoma di una donna", "Nel gennaio del 1943, la stampa cinematografica"),
}


def _dumps(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tidy(text: str) -> str:
    """Markup left over by the Phase 1 cleaner in the corrected plots: references and stray wiki italics (two quotes in a row)."""
    text = re.sub(r"<ref[^>]*?/>|<ref[^>]*>.*?</ref>", "", text, flags=re.S)
    text = re.sub(r"<ref[^>]*>[^\n]*", "", text)                  # a reference the cleaner left open
    text = re.sub(r"'{2,}", "", text).strip()
    return re.sub(r"\n+[^\n]*:\s*$", "", text)               # a closing line that introduced a quotation the cleaner dropped


def manual_plot(film: dict) -> str:
    start, end = MANUAL_PLOT[film["film_id"]]
    s = film["synopsis"]
    i, j = s.find(start), s.find(end)
    if i < 0 or j <= i:
        raise ValueError(f"manual plot markers not found for {film['film_id']}")
    return s[i:j].strip()


def load_plan(overrides_path: Path | None = None) -> dict:
    ex = json.loads(EXCLUSIONS.read_text())["records"]
    overrides_path = overrides_path or OVERRIDES
    ov = json.loads(overrides_path.read_text()) if overrides_path.exists() else {}
    excluded = {r["film_id"]: {"verdict": r["verdict"], "subtype": r["subtype"], "reasons": r["reasons"], "source": "phase4_certain"}
                for r in ex}
    for fid in ov.get("reinstate", []):
        excluded.pop(fid, None)
    for item in ov.get("extra_exclude", []):
        excluded[item["film_id"]] = {"verdict": "approved", "subtype": item.get("subtype", ""), "reasons": [item["reason"]],
                                     "source": "owner_approved"}
    doubtful = {json.loads(l)["film_id"] for l in CLASSIFICATION.open() if json.loads(l)["verdict"] == "doubtful"}
    unverified = (doubtful | set(ov.get("extra_unverified", []))) - set(excluded) - set(ov.get("mark_verified", []))
    fixes = {}
    for line in SECTION_FIX.open():
        d = json.loads(line)
        fixes[int(d["page_id"])] = d["synopsis"]
    return {"excluded": excluded, "unverified": unverified, "fixes": fixes, "overrides_sha": _sha(overrides_path.read_bytes()) if overrides_path.exists() else None}


def build_rows(plan: dict | None = None) -> tuple[list[str], list[str], dict]:
    plan = plan or load_plan()
    clean, excluded = [], []
    fixed_ids: list[str] = []
    for line in SOURCE.open(encoding="utf-8"):
        film = json.loads(line)
        fid = film["film_id"]
        if fid in plan["excluded"]:
            excluded.append(_dumps({"film": film, "exclusion": plan["excluded"][fid]}) + "\n")
            continue
        row = dict(film)
        row["synopsis_original_sha256"] = None
        if fid in MANUAL_PLOT:
            row["synopsis_original_sha256"] = _sha(film["synopsis"].encode())
            row["synopsis"] = manual_plot(film)
        elif film["wikipedia_page_id"] in plan["fixes"]:
            row["synopsis_original_sha256"] = _sha(film["synopsis"].encode())
            row["synopsis"] = tidy(plan["fixes"][film["wikipedia_page_id"]])
        if row["synopsis_original_sha256"]:
            fixed_ids.append(fid)
        row["catalog_status"] = "unverified" if fid in plan["unverified"] else "verified"
        clean.append(_dumps(row) + "\n")
    stats = {"records_clean": len(clean), "records_excluded": len(excluded), "plots_corrected": len(fixed_ids),
             "unverified": sum(1 for r in clean if '"catalog_status":"unverified"' in r), "corrected_ids": sorted(fixed_ids)}
    return clean, excluded, stats


def manifest(clean: list[str], excluded: list[str], stats: dict, plan: dict) -> dict:
    return {"version": VERSION, **{k: v for k, v in stats.items() if k != "corrected_ids"}, "corrected_ids": stats["corrected_ids"],
            "source_sha256": _sha(SOURCE.read_bytes()), "exclusions_sha256": _sha(EXCLUSIONS.read_bytes()),
            "section_fix_sha256": _sha(SECTION_FIX.read_bytes()), "overrides_sha256": plan["overrides_sha"],
            "clean_sha256": _sha("".join(clean).encode()), "excluded_sha256": _sha("".join(excluded).encode())}


def reports(clean: list[str], excluded: list[str]) -> dict[str, str]:
    """Human-readable companions of the clean dataset, built only from the rows (so they are deterministic too)."""
    cls = {}
    for line in CLASSIFICATION.open():
        d = json.loads(line)
        cls[d["film_id"]] = d
    unverified, corrections, by_cat = [], [], {}
    for line in clean:
        r = json.loads(line)
        c = cls.get(r["film_id"], {})
        key = f"{c.get('verdict', '?')}/{c.get('subtype', '?')}"
        by_cat[key] = by_cat.get(key, 0) + 1
        if r["catalog_status"] == "unverified":
            unverified.append({"film_id": r["film_id"], "title": r["title"], "year": r["year"], "category": key,
                               "audit_reasons": c.get("reasons", [])[-2:]})
        if r["synopsis_original_sha256"]:
            corrections.append({"film_id": r["film_id"], "title": r["title"], "original_sha256": r["synopsis_original_sha256"],
                                "new_sha256": _sha(r["synopsis"].encode()), "new_chars": len(r["synopsis"]),
                                "manual_exception": r["film_id"] in MANUAL_PLOT})
    excl, ex_by_cat = [], {}
    for line in excluded:
        d = json.loads(line)
        key = f"{d['exclusion']['verdict']}/{d['exclusion']['subtype']}"
        ex_by_cat[key] = ex_by_cat.get(key, 0) + 1
        excl.append({"film_id": d["film"]["film_id"], "title": d["film"]["title"], "year": d["film"]["year"], "category": key,
                     "source": d["exclusion"]["source"], "reasons": d["exclusion"]["reasons"]})
    dump = lambda o: json.dumps(o, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    return {"unverified.json": dump({"count": len(unverified), "records": unverified}),
            "corrections.json": dump({"count": len(corrections), "records": corrections}),
            "excluded_list.json": dump({"count": len(excl), "records": excl}),
            "category_counts.json": dump({"included_by_audit_category": by_cat, "excluded_by_category": ex_by_cat})}


def build() -> dict:
    plan = load_plan()
    clean, excluded, stats = build_rows(plan)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "films.clean.jsonl").write_text("".join(clean), encoding="utf-8")
    (OUT / "excluded.jsonl").write_text("".join(excluded), encoding="utf-8")
    extra = reports(clean, excluded)
    for name, text in extra.items():
        (OUT / name).write_text(text, encoding="utf-8")
    m = manifest(clean, excluded, stats, plan)
    m["report_sha256"] = {name: _sha(text.encode()) for name, text in sorted(extra.items())}
    (OUT / "clean_manifest.json").write_text(json.dumps(m, indent=2, sort_keys=True) + "\n")
    return m


def reverse_check(clean_path: Path, excluded_path: Path, source_path: Path | None = None) -> list[str]:
    """Rebuild the original dataset from clean + excluded (original plots come back from the excluded copies and, for the
    corrected plots, from the source via the stored hash). Returns the list of problems (empty = reversible)."""
    problems = []
    source_path = source_path or SOURCE
    src = {json.loads(l)["film_id"]: l for l in source_path.open(encoding="utf-8")}
    seen = set()
    for line in clean_path.open(encoding="utf-8"):
        row = json.loads(line)
        fid = row["film_id"]
        seen.add(fid)
        orig = json.loads(src[fid])
        if row["synopsis_original_sha256"] is not None and _sha(orig["synopsis"].encode()) != row["synopsis_original_sha256"]:
            problems.append(f"{fid}: original plot hash differs")
        for k in orig:
            if k != "synopsis" and row.get(k) != orig[k]:
                problems.append(f"{fid}: field {k} changed")
        if row["synopsis_original_sha256"] is None and row["synopsis"] != orig["synopsis"]:
            problems.append(f"{fid}: plot changed without a recorded hash")
    for line in excluded_path.open(encoding="utf-8"):
        d = json.loads(line)
        seen.add(d["film"]["film_id"])
        if _dumps(d["film"]) + "\n" != src[d["film"]["film_id"]]:
            problems.append(f"{d['film']['film_id']}: excluded copy differs from the source")
    if seen != set(src):
        problems.append(f"coverage: {len(set(src) - seen)} source records missing, {len(seen - set(src))} unknown")
    return problems


def verify() -> list[str]:
    plan = load_plan()
    clean, excluded, stats = build_rows(plan)
    problems = []
    for name, rows in (("films.clean.jsonl", clean), ("excluded.jsonl", excluded)):
        if (OUT / name).read_bytes() != "".join(rows).encode():
            problems.append(f"{name} is not what the plan produces")
    extra = reports(clean, excluded)
    for name, text in extra.items():
        if (OUT / name).read_bytes() != text.encode():
            problems.append(f"{name} is not what the plan produces")
    expected = manifest(clean, excluded, stats, plan)
    expected["report_sha256"] = {name: _sha(text.encode()) for name, text in sorted(extra.items())}
    if json.loads((OUT / "clean_manifest.json").read_text()) != expected:
        problems.append("clean_manifest.json is out of date")
    return problems + reverse_check(OUT / "films.clean.jsonl", OUT / "excluded.jsonl")


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "build"
    if cmd == "build":
        m = build()
        print({k: m[k] for k in ("records_clean", "records_excluded", "plots_corrected", "unverified")})
        return 0
    if cmd == "verify":
        problems = verify()
        print("OK: clean dataset reproduces byte for byte and is reversible" if not problems else "\n".join(problems[:20]))
        return 1 if problems else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
