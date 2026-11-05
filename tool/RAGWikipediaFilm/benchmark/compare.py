"""Paired bootstrap comparisons that matter for the decision (offline)."""
from __future__ import annotations

import json

from common import RESULTS, ntok, load_films
from metrics import boot_diff, per_query
from retrieval import rankings

queries = json.loads((RESULTS / "queries.json").read_text())
judg = json.loads((RESULTS / "judgments.json").read_text())
pq = per_query(rankings(), queries, judg)
films = load_films()
long_idx = [i for i, q in enumerate(queries) if ntok(films[q["source"]]["synopsis"]) > 1000]
print("queries with source >1000 tokens:", len(long_idx))
pairs = [
    (("A", "large-3072"), ("A", "small-1536"), "large vs small (A)"),
    (("B1", "large-3072"), ("B1", "small-1536"), "large vs small (B1)"),
    (("A", "large-1536"), ("A", "large-3072"), "large 1536 vs 3072 (A)"),
    (("B1", "large-1536"), ("B1", "large-3072"), "large 1536 vs 3072 (B1)"),
    (("B1", "large-3072"), ("A", "large-3072"), "B1 vs A (large)"),
    (("B2", "large-3072"), ("A", "large-3072"), "B2 vs A (large)"),
    (("C500", "large-3072"), ("A", "large-3072"), "C500 vs A (large)"),
    (("C250", "large-3072"), ("A", "large-3072"), "C250 vs A (large)"),
    (("B1", "large-1536"), ("A", "large-3072"), "B1@1536 vs A@3072"),
    (("A", "large-1536"), ("A", "small-1536"), "A large-1536 vs A small-1536 (same dims)"),
]
def sub(rows, idx): return [rows[i] for i in idx]
print(f"{'comparison':44s} {'metric':8s} {'all (diff [95% CI])':28s} {'long sources only':28s}")
for a, b, name in pairs:
    for m in ("nDCG@10", "Hit@10"):
        d = boot_diff(pq[a], pq[b], m); dl = boot_diff(sub(pq[a], long_idx), sub(pq[b], long_idx), m)
        print(f"{name:44s} {m:8s} {d[0]:+.3f} [{d[1]:+.3f},{d[2]:+.3f}]   {dl[0]:+.3f} [{dl[1]:+.3f},{dl[2]:+.3f}]")
m = json.loads((RESULTS / "metrics.json").read_text())
print("\nby type nDCG@10 / Hit@10")
for name in ("A|small-1536", "A|large-3072", "B1|large-3072", "C500|large-3072"):
    print(name, {t: (v["nDCG@10"], v["Hit@10"]) for t, v in m["by_type"][name].items()})
print("\nby source length Hit@10")
for name in ("A|large-3072", "B1|large-3072", "B2|large-3072", "C500|large-3072", "C250|large-3072"):
    print(name, {t: v["Hit@10"] for t, v in m["by_length"][name].items()})
