"""Conditional writes of the catalog against a REAL Qdrant server (B1) and a short race (B2).

Skipped without QDRANT_URL. In-memory Qdrant cannot show that the server evaluates a filter
atomically with the write; this file is where that is checked. The long run (200 rounds, 2 and 4
processes, wait true/false, with a negative control) is `tests/qdrant_catalog_race.py`; here a few
rounds keep the check in the suite. Never point it at the real index: it creates and drops its own
synthetic collections.
"""
from __future__ import annotations

import os
import uuid

import pytest
from qdrant_client import QdrantClient, models

from qdrant_catalog_race import DIM, MODEL, fake_embed, plot, run
from tool.rag.FromQueryEmbeddingToRes.store import point_uuid
from tool.rag.FromQueryEmbeddingToRes.store.base import IndexMeta
from tool.rag.FromQueryEmbeddingToRes.store.catalog import CatalogRecord, CatalogStore
from tool.rag.FromQueryEmbeddingToRes.store.qdrant_store import QdrantStore

URL = os.getenv("QDRANT_URL")
pytestmark = [pytest.mark.qdrant_server, pytest.mark.skipif(not URL, reason="QDRANT_URL not set")]


@pytest.fixture
def server():
    client = QdrantClient(url=URL, check_compatibility=False)
    name = f"catalog_test_{uuid.uuid4().hex[:8]}"
    store = QdrantStore(client, name, IndexMeta(model=MODEL, dimension=DIM))
    store.create()
    catalog = CatalogStore(client, name, MODEL, DIM)
    catalog.ensure_indexes()
    yield client, store, catalog, name
    client.delete_collection(name)
    client.close()


def rec(ts=100, tag="a", genres=("Drama",), tmdb_id=5) -> CatalogRecord:
    return CatalogRecord(tmdb_id=tmdb_id, title="Server Film", overview=plot(tag), year=2014, fetched_ts=ts,
                         genres=genres)


def point(client, name, tmdb_id=5):
    return client.retrieve(name, ids=[point_uuid(f"tmdb:movie:{tmdb_id}")], with_payload=True, with_vectors=True)[0]


def test_false_condition_leaves_the_point_intact_and_a_new_id_is_inserted(server):
    client, _, catalog, name = server
    assert catalog.sync(rec(), fake_embed).status == "inserted"
    before = point(client, name)
    assert catalog._replace(rec(ts=200, tag="b"), plot("b").strip(), fake_embed(plot("b").strip()), 99) is False
    after = point(client, name)
    assert after.payload == before.payload and list(after.vector) == list(before.vector)


def test_creation_only_if_absent_and_updates_apply_once_per_read_version(server):
    client, _, catalog, name = server
    assert catalog.sync(rec(), fake_embed).status == "inserted"
    assert catalog._create(rec(ts=50, tag="late"), plot("late").strip(), fake_embed("late")) is False
    assert point(client, name).payload["document"] == plot("a").strip()
    assert catalog._replace(rec(ts=200, tag="b"), plot("b").strip(), fake_embed(plot("b").strip()), 1) is True
    assert catalog._replace(rec(ts=201, tag="c"), plot("c").strip(), fake_embed(plot("c").strip()), 1) is False
    assert point(client, name).payload["version"] == 2


def test_metadata_overwrite_is_conditional_replaces_the_payload_and_keeps_the_vector(server):
    client, _, catalog, name = server
    catalog.sync(rec(genres=("Drama",)), fake_embed)
    vec = list(point(client, name).vector)
    assert catalog._replace_metadata(rec(ts=200, genres=("Crime",)), plot("a").strip(), 1) is True
    assert catalog._replace_metadata(rec(ts=201, genres=("War",)), plot("a").strip(), 1) is False
    got = point(client, name)
    assert got.payload["genres"] == "Crime Fiction" and got.payload["version"] == 2 and list(got.vector) == vec


def test_link_guard_does_not_replace_an_existing_tmdb_id(server):
    client, store, catalog, name = server
    from tool.rag.FromQueryEmbeddingToRes.store import StorePoint

    store.upsert([StorePoint(id="cmu-1", vector=fake_embed("cmu"), document="cmu plot",
                             metadata={"title": "Server Film", "movie_id": "1", "source": "plots", "release_year": "2014"})])
    assert catalog.sync(rec(tmdb_id=5), fake_embed).status == "linked"
    out = catalog.sync(rec(tmdb_id=6), fake_embed)
    assert out.status == "skipped"
    assert client.retrieve(name, ids=[point_uuid("cmu-1")], with_payload=True)[0].payload["tmdb_id"] == 5


def test_indexes_can_be_created_on_an_existing_collection_and_repeated(server):
    _, _, catalog, _ = server
    catalog.ensure_indexes()
    catalog.ensure_indexes()


def test_short_race_with_guards_has_no_anomalies():
    result = run(URL, rounds=int(os.getenv("CATALOG_RACE_ROUNDS", "10")), procs=4, wait=True, guarded=True)
    assert result["rounds_with_anomalies"] == 0, result["examples"]


def test_the_same_race_without_guards_shows_anomalies():
    result = run(URL, rounds=int(os.getenv("CATALOG_RACE_ROUNDS", "10")), procs=4, wait=True, guarded=False)
    assert result["rounds_with_anomalies"] > 0, "the harness cannot tell a guard from no guard"
