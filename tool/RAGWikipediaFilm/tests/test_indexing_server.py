"""Integration checks on the REAL Qdrant server and the generated embeddings (skipped when either is not available).
Read-only: nothing is written to the collection."""
from __future__ import annotations

import pytest

pytest.importorskip("qdrant_client")
from tool.RAGWikipediaFilm.indexing import qdrant_index as Q  # noqa: E402
from tool.RAGWikipediaFilm.indexing import settings as S  # noqa: E402
from tool.RAGWikipediaFilm.indexing import wiki_search as W  # noqa: E402
from tool.RAGWikipediaFilm.indexing.units import build_units  # noqa: E402
from tool.RAGWikipediaFilm.indexing.verify_embeddings import load_all  # noqa: E402


@pytest.fixture(scope="module")
def live():
    if Q.server_version() is None:
        pytest.skip("Qdrant server not running (./scripts/start_qdrant.sh)")
    client = Q.make_client()
    if S.COLLECTION not in {c.name for c in client.get_collections().collections}:
        pytest.skip("collection not built (python -m tool.RAGWikipediaFilm.indexing index)")
    if not S.SHARDS.exists() or not any(S.SHARDS.glob("shard_*.npz")):
        pytest.skip("embedding shards not available")
    units = build_units()
    vectors, _ = load_all(units)
    return client, units, vectors


def test_collection_matches_source_and_embeddings(live):
    client, units, vectors = live
    report = Q.check_index(client=client, units=units, vectors=vectors)
    assert report["ok"], report


def test_a_film_is_found_by_its_own_vector_once(live):
    client, units, vectors = live
    for i in (0, len(units) // 2, len(units) - 1):
        hits = W.search_films(client, vectors[i], limit=5)
        assert hits[0].film_id == units[i].film_id
        assert len({h.film_id for h in hits}) == len(hits)


def test_chunked_films_come_back_once_with_all_chunks(live):
    client, units, vectors = live
    chunked = sorted({u.film_id for u in units if u.chunk_count > 1})
    assert len(chunked) == 5
    for fid in chunked:
        idx = [i for i, u in enumerate(units) if u.film_id == fid]
        hits = W.search_films(client, vectors[idx].mean(axis=0), limit=10)
        assert [h.film_id for h in hits].count(fid) == 1
        assert len(W.get_film(client, fid)["chunks"]) == len(idx)
