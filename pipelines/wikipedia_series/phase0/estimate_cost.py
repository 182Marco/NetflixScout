"""Phase 0: token and cost ESTIMATE for embedding the preview units (no API call).

Tokens are measured with the local `tiktoken` (cl100k_base) on a sample of real unit texts to get the
characters-per-token ratio, then applied to the total characters. Price: text-embedding-3-large
0.13 USD per million tokens (the figure used for the film catalogue, see the film PROGRESS).

    python -m pipelines.wikipedia_series.phase0.estimate_cost
"""
from __future__ import annotations

import gzip
import json
import random

import tiktoken

from ..common import DATA_DIR

PRICE_PER_M = 0.13
BASE = DATA_DIR / "phase0"


def main() -> None:
    units = {}
    for l in open(BASE / "units_preview.jsonl", encoding="utf-8"):
        u = json.loads(l)
        if u["usable"]:
            units[u["id"]] = u
    texts = {}
    for l in gzip.open(BASE / "units_text.jsonl.gz", "rt", encoding="utf-8"):
        d = json.loads(l)
        if d["id"] in units:
            texts[d["id"]] = d["text"]
    enc = tiktoken.get_encoding("cl100k_base")
    rng = random.Random(11)
    out = {"price_per_million_tokens_usd": PRICE_PER_M, "levels": {}}
    total_chars = total_tokens = 0
    for level in ("series", "season", "episode"):
        ids = [i for i, u in units.items() if u["level"] == level and i in texts]
        sample = rng.sample(ids, min(400, len(ids)))
        ch = sum(len(texts[i]) for i in sample)
        tk = sum(len(enc.encode(texts[i])) for i in sample)
        ratio = ch / max(1, tk)
        chars = sum(len(texts[i]) for i in ids)
        tokens = chars / ratio
        longest = max((len(enc.encode(texts[i])) for i in sample), default=0)
        out["levels"][level] = {"units": len(ids), "chars": chars, "chars_per_token": round(ratio, 2),
                                "tokens_estimated": int(tokens), "longest_in_sample_tokens": longest}
        total_chars += chars
        total_tokens += tokens
    out["total"] = {"units": sum(v["units"] for v in out["levels"].values()), "tokens_estimated": int(total_tokens),
                    "usd_estimated": round(total_tokens / 1e6 * PRICE_PER_M, 2)}
    (BASE / "cost_estimate.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
