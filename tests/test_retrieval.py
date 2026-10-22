from __future__ import annotations

import numpy as np

from rag.FromQueryEmbeddingToRes import pipeline, retrieval, vectorstore
from rag.FromQueryEmbeddingToRes.models import QuerySignals, RerankBackend, SearchMode
from rag.FromQueryEmbeddingToRes.rerank import rerank_cohere

QUERY = "Consigliami 3 dei migliori film di fantascienza che hanno fatto la storia"


class FakeCollection:
    """Chroma-like collection returning fixed results ordered by distance."""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.n_results: int | None = None

    def query(self, *, query_embeddings, n_results):
        self.n_results = n_results
        rows = self.rows[:n_results]
        return {
            "ids": [[row["id"] for row in rows]],
            "documents": [[row["testo"] for row in rows]],
            "distances": [[row["distance"] for row in rows]],
            "metadatas": [[row["metadata"] for row in rows]],
        }

    def count(self) -> int:
        return len(self.rows)


ROWS = [
    {"id": "a", "testo": "Life in Rome.", "distance": 0.50, "metadata": {"title": "Gente di Roma", "genres": "Comedy"}},
    {"id": "b", "testo": "Garibaldi.", "distance": 0.55, "metadata": {"title": "1860", "genres": "Drama"}},
    {"id": "c", "testo": "A ship in space.", "distance": 0.60, "metadata": {"title": "Star Odyssey", "genres": "Science Fiction"}},
]


def _capture_embed(monkeypatch) -> list[str]:
    embedded: list[str] = []

    def fake_embed(texts, backend, model):
        embedded.extend(texts)
        return np.zeros((len(texts), 3), dtype=np.float32)

    monkeypatch.setattr(vectorstore, "embed", fake_embed)
    return embedded


def test_search_embeds_semantic_query_not_the_signal_keywords(monkeypatch) -> None:
    embedded = _capture_embed(monkeypatch)

    vectorstore.search(
        FakeCollection(ROWS),
        QUERY,
        2,
        backend="openai",
        model="m",
        positive_signals=["fantascienza", "film storici", "i migliori"],
        semantic_query="Influential science fiction movies",
    )

    assert embedded == ["Influential science fiction movies"]


def test_search_falls_back_to_the_original_query(monkeypatch) -> None:
    embedded = _capture_embed(monkeypatch)

    vectorstore.search(
        FakeCollection(ROWS),
        QUERY,
        2,
        backend="openai",
        model="m",
        positive_signals=["fantascienza", "film storici"],
        semantic_query="  ",
    )

    assert embedded == [QUERY]


def test_genre_boost_reorders_the_pool_before_cutting_to_k(monkeypatch) -> None:
    _capture_embed(monkeypatch)
    collection = FakeCollection(ROWS)

    results = vectorstore.search(
        collection,
        QUERY,
        2,
        backend="openai",
        model="m",
        fetch_k=3,
        genres=["science fiction"],
        genre_boost=0.15,
    )

    assert collection.n_results == 3
    assert [r["title"] for r in results] == ["Star Odyssey", "Gente di Roma"]


def test_genre_match_ignores_unrelated_genres() -> None:
    assert vectorstore._matches_genres({"genres": "Romantic comedy; Drama"}, ["Comedy"])
    assert not vectorstore._matches_genres({"genres": "Drama"}, ["Science Fiction"])
    assert not vectorstore._matches_genres({"genres": "Drama"}, [])


def test_retrieve_passes_fetch_k_genres_and_semantic_query(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_recupera(query, **kwargs):
        calls.append({"query": query, **kwargs})
        return []

    monkeypatch.setattr(retrieval, "recupera", fake_recupera)
    monkeypatch.setattr(retrieval, "apri_collection", lambda *a, **k: FakeCollection([]))
    config = {
        "retrieval": {"search_mode": SearchMode.semantic, "k_largo": 10, "k_finale": 3, "fetch_k": 50, "genre_boost": 0.15},
        "embedding": {"backend": "openai", "model": "m"},
        "vectorstore": {"collection": "c", "db_dir": "x"},
    }
    signals = QuerySignals(
        positive_signals=["science fiction"],
        semantic_query="Influential science fiction movies",
        genres=["Science Fiction"],
    )

    retrieval._retrieve(QUERY, config, signals=signals)

    assert calls[0]["fetch_k"] == 50
    assert calls[0]["semantic_query"] == "Influential science fiction movies"
    assert calls[0]["genres"] == ["Science Fiction"]
    assert calls[0]["genre_boost"] == 0.15


def test_retrieve_without_fetch_k_keeps_the_old_pool_size(monkeypatch) -> None:
    calls: list[dict] = []
    monkeypatch.setattr(retrieval, "recupera", lambda query, **kwargs: calls.append(kwargs) or [])
    monkeypatch.setattr(retrieval, "apri_collection", lambda *a, **k: FakeCollection([]))
    config = {
        "retrieval": {"search_mode": SearchMode.semantic, "k_largo": 10, "k_finale": 3},
        "embedding": {"backend": "openai", "model": "m"},
        "vectorstore": {"collection": "c", "db_dir": "x"},
    }

    retrieval._retrieve(QUERY, config, signals=QuerySignals())

    assert calls[0]["fetch_k"] == 10
    assert calls[0]["genre_boost"] == 0.0


def test_rerank_cohere_sees_title_and_genres() -> None:
    sent: dict = {}

    class FakeCohere:
        def rerank(self, *, model, query, documents, top_n):
            sent["documents"] = documents
            result = type("R", (), {"index": 0, "relevance_score": 0.9})()
            return type("Resp", (), {"results": [result]})()

    chunk = {"id": "c", "testo": "A ship in space.", "title": "Star Odyssey", "release_year": "1979", "genres": "Science Fiction"}

    ranked = rerank_cohere(QUERY, [chunk], model="m", cohere_api_client=FakeCohere())

    assert sent["documents"] == ["Title: Star Odyssey (1979)\nGenres: Science Fiction\n\nA ship in space."]
    assert ranked[0]["testo"] == "A ship in space."


def test_run_rag_returns_signals_and_embedded_text(monkeypatch) -> None:
    signals = QuerySignals(semantic_query="Influential science fiction movies", genres=["Science Fiction"])
    monkeypatch.setattr(pipeline, "_resolve_runtime_config", lambda config: config)
    monkeypatch.setattr(pipeline, "apri_collection", lambda *a, **k: FakeCollection(ROWS))
    monkeypatch.setattr(pipeline, "_build_signal_aware_query", lambda query, config, hint=None: signals)
    received: dict = {}

    def fake_retrieve(query, config, signals=None):
        received["signals"] = signals
        return []

    monkeypatch.setattr(pipeline, "_retrieve", fake_retrieve)
    monkeypatch.setattr(pipeline, "_rerank", lambda query, chunks, config: [])
    config = {
        "retrieval": {"search_mode": SearchMode.semantic},
        "rerank": {"backend": RerankBackend.cohere},
        "vectorstore": {"collection": "c", "db_dir": "x"},
    }

    result = pipeline.run_rag(config=config, query=QUERY)

    assert received["signals"] is signals
    assert result.signals == signals
    assert result.embedded_text == "Influential science fiction movies"


def _run_rag_with(monkeypatch, signals, retrieved):
    """run_rag with fake signals and pool; returns (result, query sent to the reranker)."""
    monkeypatch.setattr(pipeline, "_resolve_runtime_config", lambda config: config)
    monkeypatch.setattr(pipeline, "apri_collection", lambda *a, **k: FakeCollection(ROWS))
    monkeypatch.setattr(pipeline, "_build_signal_aware_query", lambda query, config, hint=None: signals)
    monkeypatch.setattr(pipeline, "_retrieve", lambda query, config, signals=None: retrieved)
    sent: dict = {}

    def fake_rerank(query, chunks, config):
        sent["query"] = query
        return chunks

    monkeypatch.setattr(pipeline, "_rerank", fake_rerank)
    config = {
        "retrieval": {"search_mode": SearchMode.semantic},
        "rerank": {"backend": RerankBackend.cohere},
        "vectorstore": {"collection": "c", "db_dir": "x"},
    }
    return pipeline.run_rag(config=config, query="Mare dentro mi ha colpito. Temi simili?"), sent["query"]


def _pool_chunk(title, genres):
    return {"id": title, "testo": "plot", "score": 0.5, "title": title, "genres": genres}


def test_excluded_genres_drop_chunks_from_the_pool(monkeypatch) -> None:
    _capture_embed(monkeypatch)

    results = vectorstore.search(
        FakeCollection(ROWS), QUERY, 3, backend="openai", model="m", excluded_genres=["Science Fiction"]
    )

    assert [r["title"] for r in results] == ["Gente di Roma", "1860"]


def test_excluded_genre_needs_whole_words() -> None:
    assert vectorstore.has_excluded_genre({"genres": "Sci-Fi;Science Fiction Western"}, ["Science Fiction"])
    assert not vectorstore.has_excluded_genre({"genres": "Melodrama"}, ["Drama"])
    assert not vectorstore.has_excluded_genre({"genres": ""}, ["Drama"])


def test_constraint_report_is_attached_to_the_result(monkeypatch) -> None:
    signals = QuerySignals(excluded_genres=["Science Fiction"])
    pool = [_pool_chunk("Exit", "Drama"), _pool_chunk("Senza generi", "")]

    result, _ = _run_rag_with(monkeypatch, signals, pool)

    [check] = result.constraints["checks"]
    assert check["type"] == "excluded_genre"
    assert check["results"]["Exit (?)"]["status"] == "verified"
    assert check["results"]["Senza generi (?)"]["status"] == "not_verifiable"
