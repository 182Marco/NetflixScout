"""Phase 2, step 1: real token statistics of all synopses in films.jsonl (no network except the tokenizer file)."""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

import numpy as np
import tiktoken

ROOT = Path(__file__).resolve().parents[1]
FILMS = ROOT / "data" / "processed" / "films.jsonl"
OUT = Path(__file__).resolve().parent / "results"
EMBEDDING_INPUT_LIMIT = 8191  # text-embedding-3-*: max input tokens per text


def main() -> None:
    enc = tiktoken.get_encoding("cl100k_base")
    OUT.mkdir(exist_ok=True)
    rows = []
    for line in FILMS.open(encoding="utf-8"):
        r = json.loads(line)
        rows.append((r["film_id"], r["wikipedia_page_id"], len(r["synopsis"]), len(enc.encode(r["synopsis"], disallowed_special=()))))
    toks = np.array([r[3] for r in rows])
    chars = np.array([r[2] for r in rows])
    pct = {p: float(np.percentile(toks, p)) for p in (1, 5, 10, 25, 50, 75, 90, 95, 99, 99.9)}
    edges = [0, 150, 300, 500, 800, 1200, 2000, 4000, 8191, 10**9]
    hist = {}
    for lo, hi in zip(edges, edges[1:]):
        hist[f"{lo}-{hi if hi < 10**9 else 'inf'}"] = int(((toks >= lo) & (toks < hi)).sum())
    stats = {
        "films": len(rows), "tokenizer": "tiktoken cl100k_base",
        "total_tokens": int(toks.sum()), "total_chars": int(chars.sum()),
        "chars_per_token": float(chars.sum() / toks.sum()),
        "tokens": {"mean": float(toks.mean()), "median": float(np.median(toks)), "min": int(toks.min()), "max": int(toks.max()), "std": float(toks.std())},
        "percentiles": pct, "histogram": hist,
        "over_8191": int((toks > EMBEDDING_INPUT_LIMIT).sum()),
        "over_4000": int((toks > 4000).sum()), "over_2000": int((toks > 2000).sum()),
        "over_1000": int((toks > 1000).sum()), "over_512": int((toks > 512).sum()),
        "extreme_gt_mean_plus_3std": int((toks > toks.mean() + 3 * toks.std()).sum()),
    }
    (OUT / "plot_stats.json").write_text(json.dumps(stats, indent=1))
    with (OUT / "plot_tokens.tsv").open("w") as f:
        for fid, pid, c, t in rows:
            f.write(f"{fid}\t{pid}\t{c}\t{t}\n")
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    sys.exit(main())
