"""Catalog writes on an in-memory Qdrant: logic only (versions, links, hashes, scarti).

Whether the server evaluates the conditions atomically is NOT shown here: it needs the real
server (`tests/test_qdrant_catalog_server.py`). The embedding is fake and counts its calls.
"""
from __future__ import annotations

import pytest
from qdrant_client import QdrantClient, models

from tool.rag.FromQueryEmbeddingToRes.store import StorePoint, point_uuid
from tool.rag.FromQueryEmbeddingToRes.store.base import IndexMeta
from tool.rag.FromQueryEmbeddingToRes.store.catalog import (
    ERROR, INSERTED, LINKED, METADATA_UPDATED, SKIPPED, UNCHANGED, UPDATED,
    Candidate, CatalogRecord, CatalogStore, decide_link, embedding_text, metadata_for,
)
from tool.rag.FromQueryEmbeddingToRes.store.genre_map import corpus_genres
from tool.rag.FromQueryEmbeddingToRes.store.qdrant_store import QdrantStore

DIM = 4
META = IndexMeta(model="test-model", dimension=DIM)
OVERVIEW = "A lighthouse keeper discovers a hidden door under the sea and follows it into the dark. " * 2


def fake_vector(text: str) -> list[float]:
    base = sum(ord(c) for c in text) % 97 + 1
    return [float(base), 1.0, 2.0, 3.0]


class Embedder:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, text: str):
        self.calls += 1
        return fake_vector(text)


def record(tmdb_id=100, title="Deep Door", year=2014, overview=OVERVIEW, ts=1000, **kw) -> CatalogRecord:
    return CatalogRecord(tmdb_id=tmdb_id, title=title, overview=overview, year=year, fetched_ts=ts, **kw)


@pytest.fixture
def env():
    client = QdrantClient(":memory:")
    store = QdrantStore(client, "c", META)
    store.create()
    catalog = CatalogStore(client, "c", META.model, DIM)
    catalog.ensure_indexes()
    return client, store, catalog


def cmu(store, i, title, year, cast="", tmdb=None):
    meta = {"title": title, "movie_id": i, "source": "plots", "genres": "Drama"}
    if year:
        meta["release_year"] = str(year)
    if cast:
        meta["cast"] = cast
    store.upsert([StorePoint(id=i, vector=[1, 0, 0, 0], document=f"plot {title}", metadata=meta)])
    if tmdb:
        store.client.set_payload("c", {"tmdb_id": tmdb}, points=[point_uuid(i)])


def payload_of(client, tmdb_id):
    return client.retrieve("c", ids=[point_uuid(f"tmdb:movie:{tmdb_id}")], with_payload=True, with_vectors=True)[0]


# ---- decision table
def cand(year=2014, cast=(), tmdb=None, alt=False, pid="p"):
    return Candidate(point_id=pid, title_norm="deep door", year=year, cast=tuple(cast), tmdb_id=tmdb, via_alternative=alt)


A, B, C = ("Ann Lee", "Bob Ray", "Cy Dunn")


@pytest.mark.parametrize("rec_cast,cands,action,reason", [
    ((), [], "insert", ""),
    ((), [cand(year=1990)], "insert", ""),  # remake: more than one year apart
    ((), [cand(year=2014)], "link", ""),  # same year, unique, casts unknown
    ((A, B, C), [cand(2014, (A, "X Y", "Z W"))], "link", ""),
    ((A, B, C), [cand(2014, ("P Q", "R S", "T U"))], "ambiguous", "cast_mismatch"),  # veto
    ((), [cand(2015)], "ambiguous", "year_or_cast_unconfirmed"),  # ±1 without actor
    ((A,), [cand(2015, (A,))], "link", ""),  # ±1 with actor
    ((A,), [cand(None, (A,))], "link", ""),  # CMU year unknown with actor
    ((), [cand(None)], "ambiguous", "year_or_cast_unconfirmed"),  # never inserted as a duplicate
    ((), [cand(2014), cand(2014, pid="q")], "ambiguous", "several_candidates"),
    ((), [cand(2014, tmdb=999)], "ambiguous", "candidate_linked_elsewhere"),
    ((A,), [cand(2014, (A,), alt=True)], "link", ""),
    ((), [cand(2014, alt=True)], "ambiguous", "alternative_title_unconfirmed"),
    ((A,), [cand(2015, (A,), alt=True)], "ambiguous", "alternative_title_unconfirmed"),
])
def test_decide_link(rec_cast, cands, action, reason):
    decision = decide_link(record(cast=rec_cast), cands)
    assert (decision.action, decision.reason) == (action, reason)


def test_no_year_never_inserts_next_to_candidates():
    assert decide_link(record(year=None), [cand()]).action == "ambiguous"


# ---- text, metadata, genres
def test_embedding_text_is_only_the_overview_and_short_ones_are_refused():
    assert embedding_text(record(overview="  " + OVERVIEW + " ")) == OVERVIEW.strip()
    assert embedding_text(record(overview="too short")) is None
    assert embedding_text(record(overview=None)) is None


def test_genres_use_the_corpus_vocabulary():
    assert corpus_genres(["Crime", "Drama", "Music", "Crime"]) == ["Crime Fiction", "Drama", "Musical"]
    meta = metadata_for(record(genres=("Romance", "War"), cast=(A, B)))
    assert meta["genres"] == "Romance Film; War film" and meta["source"] == "tmdb"
    assert meta["movie_id"] == "tmdb:movie:100" and meta["cast"] == "Ann Lee; Bob Ray"


# ---- sync
def test_insert_then_repeat_is_idempotent_and_embeds_once(env):
    client, _, catalog = env
    emb = Embedder()
    first = catalog.sync(record(), emb)
    assert first.status == INSERTED and emb.calls == 1
    again = catalog.sync(record(ts=2000), emb)
    assert again.status == UNCHANGED and emb.calls == 1
    assert client.count("c").count == 1
    point = payload_of(client, 100)
    assert point.payload["version"] == 1 and point.payload["document"] == OVERVIEW.strip()
    assert point.payload["legacy_id"] == "tmdb:movie:100" and point.payload["title_norm"] == "deep door"
    assert point.payload["release_year_int"] == 2014 and point.payload["source"] == "tmdb"


def test_text_change_embeds_once_and_bumps_the_version(env):
    client, _, catalog = env
    emb = Embedder()
    catalog.sync(record(), emb)
    out = catalog.sync(record(overview=OVERVIEW + " A new ending is revealed in the last scene.", ts=2000), emb)
    assert out.status == UPDATED and emb.calls == 2
    point = payload_of(client, 100)
    assert point.payload["version"] == 2 and list(point.vector) != [] and client.count("c").count == 1


def test_metadata_only_change_keeps_the_vector_and_leaves_no_stale_field(env):
    client, _, catalog = env
    emb = Embedder()
    catalog.sync(record(languages=("English",), genres=("Drama",)), emb)
    before = payload_of(client, 100)
    out = catalog.sync(record(ts=2000, genres=("Crime",)), emb)  # languages disappeared on TMDb
    after = payload_of(client, 100)
    assert out.status == METADATA_UPDATED and emb.calls == 1
    assert list(after.vector) == list(before.vector)
    assert "languages" not in after.payload and after.payload["genres"] == "Crime Fiction"
    assert after.payload["version"] == 2


def test_older_reading_never_overwrites_a_newer_one(env):
    client, _, catalog = env
    emb = Embedder()
    catalog.sync(record(ts=2000), emb)
    out = catalog.sync(record(ts=1000, overview=OVERVIEW + " Different text that is older."), emb)
    assert out.status == SKIPPED and out.reason == "stale"
    assert payload_of(client, 100).payload["document"] == OVERVIEW.strip()


def test_equal_timestamp_keeps_the_first_arrival(env):
    client, _, catalog = env
    emb = Embedder()
    catalog.sync(record(ts=1000), emb)
    out = catalog.sync(record(ts=1000, overview=OVERVIEW + " Another text with the same time."), emb)
    assert out.reason == "stale" and payload_of(client, 100).payload["document"] == OVERVIEW.strip()


def test_overview_missing_or_short_is_not_written(env):
    client, _, catalog = env
    emb = Embedder()
    assert catalog.sync(record(overview=None), emb).reason == "no_english_overview"
    assert catalog.sync(record(overview="short"), emb).reason == "overview_too_short"
    assert client.count("c").count == 0 and emb.calls == 0


def test_a_concurrent_writer_between_read_and_write_is_not_overwritten(env, monkeypatch):
    """A writer that changed the version after my read makes my conditional write a no-op; I decide again."""
    client, _, catalog = env
    emb = Embedder()
    catalog.sync(record(ts=1000), emb)
    other = record(ts=1500, overview=OVERVIEW + " Written by the other process in the meantime.")
    real_read, state = catalog.read_by_tmdb_id, {"first": True}

    def read(tmdb_id):
        point = real_read(tmdb_id)
        if state.pop("first", False):  # the other writer lands right after my first read
            CatalogStore(client, "c", META.model, DIM).sync(other, Embedder())
        return point

    monkeypatch.setattr(catalog, "read_by_tmdb_id", read)
    mine = record(ts=2000, overview=OVERVIEW + " Mine, newer, but based on version one.")
    out = catalog.sync(mine, emb)
    final = payload_of(client, 100)
    assert out.status == UPDATED and out.attempts == 2
    assert final.payload["document"] == mine.overview.strip() and final.payload["version"] == 3


def test_metadata_writers_with_the_same_read_version_do_not_both_apply(env):
    client, _, catalog = env
    emb = Embedder()
    catalog.sync(record(genres=("Drama",)), emb)
    read_version = payload_of(client, 100).payload["version"]
    first = catalog._replace_metadata(record(ts=2000, genres=("Crime",)), OVERVIEW.strip(), read_version)
    second = catalog._replace_metadata(record(ts=2001, genres=("War",)), OVERVIEW.strip(), read_version)
    assert (first, second) == (True, False)
    assert payload_of(client, 100).payload["genres"] == "Crime Fiction"


def test_creation_does_not_overwrite_an_existing_point(env):
    client, _, catalog = env
    emb = Embedder()
    catalog.sync(record(ts=2000), emb)
    assert catalog._create(record(ts=1000, overview=OVERVIEW + " Late creator."), OVERVIEW + " Late creator.", fake_vector("x")) is False
    assert payload_of(client, 100).payload["document"] == OVERVIEW.strip()


def test_contention_after_the_attempt_limit_is_an_error(env, monkeypatch):
    _, _, catalog = env
    monkeypatch.setattr(catalog, "_create", lambda *a, **k: False)
    out = catalog.sync(record(), Embedder())
    assert out.status == ERROR and out.reason == "contention"


# ---- links to the corpus
def test_link_sets_only_tmdb_id_and_leaves_document_and_vector(env):
    client, store, catalog = env
    cmu(store, "cmu-1", "Deep Door", 2014, cast="Ann Lee; Bob Ray; Cy Dunn")
    before = client.retrieve("c", ids=[point_uuid("cmu-1")], with_payload=True, with_vectors=True)[0]
    emb = Embedder()
    out = catalog.sync(record(cast=(A, "Q R", "S T")), emb)
    after = client.retrieve("c", ids=[point_uuid("cmu-1")], with_payload=True, with_vectors=True)[0]
    assert out.status == LINKED and emb.calls == 0 and client.count("c").count == 1
    assert after.payload == {**before.payload, "tmdb_id": 100} and list(after.vector) == list(before.vector)
    assert catalog.sync(record(ts=3000), emb).status == UNCHANGED  # found through tmdb_id, no write


def test_link_does_not_replace_a_different_tmdb_id(env):
    client, store, catalog = env
    cmu(store, "cmu-1", "Deep Door", 2014, tmdb=555)
    out = catalog.sync(record(), Embedder())
    assert out.status == SKIPPED and "candidate_linked_elsewhere" in out.reason
    assert client.retrieve("c", ids=[point_uuid("cmu-1")], with_payload=True)[0].payload["tmdb_id"] == 555


def test_a_lost_link_race_is_decided_again(env, monkeypatch):
    client, store, catalog = env
    cmu(store, "cmu-1", "Deep Door", 2014)
    real = catalog._link

    def racing(target, tmdb_id):
        client.set_payload("c", {"tmdb_id": 777}, points=[point_uuid("cmu-1")])  # someone links first
        return real(target, tmdb_id)

    monkeypatch.setattr(catalog, "_link", racing)
    out = catalog.sync(record(), Embedder())
    assert out.status == SKIPPED and client.count("c").count == 1


def test_ambiguous_candidates_write_nothing(env):
    client, store, catalog = env
    cmu(store, "cmu-1", "Deep Door", 2015)  # ±1, no actor in common
    emb = Embedder()
    out = catalog.sync(record(), emb)
    assert out.status == SKIPPED and out.reason.startswith("ambiguous") and emb.calls == 0
    assert client.count("c").count == 1


def test_cmu_without_a_year_is_a_candidate_not_a_duplicate_insert(env):
    client, store, catalog = env
    cmu(store, "cmu-1", "Deep Door", None)
    out = catalog.sync(record(), Embedder())
    assert out.status == SKIPPED and client.count("c").count == 1


def test_remake_with_another_year_becomes_a_separate_point(env):
    client, store, catalog = env
    cmu(store, "cmu-1", "Deep Door", 1960)
    assert catalog.sync(record(), Embedder()).status == INSERTED
    assert client.count("c").count == 2


def test_alternative_title_links_only_with_same_year_and_a_shared_actor(env):
    client, store, catalog = env
    cmu(store, "cmu-1", "Three", 2005, cast="Ann Lee")
    ok = catalog.sync(record(title="Survival Island", year=2005, alternative_titles=("Three",), cast=(A,)), Embedder())
    assert ok.status == LINKED
    cmu(store, "cmu-2", "Inside", 2005, cast="Zed Zip")
    no = catalog.sync(record(tmdb_id=101, title="Rory", year=2005, alternative_titles=("Inside",), cast=(A,)), Embedder())
    assert no.status == SKIPPED and client.count("c").count == 2


def test_ensure_indexes_can_be_repeated(env):
    _, _, catalog = env
    catalog.ensure_indexes()
    catalog.ensure_indexes()


def test_exclusion_by_substring_does_not_hit_catalog_ids_for_ordinary_titles(env):
    client, _, catalog = env
    catalog.sync(record(), Embedder())
    point = payload_of(client, 100)
    assert point.payload["movie_id"] == "tmdb:movie:100" and point.payload["source"] == "tmdb"


def test_any_recorded_release_year_can_confirm_the_candidate():
    other = record(year=1964, release_years=(1962, 1964))  # "The Dungeon of Harrow": premiere 1962
    assert decide_link(other, [cand(year=1962)]).action == "link"
    assert decide_link(record(year=1964), [cand(year=1962)]).action == "insert"
