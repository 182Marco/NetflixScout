"""Phase 8: ways to ask for "like X but not like Y" on the clean collection, WITHOUT any embedding call.

Every strategy takes vectors (positive and negative examples are film vectors already stored, or centroids of groups of films) and
returns film hits. They are building blocks for a future retrieval layer; nothing here is wired to the application.

  baseline          mean of the positives
  exclude_only      baseline + the named negatives removed by id (what "exclude by title" amounts to)
  subtract          q = normalise(mean(P) - alpha * mean(N))
  recommend_avg     Qdrant native recommend, strategy average_vector  (q = mean(P) + mean(P) - mean(N), not normalised)
  recommend_best    Qdrant native recommend, strategy best_score      (a candidate closer to a negative than to any positive is pushed down)
  penalty           candidate pool by the positive query, rescored with  cos(r,P) - lam * max_i cos(r,N_i)  (one negative at a time)
  + metadata        any strategy with a payload filter (must_not genre / unverified), applied inside Qdrant"""
from __future__ import annotations

import numpy as np
from qdrant_client import QdrantClient, models

from . import settings as S

PAYLOAD = ["film_id", "title", "year", "genres", "synopsis", "unverified"]


def unit(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    return v / (np.linalg.norm(v) or 1.0)


def centroid(vectors) -> np.ndarray:
    return unit(np.mean([unit(v) for v in vectors], axis=0))


def subtract_query(pos, neg, alpha: float) -> np.ndarray:
    return unit(centroid(pos) - alpha * centroid(neg)) if len(neg) else centroid(pos)


def penalised_scores(cands: np.ndarray, pos, neg, lam: float) -> np.ndarray:
    """cos to the positive centroid minus lam * the highest cosine to ANY single negative (candidates are unit vectors)."""
    p = centroid(pos)
    s = cands @ p
    if len(neg):
        s = s - lam * np.max(np.stack([cands @ unit(n) for n in neg]), axis=0)
    return s


def build_filter(*, exclude_point_ids=(), avoid_genres=(), only_verified: bool = False) -> models.Filter | None:
    must_not, must = [], []
    if exclude_point_ids:
        must_not.append(models.HasIdCondition(has_id=list(exclude_point_ids)))
    for g in avoid_genres:
        must_not.append(models.FieldCondition(key="genres", match=models.MatchValue(value=g)))
    if only_verified:
        must.append(models.FieldCondition(key="unverified", match=models.MatchValue(value=False)))
    return models.Filter(must=must or None, must_not=must_not or None) if (must or must_not) else None


def search(client: QdrantClient, vector, *, collection: str = S.COLLECTION_V2, limit: int = 10, flt=None, with_vectors=False):
    r = client.query_points(collection, query=[float(x) for x in vector], limit=limit, query_filter=flt,
                            with_payload=PAYLOAD, with_vectors=with_vectors)
    return r.points


def recommend(client: QdrantClient, pos, neg, *, strategy: str, collection: str = S.COLLECTION_V2, limit: int = 10, flt=None):
    strat = {"avg": models.RecommendStrategy.AVERAGE_VECTOR, "best": models.RecommendStrategy.BEST_SCORE}[strategy]
    q = models.RecommendQuery(recommend=models.RecommendInput(positive=[[float(x) for x in unit(v)] for v in pos],
                                                              negative=[[float(x) for x in unit(v)] for v in neg] or None,
                                                              strategy=strat))
    return client.query_points(collection, query=q, limit=limit, query_filter=flt, with_payload=PAYLOAD).points


def penalty_search(client: QdrantClient, pos, neg, *, lam: float, pool: int = 200, collection: str = S.COLLECTION_V2,
                   limit: int = 10, flt=None):
    cands = search(client, centroid(pos), collection=collection, limit=pool, flt=flt, with_vectors=True)
    mat = np.stack([unit(np.asarray(c.vector)) for c in cands])
    sc = penalised_scores(mat, pos, neg, lam)
    order = np.argsort(-sc)[:limit]
    return [cands[i] for i in order]
