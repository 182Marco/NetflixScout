"""Small retrieval benchmark on the full collection with the 72 Phase 2 queries (one tiny API call to embed them).

Reported: objective Hit@K / MRR of the source film; agreement of Qdrant (HNSW) with an exact brute-force search over
the same vectors; the Phase 2 setting reproduced inside the new vectors (pool only) to compare with the Phase 2 number;
share of the top 10 already judged in Phase 2; and the consistency of the new API-dimension vectors with the Phase 2
truncated ones. The full corpus has 41x more distractors than the Phase 2 pool, so absolute values are lower by design."""
from __future__ import annotations

import json

import numpy as np

from . import settings as S
from .qdrant_index import make_client
from .units import build_units
from .verify_embeddings import load_all
from .wiki_search import embed_query, search_films

P2 = S.ROOT / "benchmark" / "results"


def film_matrix(units, vectors):
    """Per-film max-pooling support: vectors in unit order; returns (film_ids in order, start offsets)."""
    order, starts = [], []
    for i, u in enumerate(units):
        if not order or order[-1] != u.film_id:
            order.append(u.film_id); starts.append(i)
    return order, np.array(starts)


def rank_exact(q, vectors, order, starts, mask=None):
    sims = vectors @ q
    film = np.maximum.reduceat(sims, starts)
    if mask is not None:
        film = np.where(mask, film, -np.inf)
    return [order[i] for i in np.argsort(-film)[:10]]


def metrics(ranks, queries):
    hit = lambda k: float(np.mean([q["source"] in r[:k] for q, r in zip(queries, ranks)]))
    mrr = float(np.mean([next((1 / (i + 1) for i, f in enumerate(r) if f == q["source"]), 0.0) for q, r in zip(queries, ranks)]))
    return {"Hit@5": round(hit(5), 3), "Hit@10": round(hit(10), 3), "MRR@10": round(mrr, 3)}


def evaluate() -> dict:
    queries = json.loads((P2 / "queries.json").read_text())
    judg = json.loads((P2 / "judgments.json").read_text())
    pool = set(json.loads((P2 / "sample.json").read_text())["pool"])
    units = build_units()
    vectors, _ = load_all(units)
    order, starts = film_matrix(units, vectors)
    S.QUERY_CACHE.mkdir(parents=True, exist_ok=True)
    cache = S.QUERY_CACHE / "phase2_queries_large1536.npy"
    if cache.exists():
        qv = np.load(cache)
    else:
        from .embed_run import make_client as openai_client
        c = openai_client()
        qv = np.asarray([embed_query(q["text"], c) for q in queries], dtype=np.float32)
        np.save(cache, qv)
    qd = make_client()
    pool_mask = np.array([f in pool for f in order])
    ranks_q, ranks_exact, ranks_pool, overlap, judged = [], [], [], [], []
    for q, v in zip(queries, qv):
        top = [h.film_id for h in search_films(qd, v, limit=10)]
        ex = rank_exact(v, vectors, order, starts)
        ranks_q.append(top); ranks_exact.append(ex)
        ranks_pool.append(rank_exact(v, vectors, order, starts, pool_mask))
        overlap.append(len(set(top) & set(ex)) / 10)
        g = judg[q["qid"]]
        judged.append([g.get(f) for f in top])
    flat = [x for row in judged for x in row]
    # consistency with the Phase 2 vectors (truncated 3072 -> 1536) for the pool films that are a single vector
    old = np.load(P2 / "d_A_text-embedding-3-large.npy")[:, :1536]
    old = old / np.linalg.norm(old, axis=1, keepdims=True)
    old_films = json.loads((P2 / "d_A_films.json").read_text())
    new_by_film = {u.film_id: vectors[i] for i, u in enumerate(units) if u.chunk_count == 1}
    cos = [float(old[i] @ new_by_film[f]) for i, f in enumerate(old_films) if f in new_by_film]
    res = {
        "queries": len(queries), "collection_points": qd.count(S.COLLECTION, exact=True).count,
        "qdrant_full_corpus": metrics(ranks_q, queries), "exact_full_corpus": metrics(ranks_exact, queries),
        "qdrant_vs_exact_top10_overlap_mean": round(float(np.mean(overlap)), 4),
        "pool_only_exact_new_vectors": metrics(ranks_pool, queries),
        "phase2_pool_A_large_1536_reference": {"Hit@5": 0.611, "Hit@10": 0.708, "MRR@10": 0.442},
        "top10_share_judged_relevant": round(sum(1 for x in flat if x is not None and x >= 1) / len(flat), 3),
        "top10_share_judged_not_relevant": round(sum(1 for x in flat if x == 0) / len(flat), 3),
        "top10_share_unjudged": round(sum(1 for x in flat if x is None) / len(flat), 3),
        "duplicates_in_top10": sum(len(r) - len(set(r)) for r in ranks_q),
        "phase2_vs_new_vector_cosine": {"n": len(cos), "min": round(min(cos), 5), "mean": round(float(np.mean(cos)), 5)},
    }
    (S.DATA / "retrieval_eval.json").write_text(json.dumps(res, indent=1))
    return res
