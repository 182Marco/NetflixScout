"""Phase 8: building blocks for "like X but not like Y" (pure functions on synthetic vectors) and two checks on the real v2 collection
(read-only, skipped when the server or the collection is not there)."""
from __future__ import annotations

import numpy as np
import pytest

from pipelines.wikipedia_films.indexing import negative as N
from pipelines.wikipedia_films.indexing import settings as S


def test_centroid_is_a_unit_vector_and_subtract_moves_away_from_the_negative():
    p, n = np.array([1.0, 0.0, 0.0]), np.array([0.8, 0.6, 0.0])
    c = N.centroid([p])
    assert abs(np.linalg.norm(c) - 1) < 1e-6
    q = N.subtract_query([p], [n], 0.5)
    assert q @ N.unit(n) < p @ N.unit(n)
    assert np.allclose(N.subtract_query([p], [], 0.5), p)


def test_penalty_ranks_a_candidate_close_to_a_negative_below_an_equally_positive_one():
    pos = [np.array([1.0, 0.0, 0.0])]
    neg = [np.array([0.0, 1.0, 0.0])]
    near_neg = N.unit(np.array([0.8, 0.6, 0.0]))
    far = N.unit(np.array([0.8, 0.0, 0.6]))
    s = N.penalised_scores(np.stack([near_neg, far]), pos, neg, 1.0)
    assert s[1] > s[0] and abs((np.stack([near_neg, far]) @ N.unit(pos[0]))[0] - (np.stack([near_neg, far]) @ N.unit(pos[0]))[1]) < 1e-6


def test_penalty_uses_the_closest_single_negative_not_their_average():
    pos = [np.array([1.0, 0.0, 0.0, 0.0])]
    neg = [np.array([0.0, 1.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0, 0.0])]
    c = N.unit(np.array([0.7, 0.7, 0.0, 0.0]))
    full = N.penalised_scores(np.stack([c]), pos, neg, 1.0)[0]
    assert abs(full - (c @ N.unit(pos[0]) - c @ N.unit(neg[0]))) < 1e-6


def test_filter_builder_combines_ids_genres_and_verified_only():
    assert N.build_filter() is None
    f = N.build_filter(exclude_point_ids=["a"], avoid_genres=["cyberpunk"], only_verified=True)
    assert len(f.must_not) == 2 and len(f.must) == 1


def _client():
    from pipelines.wikipedia_films.indexing.qdrant_index import make_client, server_version
    if server_version() is None:
        pytest.skip("Qdrant server not running")
    c = make_client()
    if S.COLLECTION_V2 not in {x.name for x in c.get_collections().collections}:
        pytest.skip("wikipedia_films_it_v2 not built")
    return c


def test_real_collection_genre_filter_removes_the_genre_and_the_id_filter_removes_the_example():
    c = _client()
    from pipelines.wikipedia_films.indexing.qdrant_index import point_id
    pts, _ = c.scroll(S.COLLECTION_V2, limit=1, with_vectors=True, with_payload=["film_id", "genres"])
    v, fid = pts[0].vector, pts[0].payload["film_id"]
    top = N.search(c, v, limit=5, flt=N.build_filter(exclude_point_ids=[point_id(fid, 0)]))
    assert fid not in [h.payload["film_id"] for h in top]
    genre = next(g for h in N.search(c, v, limit=10) for g in h.payload["genres"])
    out = N.search(c, v, limit=10, flt=N.build_filter(avoid_genres=[genre]))
    assert all(genre not in h.payload["genres"] for h in out)


def test_real_collection_unverified_filter_is_exact():
    c = _client()
    from qdrant_client import models
    n = c.count(S.COLLECTION_V2, count_filter=models.Filter(must=[models.FieldCondition(key="unverified", match=models.MatchValue(value=True))]), exact=True).count
    assert n == 65
