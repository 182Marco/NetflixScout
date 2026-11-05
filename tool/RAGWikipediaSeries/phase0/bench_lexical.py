"""Phase 0 PRELIMINARY benchmark of the index architecture, with a LEXICAL proxy (TF-IDF), no embeddings.

What it can say: how texts of different granularity compete in one shared ranking (crowding, level
mixing, parent retrieval) and what a level filter or a contextual prefix change. What it cannot say:
absolute dense-retrieval quality. Queries are sentences taken from the unit itself with proper nouns
removed (descriptive, nameless queries); the "named" variant prepends the series title.
Deterministic (fixed seed). Output: data/phase0/bench_lexical.json

    python -m tool.RAGWikipediaSeries.phase0.bench_lexical
"""
from __future__ import annotations

import gzip
import json
import random
import re
from collections import Counter, defaultdict

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from ..common import DATA_DIR

SEED = 20261105
N_PER_LEVEL = 500
TOP = 10


def load():
    units = [json.loads(l) for l in open(DATA_DIR / "phase0" / "units_preview.jsonl", encoding="utf-8")]
    texts = {}
    for l in gzip.open(DATA_DIR / "phase0" / "units_text.jsonl.gz", "rt", encoding="utf-8"):
        d = json.loads(l)
        texts[d["id"]] = d["text"]
    return [u for u in units if u["usable"] and texts.get(u["id"])], texts


def query_from(text: str, rng: random.Random) -> str | None:
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if 12 <= len(s.split()) <= 45]
    rng.shuffle(sentences)
    for s in sentences:
        words = [w for w in s.split() if not w[:1].isupper() and not any(c.isdigit() for c in w)]
        if len(words) >= 8:
            return " ".join(words)
    return None


def evaluate(scores: np.ndarray, level_of: np.ndarray, src: np.ndarray, qlevel: str, mask: np.ndarray | None) -> dict:
    s = scores.copy()
    if mask is not None:
        s[:, ~mask] = -1
    order = np.argsort(-s, axis=1)[:, :TOP]
    ranks = []
    for i, row in enumerate(order):
        where = np.where(row == src[i])[0]
        ranks.append(where[0] + 1 if len(where) else None)
    n = len(ranks)
    comp = Counter(level_of[order].ravel().tolist())
    return {"n": n, "hit@1": sum(r == 1 for r in ranks) / n, "hit@5": sum(r is not None and r <= 5 for r in ranks) / n,
            "hit@10": sum(r is not None for r in ranks) / n,
            "mrr": sum(1 / r for r in ranks if r) / n,
            "top10_level_share": {k: round(v / (n * TOP), 3) for k, v in comp.items()}}


def main() -> None:
    rng = random.Random(SEED)
    units, texts = load()
    series_title = {u["id"]: u["title"] for u in units if u["level"] == "series"}
    ids = [u["id"] for u in units]
    index_of = {i: k for k, i in enumerate(ids)}
    level = np.array([u["level"] for u in units])
    by_level = defaultdict(list)
    for u in units:
        by_level[u["level"]].append(u)

    def context(u):
        sname = series_title.get(u.get("series_id"), "")
        if u["level"] == "series":
            return u["title"]
        if u["level"] == "season":
            return f"{sname} - stagione {u.get('season_no') or ''}"
        return f"{sname} - {u['title']}"

    results = {"corpus": {k: len(v) for k, v in by_level.items()}, "queries_per_level": N_PER_LEVEL, "variants": {}}
    for variant in ("plain", "context_prefix"):
        docs = [(context(u) + ". " if variant == "context_prefix" else "") + texts[u["id"]] for u in units]
        vec = TfidfVectorizer(sublinear_tf=True, min_df=2, max_df=0.5, ngram_range=(1, 1), max_features=300000)
        X = vec.fit_transform(docs)
        res = {}
        for qlevel in ("series", "season", "episode"):
            pool = [u for u in by_level[qlevel] if (qlevel == "series" or u.get("series_id"))]
            rng2 = random.Random(SEED + hash(qlevel) % 1000)
            rng2.shuffle(pool)
            qs, src, named, parent_s, parent_se = [], [], [], [], []
            for u in pool:
                q = query_from(texts[u["id"]], rng2)
                if not q:
                    continue
                qs.append(q)
                src.append(index_of[u["id"]])
                named.append((series_title.get(u.get("series_id"), "") + " " + q).strip())
                parent_s.append(index_of.get(u.get("series_id"), -1) if qlevel != "series" else -1)
                parent_se.append(index_of.get(u.get("season_id"), -1) if qlevel == "episode" else -1)
                if len(qs) == N_PER_LEVEL:
                    break
            src = np.array(src)
            for qtype, qlist in (("nameless", qs), ("named", named)):
                scores = (vec.transform(qlist) @ X.T).toarray()
                for mode in ("mixed", "filtered"):
                    mask = (level == qlevel) if mode == "filtered" else None
                    r = evaluate(scores, level, src, qlevel, mask)
                    if mode == "mixed" and qlevel != "series":
                        order = np.argsort(-scores, axis=1)[:, :TOP]
                        r["parent_series_in_top10"] = float(np.mean([p in row for p, row in zip(parent_s, order) if p >= 0]))
                        if qlevel == "episode":
                            r["parent_season_in_top10"] = float(np.mean([p in row for p, row in zip(parent_se, order) if p >= 0]))
                    res[f"{qlevel}|{qtype}|{mode}"] = r
        results["variants"][variant] = res
    out = DATA_DIR / "phase0" / "bench_lexical.json"
    out.write_text(json.dumps(results, indent=1), encoding="utf-8")
    for variant, res in results["variants"].items():
        print("==", variant)
        for k, r in res.items():
            print(f"{k:32s} hit@1={r['hit@1']:.2f} hit@5={r['hit@5']:.2f} hit@10={r['hit@10']:.2f} mrr={r['mrr']:.2f}",
                  {a: b for a, b in r.items() if a.startswith('parent') or a == 'top10_level_share'})


if __name__ == "__main__":
    main()
