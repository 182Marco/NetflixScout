"""Retrieval over the Qdrant collection on controlled vectors (in-memory Qdrant, no network, no paid call).

`vectorstore.search`, the paged reader, the BM25 builder and `retrieval._retrieve` must answer as documented; the query
embedding is replaced by a fixed vector.
"""
from __future__ import annotations

import numpy as np
import pytest

from tool.rag.FromQueryEmbeddingToRes import hybrid, retrieval, vectorstore
from tool.rag.FromQueryEmbeddingToRes.models import QuerySignals, SearchMode
from tool.rag.FromQueryEmbeddingToRes.runtime import _resolve_runtime_config
from tool.rag.FromQueryEmbeddingToRes.store import StorePoint
from tool.rag.FromQueryEmbeddingToRes.store.base import IndexMeta
from tool.rag.FromQueryEmbeddingToRes.store.collection import QdrantCollection, open_collection
from tool.rag.FromQueryEmbeddingToRes.store.qdrant_store import QdrantStore, open_client

DIM = 32
N = 45
GENRES = ["Science Fiction", "Romance Film", "Horror", "Drama", "Comedy; Drama", "Japanese Movies"]
WORDS = ["robot", "ship", "love", "ghost", "river", "night", "storm", "king", "city", "desert"]


def _points():
    rng = np.random.default_rng(7)
    points = []
    for i in range(N):
        v = rng.normal(size=DIM).astype(np.float32)
        doc = f"{WORDS[i % 10]} {WORDS[(i * 3) % 10]} story number {i} with {WORDS[(i * 7) % 10]} tok{i} " + "pad " * i
        meta = {"source": "MovieSummaries/plot_summaries.txt", "doc_index": str(i), "chunk_index": "0",
                "movie_id": str(1000 + i), "title": f"Film {i}", "genres": GENRES[i % len(GENRES)],
                "languages": "English", "countries": "USA", "cast": f"Actor {i}; Actor {i + 1}"}
        if i % 5:
            meta["release_year"] = str(1950 + i)
            meta["release_date"] = f"{1950 + i}-01-01"
        points.append(StorePoint(id=f"h-{i:06d}-000000", vector=(v / np.linalg.norm(v)).tolist(), document=doc, metadata=meta))
    return points


@pytest.fixture()
def col(monkeypatch):
    store = QdrantStore(open_client("memory"), "netflix_scout", IndexMeta("m", DIM))
    store.create()
    store.upsert(_points())
    query_vec = np.random.default_rng(3).normal(size=DIM).astype(np.float32)
    monkeypatch.setattr(vectorstore, "embed", lambda texts, backend=None, model=None: np.array([query_vec]))
    hybrid._BM25_CACHE.clear()
    return QdrantCollection(store)


def _search(collection, **kwargs):
    return vectorstore.search(collection, "una domanda", kwargs.pop("k", 5), backend="openai", model="m", **kwargs)


def test_search_result_contract(col):
    rows = _search(col, k=3)
    assert len(rows) == 3
    for row in rows:
        assert set(row) >= {"id", "testo", "score", "source", "movie_id", "title", "genres", "cast"}
        assert isinstance(row["id"], str) and isinstance(row["score"], float)
        assert all(isinstance(v, str) for k, v in row.items() if k != "score")
        assert not set(row) & {"legacy_id", "document", "title_norm", "release_year_int"}
    assert [r["score"] for r in rows] == sorted((r["score"] for r in rows), reverse=True)


def test_k_larger_than_the_collection_returns_everything_once(col):
    rows = _search(col, k=100)
    assert len(rows) == N and len({r["id"] for r in rows}) == N


def test_filters_boosts_and_penalties(col):
    plain = _search(col, fetch_k=30, k=6)
    assert not any("Horror" in r["genres"] for r in _search(col, excluded_genres=["Horror"], fetch_k=30, k=6))
    assert "Film 1" not in {r["title"] for r in _search(col, hard_exclusions=["Film 1"], fetch_k=45, k=45)}
    boosted = _search(col, genres=["Science Fiction"], genre_boost=5.0, fetch_k=45, k=6)
    assert all("Science Fiction" in r["genres"] for r in boosted)
    penalised = _search(col, negative_signals=["robot"], fetch_k=45, k=45)
    robot = [r for r in penalised if "robot" in r["testo"].lower()]
    assert robot and all(r["score"] < next(p["score"] for p in _search(col, fetch_k=45, k=45) if p["id"] == r["id"]) for r in robot)
    assert len(plain) == 6


def test_count_and_paged_get_cover_everything_once(col):
    assert col.count() == N
    seen, offset = [], 0
    while offset < N:  # sequential integer offsets
        page = col.get(limit=8, offset=offset)
        seen.extend(page["ids"])
        offset += len(page["ids"])
    assert len(set(seen)) == N
    jump = QdrantCollection(col.store).get(limit=8, offset=16)  # non sequential: walks from the start
    assert jump["ids"] == seen[16:24] and col.get(limit=8, offset=N)["ids"] == []


def test_raw_query_shape_and_single_vector_rule(col):
    vec = np.random.default_rng(11).normal(size=DIM).astype(np.float32).tolist()
    out = col.query(query_embeddings=[vec], n_results=9)
    assert set(out) == {"ids", "documents", "distances", "metadatas"} and len(out["ids"][0]) == 9
    assert out["distances"][0] == sorted(out["distances"][0])
    with pytest.raises(ValueError):
        col.query(query_embeddings=[vec, vec], n_results=3)


def test_bm25_index_reads_every_page_and_finds_the_token(col, monkeypatch):
    monkeypatch.setattr(hybrid, "_BM25_PAGE_SIZE", 7)  # several pages
    index = hybrid.costruisci_indice_bm25(col)
    assert len(index["chunks"]) == N
    assert hybrid.cerca_bm25("tok17", index, 1)[0]["title"] == "Film 17"


def _config(mode):
    return {
        "retrieval": {"search_mode": mode, "k_largo": 6, "k_finale": 3, "fetch_k": 30, "genre_boost": 0.15, "rrf_costante": 60},
        "embedding": {"backend": "openai", "model": "m"},
        "vectorstore": {"collection": "netflix_scout", "qdrant": {"mode": "memory", "model": "m", "dimension": DIM}},
    }


@pytest.mark.parametrize("mode", [SearchMode.semantic, SearchMode.hybrid])
def test_retrieve_pipeline_applies_every_signal(col, monkeypatch, mode):
    monkeypatch.setattr(retrieval, "apri_collection", lambda nome, *, store_config: col)
    monkeypatch.setattr(vectorstore, "apri_collection", lambda nome, *, store_config: col)
    signals = QuerySignals(positive_signals=["robot"], negative_signals=["ghost"], hard_exclusions=["Film 3"],
                           semantic_query="tok7 tok19 tok23 tok28 tok40 tok44", genres=["Science Fiction"],
                           excluded_genres=["Horror"])
    out = retrieval._retrieve("una domanda", _config(mode), signals=signals)
    assert out and len(out) <= 6
    assert "Film 3" not in {r["title"] for r in out} and not any("Horror" in r["genres"] for r in out)


def test_a_missing_collection_is_reported(tmp_path):
    with pytest.raises(RuntimeError, match="not found"):
        vectorstore.apri_collection("nope", store_config={"qdrant": {"mode": "memory"}})
    with pytest.raises(RuntimeError, match="not found"):
        open_collection("nope", {"qdrant": {"mode": "memory"}}, client=open_client("memory"))


def test_wrong_model_in_config_refuses_to_open(col):
    with pytest.raises(ValueError, match="rebuild the index"):
        open_collection("netflix_scout", {"qdrant": {"mode": "memory", "model": "other", "dimension": DIM}}, client=col.store.client)
    ok = open_collection("netflix_scout", {"qdrant": {"mode": "memory", "model": "m", "dimension": DIM}}, client=col.store.client)
    assert ok.count() == N


def test_runtime_config_injects_the_embedding_model():
    base = {"vectorstore": {"collection": "c", "qdrant": {"mode": "server", "url": "http://x"}},
            "embedding": {"backend": "openai", "model": "text-embedding-3-small"},
            "retrieval": {}, "rerank": {}, "generation": {}}
    resolved = _resolve_runtime_config(base)
    assert resolved["vectorstore"]["qdrant"]["model"] == "text-embedding-3-small"
    assert base["vectorstore"]["qdrant"].get("model") is None  # the input is not mutated
