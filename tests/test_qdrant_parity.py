"""Retrieval parity Chroma <-> Qdrant on controlled vectors (real Chroma, in-memory Qdrant).

The same points go through the real `crea_collection`/`indicizza`, then through the real migration;
`vectorstore.search`, the BM25 builder and `retrieval._retrieve` must answer the same on both.
No network, no paid call: the query embedding is replaced by a fixed vector.
"""
from __future__ import annotations

import numpy as np
import pytest

from tool.rag.EmbeddingProcess import migrate_chroma_to_qdrant as mig
from tool.rag.FromQueryEmbeddingToRes import hybrid, retrieval, vectorstore
from tool.rag.FromQueryEmbeddingToRes.models import QuerySignals, SearchMode
from tool.rag.FromQueryEmbeddingToRes.runtime import _resolve_runtime_config
from tool.rag.FromQueryEmbeddingToRes.store.base import IndexMeta
from tool.rag.FromQueryEmbeddingToRes.store.collection import QdrantCollection, open_collection
from tool.rag.FromQueryEmbeddingToRes.store.qdrant_store import QdrantStore, open_client

DIM = 32
N = 45
GENRES = ["Science Fiction", "Romance Film", "Horror", "Drama", "Comedy; Drama", "Japanese Movies"]
WORDS = ["robot", "ship", "love", "ghost", "river", "night", "storm", "king", "city", "desert"]
TOL = 1e-5


def _points():
    rng = np.random.default_rng(7)
    ids, docs, vecs, metas = [], [], [], []
    for i in range(N):
        v = rng.normal(size=DIM).astype(np.float32)
        ids.append(f"h-{i:06d}-000000")
        vecs.append((v / np.linalg.norm(v)).tolist())
        # unique token + unique length: BM25 scores of a query on those tokens never tie
        docs.append(f"{WORDS[i % 10]} {WORDS[(i * 3) % 10]} story number {i} with {WORDS[(i * 7) % 10]} "
                    f"tok{i} " + "pad " * i)
        meta = {"source": "MovieSummaries/plot_summaries.txt", "doc_index": str(i), "chunk_index": "0",
                "movie_id": str(1000 + i), "title": f"Film {i}", "genres": GENRES[i % len(GENRES)],
                "languages": "English", "countries": "USA", "cast": f"Actor {i}; Actor {i + 1}"}
        if i % 5:
            meta["release_year"] = str(1950 + i)
            meta["release_date"] = f"{1950 + i}-01-01"
        metas.append(meta)
    return ids, docs, vecs, metas


@pytest.fixture()
def engines(tmp_path, monkeypatch):
    ids, docs, vecs, metas = _points()
    chroma = vectorstore.crea_collection("netflix_scout", db_dir=tmp_path / "chroma")
    vectorstore.indicizza(chroma, ids, docs, vecs, metas)
    client = open_client("memory")
    store = QdrantStore(client, "netflix_scout", IndexMeta("m", DIM))
    mig.migrate(chroma_collection=chroma, store=store, run=mig.Run(tmp_path / "run"), batch_size=10)
    qdrant = QdrantCollection(store)
    query_vec = np.random.default_rng(3).normal(size=DIM).astype(np.float32)
    monkeypatch.setattr(vectorstore, "embed", lambda texts, backend=None, model=None: np.array([query_vec]))
    hybrid._BM25_CACHE.clear()
    return chroma, qdrant


def _search(collection, **kwargs):
    return vectorstore.search(collection, "una domanda", kwargs.pop("k", 5), backend="local", model="m", **kwargs)


def _same(a: list[dict], b: list[dict]) -> None:
    assert [r["id"] for r in a] == [r["id"] for r in b]
    for x, y in zip(a, b):
        assert abs(x["score"] - y["score"]) <= TOL
        assert {k: v for k, v in x.items() if k != "score"} == {k: v for k, v in y.items() if k != "score"}


SCENARIOS = {
    "plain": {},
    "wide_pool": {"fetch_k": 30, "k": 8},
    "k_larger_than_collection": {"k": 100},
    "genre_boost": {"genres": ["Science Fiction"], "genre_boost": 0.15, "fetch_k": 30, "k": 6},
    "excluded_genre": {"excluded_genres": ["Horror"], "fetch_k": 30, "k": 6},
    "hard_exclusion_title": {"hard_exclusions": ["Film 1"], "fetch_k": 30, "k": 6},
    "negative_signals": {"negative_signals": ["robot", "ship"], "fetch_k": 30, "k": 6},
    "everything": {"genres": ["Drama"], "genre_boost": 0.2, "excluded_genres": ["Comedy"],
                   "hard_exclusions": ["Film 4"], "negative_signals": ["ghost"], "fetch_k": 40, "k": 7},
}


@pytest.mark.parametrize("name", SCENARIOS)
def test_search_is_the_same_on_both_engines(engines, name):
    chroma, qdrant = engines
    _same(_search(chroma, **dict(SCENARIOS[name])), _search(qdrant, **dict(SCENARIOS[name])))


def test_search_result_contract_on_qdrant(engines):
    _, qdrant = engines
    rows = _search(qdrant, k=3)
    assert len(rows) == 3
    for row in rows:
        assert set(row) >= {"id", "testo", "score", "source", "movie_id", "title", "genres", "cast"}
        assert isinstance(row["id"], str) and isinstance(row["score"], float)
        assert all(isinstance(v, str) for k, v in row.items() if k != "score")
        assert not set(row) & {"legacy_id", "document", "title_norm", "release_year_int"}
    assert [r["score"] for r in rows] == sorted((r["score"] for r in rows), reverse=True)


def test_raw_query_shape_and_distances_match(engines):
    chroma, qdrant = engines
    vec = np.random.default_rng(11).normal(size=DIM).astype(np.float32).tolist()
    a = chroma.query(query_embeddings=[vec], n_results=9)
    b = qdrant.query(query_embeddings=[vec], n_results=9)
    assert a["ids"] == b["ids"] and a["documents"] == b["documents"] and a["metadatas"] == b["metadatas"]
    assert np.allclose(a["distances"][0], b["distances"][0], atol=TOL)
    with pytest.raises(ValueError):
        qdrant.query(query_embeddings=[vec, vec], n_results=3)


def test_count_and_paged_get_cover_everything_once(engines):
    chroma, qdrant = engines
    assert chroma.count() == qdrant.count() == N
    seen, offset = [], 0
    while offset < N:  # Chroma-style integer offsets, sequential
        page = qdrant.get(limit=8, offset=offset)
        seen.extend(page["ids"])
        offset += len(page["ids"])
    assert sorted(seen) == sorted(chroma.get(limit=N, offset=0)["ids"]) and len(set(seen)) == N
    jump = QdrantCollection(qdrant.store).get(limit=8, offset=16)  # non sequential: walks from the start
    assert jump["ids"] == seen[16:24]
    assert qdrant.get(limit=8, offset=N)["ids"] == []


def test_bm25_index_and_scores_match(engines, monkeypatch):
    chroma, qdrant = engines
    monkeypatch.setattr(hybrid, "_BM25_PAGE_SIZE", 7)  # several pages on both engines
    a = hybrid.costruisci_indice_bm25(chroma)
    hybrid._BM25_CACHE.clear()
    b = hybrid.costruisci_indice_bm25(qdrant)
    strip = lambda chunks: {c["id"]: c for c in chunks}  # noqa: E731
    assert strip(a["chunks"]) == strip(b["chunks"])
    k = 10
    for query in ("robot ship", "love story night", "ghost", "desert king storm"):
        ra = {r["id"]: r["score"] for r in hybrid.cerca_bm25(query, a, k)}
        rb = {r["id"]: r["score"] for r in hybrid.cerca_bm25(query, b, k)}
        # the score profile of the top-k is engine-independent
        assert sorted(ra.values(), reverse=True) == pytest.approx(sorted(rb.values(), reverse=True), abs=1e-9)
        assert all(abs(ra[i] - rb[i]) <= 1e-9 for i in ra.keys() & rb.keys())
        # ids may differ only among documents tied at the cut: same BM25 score as the k-th one
        cut = min(ra.values())
        assert all(ra.get(i, rb.get(i)) == pytest.approx(cut, abs=1e-9) for i in ra.keys() ^ rb.keys())


def _config(engine):
    return {
        "retrieval": {"search_mode": SearchMode.semantic, "k_largo": 6, "k_finale": 3, "fetch_k": 30,
                      "genre_boost": 0.15, "rrf_costante": 60},
        "embedding": {"backend": "local", "model": "m"},
        "vectorstore": {"collection": "netflix_scout", "db_dir": None, "engine": engine,
                        "qdrant": {"mode": "memory", "model": "m", "dimension": DIM}},
    }


@pytest.mark.parametrize("mode", [SearchMode.semantic, SearchMode.hybrid])
def test_retrieve_pipeline_is_the_same_on_both_engines(engines, monkeypatch, mode):
    chroma, qdrant = engines
    by_engine = {"chroma": chroma, "qdrant": qdrant}
    opener = lambda nome, db_dir=None, backend=None, *, store_config=None: by_engine[  # noqa: E731
        (store_config or {}).get("engine", "chroma")]
    monkeypatch.setattr(retrieval, "apri_collection", opener)
    monkeypatch.setattr(vectorstore, "apri_collection", opener)
    signals = QuerySignals(positive_signals=["robot"], negative_signals=["ghost"], hard_exclusions=["Film 3"],
                           semantic_query="tok7 tok19 tok23 tok28 tok40 tok44", genres=["Science Fiction"],
                           excluded_genres=["Horror"])
    out = {}
    for engine in ("chroma", "qdrant"):
        hybrid._BM25_CACHE.clear()
        cfg = _config(engine)
        cfg["retrieval"]["search_mode"] = mode
        out[engine] = retrieval._retrieve("una domanda", cfg, signals=signals)
    assert out["chroma"] and len(out["chroma"]) == len(out["qdrant"])
    _same(out["chroma"], out["qdrant"])  # no BM25 ties in this data: ids, order, scores and metadata agree


def test_engine_switch_defaults_to_chroma_and_qdrant_must_exist(tmp_path):
    local = vectorstore.apri_collection("coll1", db_dir=tmp_path / "x")  # no store_config -> Chroma, as before
    assert local.count() == 0
    with pytest.raises(RuntimeError, match="not found"):
        vectorstore.apri_collection("nope", store_config={"engine": "qdrant", "qdrant": {"mode": "memory"}})
    with pytest.raises(RuntimeError, match="not found"):
        open_collection("nope", {"qdrant": {"mode": "memory"}}, client=open_client("memory"))


def test_wrong_model_in_config_refuses_to_open(engines):
    _, qdrant = engines
    with pytest.raises(ValueError, match="rebuild the index"):
        open_collection("netflix_scout", {"qdrant": {"mode": "memory", "model": "other", "dimension": DIM}},
                        client=qdrant.store.client)
    ok = open_collection("netflix_scout", {"qdrant": {"mode": "memory", "model": "m", "dimension": DIM}},
                         client=qdrant.store.client)
    assert ok.count() == N


def test_runtime_config_injects_the_embedding_model():
    base = {"vectorstore": {"collection": "c", "db_dir": "somewhere", "engine": "qdrant",
                            "qdrant": {"mode": "server", "url": "http://x"}},
            "embedding": {"backend": "openai", "model": "text-embedding-3-small"},
            "retrieval": {}, "rerank": {}, "generation": {}}
    resolved = _resolve_runtime_config(base)
    assert resolved["vectorstore"]["qdrant"]["model"] == "text-embedding-3-small"
    assert base["vectorstore"]["qdrant"].get("model") is None  # the input is not mutated
