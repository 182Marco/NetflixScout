"""Phase 2, step 5: embeddings of every variant and of the queries with text-embedding-3-small and -large.
large@1536/1024 are derived from the 3072 vector by truncation + L2 renormalisation (what the API's `dimensions`
does); equivalence is verified against the API on a few texts. Vectors are cached on disk by text hash."""
from __future__ import annotations

import json

import numpy as np

from common import RESULTS, embed
from variants import VARIANTS, build

MODELS = ["text-embedding-3-small", "text-embedding-3-large"]


def shorten(v: np.ndarray, d: int) -> np.ndarray:
    v = v[:, :d]
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def main() -> None:
    pool = json.loads((RESULTS / "sample.json").read_text())["pool"]
    queries = json.loads((RESULTS / "queries.json").read_text())
    variants = build(pool)
    for model in MODELS:
        qv = embed("queries", model, [q["text"] for q in queries])
        np.save(RESULTS / f"q_{model}.npy", qv)
        for name in VARIANTS:
            items = variants[name]
            vec = embed(f"{name}", model, [t for _, t in items])
            np.save(RESULTS / f"d_{name}_{model}.npy", vec)
            (RESULTS / f"d_{name}_films.json").write_text(json.dumps([f for f, _ in items]))
            print(model, name, vec.shape, flush=True)
    # equivalence check large@1536 (truncate+renormalise) vs the API's dimensions=1536
    texts = [t for _, t in variants["B2"][:5]]
    api = embed("dimcheck", "text-embedding-3-large", texts, dimensions=1536)
    mine = shorten(embed("dimcheck3072", "text-embedding-3-large", texts), 1536)
    cos = (api * mine).sum(1) / (np.linalg.norm(api, axis=1) * np.linalg.norm(mine, axis=1))
    print("large@1536: API vs truncate+renormalise cosine", cos.round(5).tolist())
    (RESULTS / "dim_check.json").write_text(json.dumps({"cosines": cos.tolist()}))


if __name__ == "__main__":
    main()
