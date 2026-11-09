"""Offline comparison of two semantic runs of the RAGs (FASE 19I). No model, no network, nothing is written.

    python -m movie_db.harness.evaluation.compare_rag_runs --old full --new full2

For every case: the top-3 titles of each run and whether they are the same IN THE SAME ORDER. A cell of the manual review (case, position 1-3) must be graded
again when the title at that position changed; a cell whose title is unchanged keeps the grade already registered in `review.md`. No judgement is made here."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
RUNS = ROOT / "cinema_db/data/rag_semantic"
TOP = 3


def load(label: str) -> dict[str, dict[str, Any]]:
    return {r["id"]: r for r in map(json.loads, (RUNS / label / "run.jsonl").open())}


def _titles(row: dict[str, Any] | None) -> list[str]:
    return [i["title"] for i in (row or {}).get("items", [])[:TOP]]


def compare(old: dict[str, dict[str, Any]], new: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Pure. `cells_to_regrade`: [case, position] where the title differs; `unchanged_cells`: keep their old grade; `missing`: cases absent from the new run."""
    cases: dict[str, Any] = {}
    regrade: list[list[Any]] = []
    unchanged = 0
    for cid, o in old.items():
        n = new.get(cid)
        to, tn = _titles(o), _titles(n)
        changed = [p for p in range(1, max(len(to), len(tn)) + 1) if (to[p - 1] if p <= len(to) else None) != (tn[p - 1] if p <= len(tn) else None)]
        graded_positions = range(1, len(to) + 1)           # only the cells that exist in the registered review (old top 3)
        cells = [[cid, p] for p in changed if p in graded_positions or p <= len(tn)]
        if n is not None:
            regrade += cells
            unchanged += sum(1 for p in graded_positions if p not in changed)
        cases[cid] = {"status": "MISSING" if n is None else "IDENTICAL" if not changed else "CHANGED", "old": to, "new": tn if n else None,
                      "grade_old": (o.get("grade") or {}).get("valid"), "grade_new": ((n or {}).get("grade") or {}).get("valid")}
    return {"cases": cases, "cells_to_regrade": regrade, "unchanged_cells": unchanged, "missing": [c for c, v in cases.items() if v["status"] == "MISSING"],
            "new_only": [c for c in new if c not in old]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--old", required=True)
    ap.add_argument("--new", required=True)
    a = ap.parse_args(argv)
    out = compare(load(a.old), load(a.new))
    for cid, c in out["cases"].items():
        print(f"{cid:4} {c['status']:9} auto-verdict {c['grade_old']} -> {c['grade_new']}")
        if c["status"] == "CHANGED":
            for p, (x, y) in enumerate(zip(c["old"] + [None] * TOP, (c["new"] or []) + [None] * TOP), 1):
                if p <= TOP and x != y:
                    print(f"       #{p}: {x!r} -> {y!r}")
    print(f"\ncells to grade again: {len(out['cells_to_regrade'])}  (unchanged cells keep their registered grade: {out['unchanged_cells']})")
    print("cases to grade again:", sorted({c for c, _ in out["cells_to_regrade"]}))
    if out["missing"]:
        print("missing in the new run:", out["missing"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
