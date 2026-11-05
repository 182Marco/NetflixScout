"""Phase 2, step 2: seeded, stratified selection. pool (1000, the retrieval corpus of the benchmark)
> evaluation sample (150, summary fidelity) > query sources (72, one query each). No network."""
from __future__ import annotations

import json
import random

from common import RESULTS, SEED

POOL_BINS = [(0, 200, 150), (200, 400, 200), (400, 800, 200), (800, 1500, 200), (1500, 2500, 150), (2500, 10**9, 100)]
SOURCE_BINS = [(250, 500, 18), (500, 1000, 18), (1000, 2000, 18), (2000, 10**9, 18)]
SAMPLE_BINS = [(0, 200, 15), (200, 400, 25), (400, 800, 30), (800, 1500, 35), (1500, 2500, 25), (2500, 10**9, 20)]


def main() -> None:
    rows = [l.split("\t") for l in (RESULTS / "plot_tokens.tsv").read_text().splitlines()]
    toks = {r[0]: int(r[3]) for r in rows}
    rng = random.Random(SEED)
    ids = sorted(toks)
    by_bin = lambda bins: [[i for i in ids if lo <= toks[i] < hi] for lo, hi, _ in bins]

    # 1) query sources first (need enough narrative: >= 250 tokens)
    sources: list[str] = []
    for (lo, hi, q), members in zip(SOURCE_BINS, by_bin(SOURCE_BINS)):
        sources += rng.sample(members, q)
    # 2) evaluation sample = sources + stratified fill up to the bin quotas
    sample = set(sources)
    for (lo, hi, q), members in zip(SAMPLE_BINS, by_bin(SAMPLE_BINS)):
        have = [i for i in members if i in sample]
        rest = [i for i in members if i not in sample]
        need = max(0, q - len(have))
        sample |= set(rng.sample(rest, need))
    # 3) pool = sample + stratified fill up to the bin quotas
    pool = set(sample)
    for (lo, hi, q), members in zip(POOL_BINS, by_bin(POOL_BINS)):
        have = [i for i in members if i in pool]
        rest = [i for i in members if i not in pool]
        pool |= set(rng.sample(rest, max(0, q - len(have))))
    out = {"seed": SEED, "pool": sorted(pool), "sample": sorted(sample), "sources": sources}
    (RESULTS / "sample.json").write_text(json.dumps(out))
    t = lambda s: [toks[i] for i in s]
    for name, s in (("pool", pool), ("sample", sample), ("sources", sources)):
        v = sorted(t(s)); print(name, len(s), "tokens total", sum(v), "mean", round(sum(v) / len(v)), "median", v[len(v) // 2], "max", v[-1])


if __name__ == "__main__":
    main()
