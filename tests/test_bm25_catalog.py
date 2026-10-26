"""BM25 cache with a catalog that grows or changes text: one index per collection, rebuilt on demand."""
from __future__ import annotations

import pytest

from tool.rag.FromQueryEmbeddingToRes import hybrid, retrieval
from tool.rag.FromQueryEmbeddingToRes.models import QuerySignals, SearchMode


def BASE() -> dict[str, str]:  # BM25 gives a rare term no weight in a tiny corpus
    return {"a": "a ship in space", "b": "a quiet farm", "c": "a city at night", "d": "a boxer trains hard"}


class Coll:
    name = "fake"

    def __init__(self, docs: dict[str, str]) -> None:
        self.docs = docs
        self.reads = 0

    def count(self) -> int:
        return len(self.docs)

    def get(self, limit, offset=0, include=None):
        self.reads += 1
        ids = list(self.docs)[offset:offset + limit]
        return {"ids": ids, "documents": [self.docs[i] for i in ids], "metadatas": [{"title": i} for i in ids]}


@pytest.fixture(autouse=True)
def clean_cache():
    hybrid._BM25_CACHE.clear()
    yield
    hybrid._BM25_CACHE.clear()


def top(index, query):
    return [r["id"] for r in hybrid.cerca_bm25(query, index, 1)]


def test_new_film_is_found_only_after_the_next_build_and_one_entry_is_kept():
    coll = Coll(BASE())
    first = hybrid.costruisci_indice_bm25(coll)
    reads = coll.reads
    assert hybrid.costruisci_indice_bm25(coll) is first and coll.reads == reads  # cached
    coll.docs["tmdb:movie:1"] = "a lighthouse keeper opens a hidden door"
    assert "tmdb:movie:1" not in [c["id"] for c in first["chunks"]]  # the cached index does not see it
    rebuilt = hybrid.costruisci_indice_bm25(coll)
    assert rebuilt is not first and coll.reads > reads and top(rebuilt, "lighthouse") == ["tmdb:movie:1"]
    assert len(hybrid._BM25_CACHE) == 1  # the stale entry was evicted
    assert hybrid.costruisci_indice_bm25(coll) is rebuilt  # and the new one is reused


def test_text_change_with_the_same_count_needs_the_explicit_invalidation():
    coll = Coll(BASE())
    old = hybrid.costruisci_indice_bm25(coll)
    coll.docs["b"] = "a lighthouse keeper"
    assert hybrid.costruisci_indice_bm25(coll) is old  # same key: stale until invalidated
    hybrid.invalidate_bm25("fake")
    new = hybrid.costruisci_indice_bm25(coll)
    assert new is not old and top(new, "lighthouse") == ["b"]


def test_invalidation_touches_only_that_collection():
    hybrid._BM25_CACHE[("other", 3)] = {"bm25": None, "chunks": []}
    hybrid._BM25_CACHE[("fake", 3)] = {"bm25": None, "chunks": []}
    hybrid.invalidate_bm25("fake")
    assert list(hybrid._BM25_CACHE) == [("other", 3)]


def test_semantic_mode_never_builds_the_keyword_index(monkeypatch):
    def boom(collection):
        raise AssertionError("BM25 built in semantic mode")

    monkeypatch.setattr(retrieval, "costruisci_indice_bm25", boom)
    monkeypatch.setattr(retrieval, "recupera", lambda query, **kw: [])
    monkeypatch.setattr(retrieval, "apri_collection", lambda *a, **k: Coll({}))
    config = {
        "retrieval": {"search_mode": SearchMode.semantic, "k_largo": 10, "k_finale": 3},
        "embedding": {"backend": "openai", "model": "m"},
        "vectorstore": {"collection": "c", "db_dir": "x"},
    }
    retrieval._retrieve("q", config, signals=QuerySignals())
