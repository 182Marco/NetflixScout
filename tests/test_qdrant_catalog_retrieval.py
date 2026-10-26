"""A film added from TMDb behaves like any other point of the index in retrieval (in-memory Qdrant)."""
from __future__ import annotations

import numpy as np
import pytest
from qdrant_client import QdrantClient

from tool.rag.FromQueryEmbeddingToRes import vectorstore
from tool.rag.FromQueryEmbeddingToRes.models import RagChunk
from tool.rag.FromQueryEmbeddingToRes.references import ReferenceInput, resolve_reference
from tool.rag.FromQueryEmbeddingToRes.store import StorePoint
from tool.rag.FromQueryEmbeddingToRes.store.base import IndexMeta
from tool.rag.FromQueryEmbeddingToRes.store.catalog import CatalogRecord, CatalogStore
from tool.rag.FromQueryEmbeddingToRes.store.collection import QdrantCollection
from tool.rag.FromQueryEmbeddingToRes.store.qdrant_store import QdrantStore

DIM = 4
OVERVIEW = "A lighthouse keeper discovers a hidden door under the sea and follows it into the dark. " * 2
TARGET = [0.0, 1.0, 0.0, 0.0]


@pytest.fixture
def env(monkeypatch):
    client = QdrantClient(":memory:")
    store = QdrantStore(client, "c", IndexMeta(model="m", dimension=DIM))
    store.create()
    store.upsert([
        StorePoint(id="a", vector=[1.0, 0.0, 0.0, 0.0], document="plot a",
                   metadata={"title": "Alpha", "movie_id": "1", "source": "plots", "genres": "Drama", "release_year": "2000"}),
        StorePoint(id="b", vector=[0.9, 0.1, 0.0, 0.0], document="plot b",
                   metadata={"title": "Beta", "movie_id": "2", "source": "plots", "genres": "Crime Fiction", "release_year": "2001"}),
    ])
    catalog = CatalogStore(client, "c", "m", DIM)
    catalog.ensure_indexes()
    rec = CatalogRecord(tmdb_id=100, title="Deep Door", overview=OVERVIEW, year=2014, fetched_ts=1,
                        genres=("Crime", "Drama"), cast=("Ann Lee",))
    assert catalog.sync(rec, lambda text: TARGET).status == "inserted"
    monkeypatch.setattr(vectorstore, "embed", lambda texts, backend=None, model=None: np.array([TARGET]))
    return QdrantCollection(store), store


def run(coll, **kw):
    return vectorstore.search(coll, "a lighthouse story", 3, "openai", "m", **kw)


def test_the_film_is_found_by_the_vector_search_as_a_rag_chunk(env):
    coll, _ = env
    first = run(coll)[0]
    chunk = RagChunk(**first)
    assert chunk.id == "tmdb:movie:100" and chunk.source == "tmdb" and chunk.title == "Deep Door"
    assert chunk.release_year == "2014" and chunk.movie_id == "tmdb:movie:100"
    assert chunk.testo == OVERVIEW.strip() and "version" not in first and "write_id" not in first


def test_the_film_is_found_by_title_and_resolves_as_a_reference(env):
    _, store = env
    found = store.find_by_title("Deep Door", 2014)
    assert [f["id"] for f in found] == ["tmdb:movie:100"]
    ref = resolve_reference(store, ReferenceInput("deep door", 2014), "positive")
    assert ref.status == "resolved" and ref.movie_id == "tmdb:movie:100"


def test_genre_boost_and_exclusion_use_the_corpus_vocabulary(env):
    coll, _ = env
    boosted = run(coll, genres=["Crime Fiction"], genre_boost=1.0)
    assert {r["id"] for r in boosted[:2]} == {"tmdb:movie:100", "b"}  # both "Crime Fiction"
    kept = run(coll, excluded_genres=["Science Fiction"])
    assert "tmdb:movie:100" in [r["id"] for r in kept]
    dropped = run(coll, excluded_genres=["Crime Fiction"])
    assert "tmdb:movie:100" not in [r["id"] for r in dropped] and "b" not in [r["id"] for r in dropped]


def test_ordinary_title_exclusions_do_not_hit_the_catalog_id(env):
    coll, _ = env
    ids = [r["id"] for r in run(coll, hard_exclusions=["Alpha", "Beta"])]
    assert "tmdb:movie:100" in ids
    assert "tmdb:movie:100" not in [r["id"] for r in run(coll, hard_exclusions=["Deep Door"])]


def test_the_film_is_listed_by_the_keyword_index_reader(env):
    coll, _ = env
    page = coll.get(limit=10, offset=0)
    assert "tmdb:movie:100" in page["ids"]
    meta = page["metadatas"][page["ids"].index("tmdb:movie:100")]
    assert meta["source"] == "tmdb" and "document" not in meta and "tmdb_id" not in meta
