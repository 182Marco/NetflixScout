"""The migration and its validator next to catalog points (TMDb films and links), in-memory Qdrant."""
from __future__ import annotations

import numpy as np
from qdrant_client import models
from test_qdrant_migration import DIM, FakeChroma, _failed, _migrate, _set_payload, _store

from tool.rag.EmbeddingProcess import validate_migration as val
from tool.rag.FromQueryEmbeddingToRes.store import point_uuid
from tool.rag.FromQueryEmbeddingToRes.store.catalog import CatalogRecord, CatalogStore

OVERVIEW = "A lighthouse keeper discovers a hidden door under the sea and follows it into the dark. " * 2


def vec(seed: int) -> list[float]:
    v = np.random.default_rng(seed).normal(size=DIM)
    return (v / np.linalg.norm(v)).astype(np.float32).tolist()


class Embedder:
    def __init__(self):
        self.calls = 0

    def __call__(self, text):
        self.calls += 1
        return vec(self.calls + 1000)


def catalog_for(store) -> CatalogStore:
    c = CatalogStore(store.client, store.collection, store.meta.model, store.meta.dimension)
    c.ensure_indexes()
    return c


def add_catalog(chroma, store, emb):
    """One TMDb film not in the corpus and one corpus film linked to its TMDb id."""
    cat = catalog_for(store)
    new = CatalogRecord(tmdb_id=900, title="Brand New", overview=OVERVIEW, year=2020, fetched_ts=1)
    assert cat.sync(new, emb).status == "inserted"
    title = chroma.metas[0]["title"]
    year = int(chroma.metas[0]["release_year"])
    linked = CatalogRecord(tmdb_id=901, title=title, overview=OVERVIEW, year=year, fetched_ts=2)
    assert cat.sync(linked, emb).status == "linked"
    return cat, linked


def migrated(tmp_path):
    chroma, store = FakeChroma(), _store()
    _migrate(chroma, store, tmp_path)
    emb = Embedder()
    cat, linked = add_catalog(chroma, store, emb)
    return chroma, store, cat, linked, emb


def test_validator_passes_with_catalog_points_and_links(tmp_path):
    chroma, store, *_ = migrated(tmp_path)
    report = val.validate(chroma, store, page=3)
    assert report["passed"], report["anomaly_counts"]
    count = report["checks"]["count"]
    assert count["catalog_points"] == 1 and count["corpus_points_linked_to_tmdb"] == 1
    assert report["checks"]["catalog_perimeter"]["ok"]


def test_validator_still_catches_damage_on_a_linked_corpus_point(tmp_path):
    chroma, store, *_ = migrated(tmp_path)
    _set_payload(store, chroma.ids[0], document="altered")
    _failed(val.validate(chroma, store, page=3), "documents")

    chroma, store, *_ = migrated(tmp_path / "b")
    other = np.random.default_rng(5).normal(size=DIM).astype(np.float32).tolist()
    store.client.update_vectors(store.collection, [models.PointVectors(id=point_uuid(chroma.ids[0]), vector=other)])
    _failed(val.validate(chroma, store, page=3), "vectors")


def test_validator_refuses_any_extra_key_on_corpus_points_except_an_integer_tmdb_id(tmp_path):
    for field in ({"version": 1}, {"write_id": "x"}, {"text_hash": "x"}, {"surplus": "y"}):
        chroma, store, *_ = migrated(tmp_path / next(iter(field)))
        _set_payload(store, chroma.ids[1], **field)
        _failed(val.validate(chroma, store, page=3), "metadata")
    chroma, store, *_ = migrated(tmp_path / "bad")
    _set_payload(store, chroma.ids[1], tmdb_id="12")
    _failed(val.validate(chroma, store, page=3), "catalog_perimeter")


def test_malformed_catalog_point_fails(tmp_path):
    chroma, store, *_ = migrated(tmp_path)
    store.client.set_payload(store.collection, {"source": "plots"}, points=[point_uuid("tmdb:movie:900")])
    _failed(val.validate(chroma, store, page=3), "catalog_perimeter")


def test_repeating_the_migration_in_place_loses_only_the_links(tmp_path):
    chroma, store, cat, linked, emb = migrated(tmp_path)
    tmdb_before = store.client.retrieve(store.collection, ids=[point_uuid("tmdb:movie:900")],
                                        with_payload=True, with_vectors=True)[0]
    _migrate(chroma, store, tmp_path / "again")
    report = val.validate(chroma, store, page=3)
    assert report["passed"], report["anomaly_counts"]
    assert report["checks"]["count"]["corpus_points_linked_to_tmdb"] == 0  # the link is gone, nothing else
    tmdb_after = store.client.retrieve(store.collection, ids=[point_uuid("tmdb:movie:900")],
                                       with_payload=True, with_vectors=True)[0]
    assert tmdb_after.payload == tmdb_before.payload and list(tmdb_after.vector) == list(tmdb_before.vector)
    assert store.count() == len(chroma.ids) + 1
    calls = emb.calls
    assert cat.sync(CatalogRecord(**{**linked.__dict__, "fetched_ts": 9}), emb).status == "linked"  # again, free
    assert emb.calls == calls and store.count() == len(chroma.ids) + 1


def test_rebuilding_into_a_new_collection_loses_the_tmdb_films_and_citing_them_embeds_again(tmp_path):
    chroma = FakeChroma()
    fresh = _store()
    _migrate(chroma, fresh, tmp_path)
    emb = Embedder()
    cat = catalog_for(fresh)
    new = CatalogRecord(tmdb_id=900, title="Brand New", overview=OVERVIEW, year=2020, fetched_ts=1)
    assert cat.read_by_tmdb_id(900) is None
    assert cat.sync(new, emb).status == "inserted" and emb.calls == 1
