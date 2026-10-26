"""Check the completeness and coherence of a captured baseline; print a reproducible summary.

    python docs/qdrant_migration/verify_baseline.py --baseline DIR [--queries FILE] [--summary FILE]

Read-only. Thresholds are NOT applied here (see protocol.md); this only reports what was captured:
recall of Chroma's own top-k against the exact top-k and the signals the parser extracted.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

REQUIRED = ("signals", "embedded_text", "exact_top50", "chroma_raw_top50",
            "retrieve_semantic", "retrieve_hybrid", "rerank_query", "final_top")


def recall(approx: list[dict], exact: list[dict], k: int) -> float:
    truth = {r["id"] for r in exact[:k]}
    return len(truth & {r["id"] for r in approx[:k]}) / k


def check(record: dict, vector: np.ndarray | None) -> list[str]:
    problems = [f"missing {key}" for key in REQUIRED if key not in record]
    if problems:
        return problems
    if not record["embedded_text"].strip() or not record["signals"].get("semantic_query", "").strip():
        problems.append("empty semantic_query")
    if len(record["exact_top50"]) != 50 or len(record["chroma_raw_top50"]) != 50:
        problems.append("top-50 incomplete")
    for key in ("retrieve_semantic", "retrieve_hybrid"):
        if not record[key]:
            problems.append(f"{key} empty")
    if not record["final_top"]:
        problems.append("final_top empty")
    if vector is None or vector.shape != (1536,):
        problems.append("query vector missing or not 1536-dim")
    exact_scores = [r["score"] for r in record["exact_top50"]]
    if exact_scores != sorted(exact_scores, reverse=True):
        problems.append("exact scores not descending")
    if not {r["id"] for r in record["final_top"]} <= {r["id"] for r in record["retrieve_semantic"]}:
        problems.append("final_top not a subset of the semantic pool")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--queries", default=str(Path(__file__).with_name("queries.json")))
    parser.add_argument("--summary")
    args = parser.parse_args()

    base = Path(args.baseline)
    queries = json.loads(Path(args.queries).read_text(encoding="utf-8"))
    lines = [f"{'id':4} {'status':8} {'r@10':>5} {'r@50':>5} {'sem':>3} {'hyb':>3} {'fin':>3}  semantic_query"]
    complete = partial = failed = 0
    for item in queries:
        path = base / f"{item['id']}.json"
        if not path.exists():
            failed += 1
            lines.append(f"{item['id']:4} FAILED   (no result file)")
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        vec_path = base / f"{item['id']}.vec.npy"
        vector = np.load(vec_path) if vec_path.exists() else None
        problems = check(record, vector)
        if problems and any(p.startswith("missing") for p in problems):
            failed += 1
            lines.append(f"{item['id']:4} FAILED   {'; '.join(problems)}")
            continue
        status = "partial" if problems else "complete"
        partial += bool(problems)
        complete += not problems
        r10 = recall(record["chroma_raw_top50"], record["exact_top50"], 10)
        r50 = recall(record["chroma_raw_top50"], record["exact_top50"], 50)
        lines.append(
            f"{item['id']:4} {status:8} {r10:5.2f} {r50:5.2f} {len(record['retrieve_semantic']):3d} "
            f"{len(record['retrieve_hybrid']):3d} {len(record['final_top']):3d}  "
            f"{record['embedded_text'][:70]}" + (f"  !! {'; '.join(problems)}" if problems else "")
        )
    lines.append(f"\ncomplete={complete} partial={partial} failed={failed} total={len(queries)}")
    text = "\n".join(lines)
    print(text)
    if args.summary:
        Path(args.summary).write_text(text + "\n", encoding="utf-8")
    return 0 if complete == len(queries) else 1


if __name__ == "__main__":
    raise SystemExit(main())
