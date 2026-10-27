"""Catalog wiring in `app.py`: off by default and inert; on, a verified movie reaches Qdrant.

TMDb is the fake transport, the store a real embedded Qdrant in a temp folder, the embedding a
counting fake (no network, no key).
"""
from __future__ import annotations

import copy
from dataclasses import fields

import pytest
from tmdb_support import MOVIE_ID, make_tool, movie_payload, run

import app
from tool.rag.FromQueryEmbeddingToRes.store import StorePoint, point_uuid
from tool.rag.FromQueryEmbeddingToRes.store.base import IndexMeta
from tool.rag.FromQueryEmbeddingToRes.store.catalog import CatalogRecord
from tool.rag.FromQueryEmbeddingToRes.store.collection import close_clients
from tool.rag.FromQueryEmbeddingToRes.store.qdrant_store import QdrantStore, open_client
from tool.tmdb.film_record import read_film_record

MODEL, DIM = "text-embedding-3-small", 1536
LONG = "A crew crosses a wormhole to find a new home for humanity while time slows down around them. " * 2


def details():
    data = movie_payload(genres=[{"id": 80, "name": "Crime"}])
    data["translations"] = {"translations": [{"iso_639_1": "en", "iso_3166_1": "US", "data": {"overview": LONG}}]}
    return data


@pytest.fixture
def qdrant_folder(tmp_path):
    folder = tmp_path / "q"
    client = open_client("embedded", path=folder)
    store = QdrantStore(client, "netflix_scout", IndexMeta(model=MODEL, dimension=DIM))
    store.create()
    store.upsert([StorePoint(id="cmu-1", vector=[1.0] + [0.0] * (DIM - 1), document="plot",
                             metadata={"title": "Other", "movie_id": "1", "source": "plots"})])
    client.close()
    yield folder
    close_clients()


def config(folder, enabled=True, mode="embedded"):
    return app.build_runtime_config({
        "catalog": {"enabled": enabled},
        "rag": {"vectorstore": {
                                 "qdrant": {"mode": mode, "path": str(folder), "url": None}}},
    })


class CountingEmbed:
    def __init__(self):
        self.calls = []

    def __call__(self, texts, backend, model, timeout=None):
        self.calls.append((list(texts), backend, model, timeout))
        return [[0.5] * DIM for _ in texts]


def test_default_config_has_the_catalog_off():
    assert app.CONFIG["catalog"] == {"enabled": False}


def test_off_registers_no_tmdb_enricher_and_touches_nothing(monkeypatch, qdrant_folder):
    opened = []
    monkeypatch.setattr(app, "apri_collection", lambda *a, **k: opened.append(1))
    built = app.build_app({"catalog": {"enabled": False}})
    assert "tmdb_search" not in built["orchestrator"].enrichers and opened == []
    assert set(built["orchestrator"].enrichers) <= {"rag_search"}


def test_on_with_a_volatile_store_fails_at_startup(qdrant_folder):
    with pytest.raises(ValueError, match="catalog.enabled"):
        app.build_app(config(qdrant_folder, mode="memory"))


def test_film_record_fields_are_exactly_the_catalog_record_fields():
    tool, _ = make_tool({f"/movie/{MOVIE_ID}": details()})
    record, _ = read_film_record(tool, MOVIE_ID)
    assert set(record) <= {f.name for f in fields(CatalogRecord)}
    assert CatalogRecord(**record).tmdb_id == MOVIE_ID


def test_on_a_verified_movie_is_stored_once_and_found_by_tmdb_id(monkeypatch, qdrant_folder):
    fake = CountingEmbed()
    monkeypatch.setattr(app, "embed", fake)
    tool, transport = make_tool({f"/movie/{MOVIE_ID}": details()})
    enricher = app.build_catalog_enricher(config(qdrant_folder), tool)
    result = run(tool, {"operation": "movie_details", "tmdb_id": MOVIE_ID})
    before = copy.deepcopy(result["metadata"]), copy.deepcopy(result["chunks"])

    out = enricher.enrich(tool_result={**result, "turn_id": "t1"})

    assert out["trace"][0]["data"]["catalog"] == [{"status": "inserted", "tmdb_id": MOVIE_ID}]
    assert (out["metadata"], out["chunks"]) == before
    assert fake.calls == [([LONG.strip()], "openai", MODEL, app.CATALOG_EMBED_TIMEOUT)]
    assert transport.paths.count(f"/movie/{MOVIE_ID}") == 1  # the details call is shared via the cache
    store = app.apri_collection("netflix_scout", store_config=config(qdrant_folder)["rag"]["vectorstore"]).store
    point = store.client.retrieve("netflix_scout", ids=[point_uuid(f"tmdb:movie:{MOVIE_ID}")], with_payload=True)[0]
    assert point.payload["genres"] == "Crime Fiction" and point.payload["source"] == "tmdb"
    assert store.count() == 2

    again = enricher.enrich(tool_result={**result, "turn_id": "t2"})
    assert again["trace"][0]["data"]["catalog"][0]["status"] == "unchanged" and len(fake.calls) == 1


def test_embedding_failure_leaves_metadata_untouched(monkeypatch, qdrant_folder):
    def boom(*a, **k):
        raise TimeoutError("openai down")

    monkeypatch.setattr(app, "embed", boom)
    tool, _ = make_tool({f"/movie/{MOVIE_ID}": details()})
    enricher = app.build_catalog_enricher(config(qdrant_folder), tool)
    result = run(tool, {"operation": "movie_details", "tmdb_id": MOVIE_ID})
    out = enricher.enrich(tool_result={**result, "turn_id": "t"})
    assert out["metadata"] == result["metadata"] and "enrichment_error" not in out["metadata"]
    assert out["trace"][0]["data"]["catalog"][0] == {"status": "error", "reason": "TimeoutError", "tmdb_id": MOVIE_ID}
    store = app.apri_collection("netflix_scout", store_config=config(qdrant_folder)["rag"]["vectorstore"]).store
    assert store.count() == 1


# ---- the reference-film flow shares the wiring, but is built lazily and never blocks the start
def test_reference_flow_provider_is_lazy_and_degrades_without_a_writable_qdrant(qdrant_folder, monkeypatch):
    from tool.rag.FromQueryEmbeddingToRes.reference_flow import ReferenceFlow

    tool, _ = make_tool({})
    opened = []
    monkeypatch.setattr(app, "apri_collection", lambda *a, **k: opened.append(1))
    provider = app.build_reference_flow_provider(config(qdrant_folder, mode="memory"), tool)
    assert opened == []  # nothing is opened when the application is built
    assert provider() is None and provider() is None and opened == []  # cannot work: remembered, no error

    monkeypatch.undo()
    monkeypatch.setattr(app, "embed", CountingEmbed())
    good = app.build_reference_flow_provider(config(qdrant_folder), tool)
    flow = good()
    assert isinstance(flow, ReferenceFlow) and good() is flow
    assert flow.strategy == "best_score" and flow.max_positive == 2 and flow.max_lookups == 4 and flow.persist is True


def test_build_app_gives_the_rag_tool_the_provider_without_touching_qdrant(monkeypatch):
    monkeypatch.setattr(app, "apri_collection", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Qdrant touched at build time")))
    rag = app.build_app()["orchestrator"].tools["rag_search"]
    assert callable(rag.reference_flow)
