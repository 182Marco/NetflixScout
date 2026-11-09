"""Phase 2, step 8 (offline, free): Precision/Recall/nDCG@K on pooled LLM judgments, objective source-film hit rate and MRR,
breakdown by query type and by length of the source plot, paired bootstrap against the baseline (A, small-1536)."""
from __future__ import annotations

import json
import math

import numpy as np

from common import RESULTS, SEED, ntok, load_films
from retrieval import CONFIGS, EXTRA_CONFIGS, rankings
from variants import VARIANTS

KS = (5, 10)
BASE = ("A", "small-1536")


def dcg(grades):
    return sum(g / math.log2(i + 2) for i, g in enumerate(grades))


def per_query(runs, queries, judg):
    res = {}
    for key, r in runs.items():
        rows = []
        for qi, q in enumerate(queries):
            g = judg[q["qid"]]
            top = [r["films"][j] for j in r["top"][qi, :10]]
            gr = [g.get(f, 0) for f in top]
            n_rel = sum(1 for v in g.values() if v >= 1)
            ideal = sorted(g.values(), reverse=True)
            row = {}
            for k in KS:
                row[f"P@{k}"] = sum(1 for v in gr[:k] if v >= 1) / k
                row[f"Ps@{k}"] = sum(1 for v in gr[:k] if v == 2) / k
                row[f"R@{k}"] = sum(1 for v in gr[:k] if v >= 1) / n_rel
                row[f"nDCG@{k}"] = dcg(gr[:k]) / dcg(ideal[:k])
                row[f"Hit@{k}"] = float(q["source"] in top[:k])
            row["MRR"] = next((1 / (i + 1) for i, f in enumerate(top) if f == q["source"]), 0.0)
            rows.append(row)
        res[key] = rows
    return res


def mean(rows, metric, idx=None):
    v = [r[metric] for i, r in enumerate(rows) if idx is None or i in idx]
    return sum(v) / len(v)


def boot_diff(a, b, metric, n=4000, rng=None):
    rng = rng or np.random.default_rng(SEED)
    d = np.array([x[metric] - y[metric] for x, y in zip(a, b)])
    idx = rng.integers(0, len(d), (n, len(d)))
    m = d[idx].mean(1)
    return float(d.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def main() -> None:
    queries = json.loads((RESULTS / "queries.json").read_text())
    judg = json.loads((RESULTS / "judgments.json").read_text())
    runs = rankings()
    pq = per_query(runs, queries, judg)
    films = load_films()
    bins = {"250-500": (250, 500), "500-1000": (500, 1000), "1000-2000": (1000, 2000), ">2000": (2000, 10**9)}
    src_tok = [ntok(films[q["source"]]["synopsis"]) for q in queries]
    out = {"overall": {}, "by_type": {}, "by_length": {}, "vs_baseline": {}}
    metrics = ["Hit@5", "Hit@10", "MRR", "P@5", "P@10", "Ps@5", "Ps@10", "R@5", "R@10", "nDCG@5", "nDCG@10"]
    for key, rows in pq.items():
        name = f"{key[0]}|{key[1]}"
        out["overall"][name] = {m: round(mean(rows, m), 4) for m in metrics}
        for t in sorted({q["type"] for q in queries}):
            idx = {i for i, q in enumerate(queries) if q["type"] == t}
            out["by_type"].setdefault(name, {})[t] = {m: round(mean(rows, m, idx), 3) for m in ("Hit@10", "nDCG@10", "R@10")}
        for b, (lo, hi) in bins.items():
            idx = {i for i, n in enumerate(src_tok) if lo <= n < hi}
            out["by_length"].setdefault(name, {})[b] = {m: round(mean(rows, m, idx), 3) for m in ("Hit@10", "nDCG@10")}
        if key != BASE:
            out["vs_baseline"][name] = {m: [round(x, 4) for x in boot_diff(rows, pq[BASE], m)] for m in ("nDCG@10", "R@10", "Hit@10", "P@10")}
    out["n_queries"] = len(queries)
    out["judged_pairs"] = sum(len(v) for v in judg.values())
    out["relevant_per_query_mean"] = round(sum(sum(1 for x in v.values() if x >= 1) for v in judg.values()) / len(judg), 2)
    out["strict_per_query_mean"] = round(sum(sum(1 for x in v.values() if x == 2) for v in judg.values()) / len(judg), 2)
    (RESULTS / "metrics.json").write_text(json.dumps(out, indent=1))
    # console table
    print(f"{'system':22s}" + "".join(f"{m:>9s}" for m in metrics))
    for name, v in sorted(out["overall"].items(), key=lambda kv: -kv[1]["nDCG@10"]):
        print(f"{name:22s}" + "".join(f"{v[m]:9.3f}" for m in metrics))
    print("judged pairs", out["judged_pairs"], "relevant/query", out["relevant_per_query_mean"], "strict/query", out["strict_per_query_mean"])


if __name__ == "__main__":
    main()
