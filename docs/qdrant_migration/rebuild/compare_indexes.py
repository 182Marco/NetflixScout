"""Compare two Qdrant indexes point by point (e.g. the migrated one and one rebuilt from the dataset). Read-only.

    python docs/qdrant_migration/rebuild/compare_indexes.py --a http://127.0.0.1:6333 --b http://127.0.0.1:6411 --report FILE

Checks: point counts, identical `legacy_id` sets and point ids, documents, every payload key and value, vector dimension,
finite/non-zero/unit-norm vectors, and the cosine similarity between the two vectors of each id (the embeddings were
recomputed, so tiny differences are expected; a low similarity is a real finding). Nothing is written to either server.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from qdrant_client import QdrantClient

PAGE = 1000
COSINE_NOTE = [0.9999, 0.999, 0.99, 0.95]


def load(client, collection: str) -> dict[str, dict]:
    points, offset = {}, None
    while True:
        batch, offset = client.scroll(collection, limit=PAGE, offset=offset, with_payload=True, with_vectors=True)
        for p in batch:
            payload = dict(p.payload or {})
            points[payload.get("legacy_id") or str(p.id)] = {"id": str(p.id), "payload": payload,
                                                              "vector": np.asarray(p.vector, dtype=np.float64)}
        if offset is None:
            return points


def compare(a: dict[str, dict], b: dict[str, dict]) -> dict:
    only_a, only_b = sorted(set(a) - set(b)), sorted(set(b) - set(a))
    common = sorted(set(a) & set(b))
    issues: Counter = Counter()
    samples: dict[str, list] = {}

    def note(kind, detail):
        issues[kind] += 1
        samples.setdefault(kind, [])
        if len(samples[kind]) < 5:
            samples[kind].append(detail)

    sims = []
    for key in common:
        pa, pb = a[key], b[key]
        if pa["id"] != pb["id"]:
            note("point_id", key)
        if pa["payload"] != pb["payload"]:
            keys = sorted(k for k in set(pa["payload"]) | set(pb["payload"]) if pa["payload"].get(k) != pb["payload"].get(k))
            note("payload", {"id": key, "keys": keys})
        va, vb = pa["vector"], pb["vector"]
        if va.shape != vb.shape:
            note("dimension", {"id": key, "a": va.shape, "b": vb.shape})
            continue
        for name, v in (("a", va), ("b", vb)):
            norm = float(np.linalg.norm(v))
            if not math.isfinite(norm) or norm == 0 or abs(norm - 1) > 1e-4:
                note(f"vector_invalid_{name}", {"id": key, "norm": norm})
        sims.append(float(va @ vb / (np.linalg.norm(va) * np.linalg.norm(vb))))
    sims_arr = np.asarray(sims) if sims else np.asarray([0.0])
    return {
        "count_a": len(a), "count_b": len(b), "common": len(common),
        "only_in_a": len(only_a), "only_in_b": len(only_b),
        "only_in_a_sample": only_a[:5], "only_in_b_sample": only_b[:5],
        "issues": dict(issues), "samples": samples,
        "cosine": {"min": float(sims_arr.min()), "mean": float(sims_arr.mean()), "p01": float(np.percentile(sims_arr, 1)),
                   **{f"below_{t}": int((sims_arr < t).sum()) for t in COSINE_NOTE}},
        "identical_ids_and_payloads": not (only_a or only_b or issues.get("payload") or issues.get("point_id")),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--a", required=True); ap.add_argument("--b", required=True)
    ap.add_argument("--collection-a", default="netflix_scout"); ap.add_argument("--collection-b", default="netflix_scout")
    ap.add_argument("--report", required=True)
    args = ap.parse_args(argv)
    ca, cb = QdrantClient(url=args.a, timeout=120), QdrantClient(url=args.b, timeout=120)
    try:
        report = compare(load(ca, args.collection_a), load(cb, args.collection_b))
    finally:
        ca.close(); cb.close()
    Path(args.report).write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    sys.stdout.write(json.dumps({k: report[k] for k in ("count_a", "count_b", "common", "only_in_a", "only_in_b", "issues", "cosine", "identical_ids_and_payloads")}, indent=1, default=str) + "\n")
    return 0 if report["identical_ids_and_payloads"] and not any(k.startswith(("vector_invalid", "dimension")) for k in report["issues"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
