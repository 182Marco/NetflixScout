"""QdrantStore on `memory`, `embedded` and (when QDRANT_URL is set) `server`.

The first two prove the basic behaviour only. Compatibility with the server (HNSW, payload
indexes, concurrency) is proven only by the `server` variant: without it that result stays open.
"""
from __future__ import annotations

import importlib.metadata
import os
import re
import uuid
from pathlib import Path

import numpy as np
import pytest

from tool.rag.FromQueryEmbeddingToRes.store import StorePoint, norm_title, point_uuid, year_int
from tool.rag.FromQueryEmbeddingToRes.store.base import IndexMeta
from tool.rag.FromQueryEmbeddingToRes.store.qdrant_store import QdrantStore, open_client
from tool.rag.FromQueryEmbeddingToRes.store.settings import (
    QDRANT_CLIENT_VERSION,
    QDRANT_SERVER_VERSION,
    versions_compatible,
)

META = IndexMeta(model="test-model", dimension=4)
ROOT = Path(__file__).resolve().parents[1]

SERVER = pytest.param(
    "server",
    marks=[pytest.mark.qdrant_server,
           pytest.mark.skipif(not os.getenv("QDRANT_URL"), reason="QDRANT_URL not set")],
)


def _point(i: str, vec, title: str, year: str | None, movie_id: str, genres: str = "Drama") -> StorePoint:
    metadata = {"title": title, "movie_id": movie_id, "genres": genres, "source": "plots"}
    if year is not None:
        metadata["release_year"] = year
    return StorePoint(id=i, vector=vec, document=f"plot of {title}", metadata=metadata)


POINTS = [
    _point("a-0", [1, 0, 0, 0], "The Matrix", "1999", "m1", "Science Fiction"),
    _point("a-1", [0.9, 0.1, 0, 0], "Neo Land", "2001", "m2", "Science Fiction"),
    _point("a-2", [0, 1, 0, 0], "Romance One", "1950", "m3", "Romance"),
    _point("a-3", [0, 0.9, 0.1, 0], "Romance Two", "1951", "m4", "Romance"),
    _point("a-4", [0, 0, 1, 0], "Horror Show", "1980", "m5", "Horror"),
    _point("a-5", [0, 0.1, 0.9, 0], "Horror Show", "2010", "m6", "Horror"),  # remake: same title
    _point("a-6", [0, 0, 0, 1], "No Year", None, "m7"),
]


@pytest.fixture(params=["memory", "embedded", SERVER])
def store(request, tmp_path):
    name = f"t_{uuid.uuid4().hex[:8]}"
    if request.param == "memory":
        client = open_client("memory")
    elif request.param == "embedded":
        client = open_client("embedded", path=tmp_path / "q")
    else:
        client = open_client("server", url=os.environ["QDRANT_URL"])
    s = QdrantStore(client, name, META)
    s.create()
    s.upsert(POINTS)
    yield s
    if request.param == "server":
        client.delete_collection(name)
    client.close()


def test_count_and_idempotent_upsert(store):
    assert store.count() == len(POINTS)
    store.upsert(POINTS)
    assert store.count() == len(POINTS)


def test_query_shape_and_order(store):
    rows = store.query([1, 0, 0, 0], 3)
    assert [r["id"] for r in rows][:2] == ["a-0", "a-1"]
    first = rows[0]
    assert set(first) >= {"id", "testo", "score", "title", "movie_id", "genres", "release_year"}
    assert "legacy_id" not in first and "title_norm" not in first and "release_year_int" not in first
    assert first["testo"] == "plot of The Matrix"
    assert first["score"] == pytest.approx(1.0, abs=1e-6)


def test_exact_query_returns_the_same_neighbours(store):
    assert [r["id"] for r in store.query([1, 0.2, 0, 0], 5, exact=True)] == [
        r["id"] for r in store.query([1, 0.2, 0, 0], 5)]


def test_query_excludes_movie_ids(store):
    rows = store.query([1, 0, 0, 0], 7, exclude_movie_ids=["m1"])
    assert "a-0" not in [r["id"] for r in rows]


def test_recommend_moves_towards_positive_and_away_from_negative(store):
    positive, negative = [[1, 1, 0, 0]], [[0, 1, 0, 0]]  # between "Matrix" and the romances
    plain = [r["id"] for r in store.recommend(positive, [], 7)]
    steered = [r["id"] for r in store.recommend(positive, negative, 7)]
    assert "a-2" in plain[:3]  # without a negative the romance is as close as the sci-fi
    assert set(steered[:2]) == {"a-0", "a-1"}  # with it, only the sci-fi films lead


def test_average_vector_is_the_documented_formula(store):
    pos, neg = [[1, 0, 0, 0], [0.8, 0.2, 0, 0]], [[0, 1, 0, 0]]
    rec = store.recommend(pos, neg, 7)
    manual = 2 * np.mean(pos, axis=0) - np.mean(neg, axis=0)
    direct = store.query(manual.tolist(), 7)
    assert [r["id"] for r in rec] == [r["id"] for r in direct]


def test_best_score_runs_and_excludes(store):
    rows = store.recommend([[1, 0, 0, 0]], [[0, 0, 1, 0]], 7, strategy="best_score", exclude_movie_ids=["m1"])
    assert rows and "a-0" not in [r["id"] for r in rows]


def test_recommend_by_raw_vector_returns_the_reference_unless_excluded(store):
    vec = store.vector_of("a-0")
    assert "a-0" in [r["id"] for r in store.recommend([vec], [], 3)]
    assert "a-0" not in [r["id"] for r in store.recommend([vec], [], 3, exclude_movie_ids=["m1"])]


def test_recommend_input_validation(store):
    with pytest.raises(ValueError, match="positive"):
        store.recommend([], [[0, 1, 0, 0]], 3)
    with pytest.raises(ValueError, match="strategy"):
        store.recommend([[1, 0, 0, 0]], [], 3, strategy="sum_scores")


def test_find_by_title_year_window_and_homonyms(store):
    assert [h["id"] for h in store.find_by_title("the matrix")] == ["a-0"]
    assert [h["id"] for h in store.find_by_title("Matrix")] == ["a-0"]  # article-insensitive
    homonyms = store.find_by_title("Horror Show")
    assert {h["id"] for h in homonyms} == {"a-4", "a-5"}
    assert [h["id"] for h in store.find_by_title("Horror Show", year=1981)] == ["a-4"]
    assert [h["id"] for h in store.find_by_title("Horror Show", year=2010, window=0)] == ["a-5"]
    assert store.find_by_title("Absent Film") == []
    assert [h["id"] for h in store.find_by_title("No Year")] == ["a-6"]
    assert store.find_by_title("No Year", year=1999) == []  # a year filter never matches a missing year


def test_vector_of_and_missing(store):
    assert store.vector_of("a-2") == pytest.approx([0, 1, 0, 0], abs=1e-6)
    assert store.vector_of("nope") is None


def test_scroll_returns_every_point_in_the_search_shape(store):
    rows = list(store.scroll(batch_size=3))
    assert sorted(r["id"] for r in rows) == sorted(p.id for p in POINTS)
    assert all("testo" in r and "legacy_id" not in r for r in rows)


def test_meta_check_accepts_and_refuses(store):
    store.check_meta()
    other = QdrantStore(store.client, store.collection, IndexMeta(model="other", dimension=4))
    with pytest.raises(ValueError, match="rebuild the index"):
        other.check_meta()


def test_create_never_replaces(store):
    with pytest.raises(Exception):  # noqa: B017  (client-specific error type)
        store.create()
    assert store.count() == len(POINTS)


def test_embedded_persists_and_locks_its_folder(tmp_path):
    path = tmp_path / "q"
    first = QdrantStore(open_client("embedded", path=path), "c", META)
    first.create()
    first.upsert(POINTS)
    with pytest.raises(RuntimeError):  # a second process/client on the same folder
        open_client("embedded", path=path)
    first.close()
    again = QdrantStore(open_client("embedded", path=path), "c", META)
    assert again.count() == len(POINTS)
    again.check_meta()
    again.close()


def test_open_client_validation():
    with pytest.raises(ValueError, match="path"):
        open_client("embedded")
    with pytest.raises(ValueError, match="url"):
        open_client("server")
    with pytest.raises(ValueError, match="unknown"):
        open_client("cloud")


def test_ids_and_normalisation():
    assert point_uuid("5ddcfdb80e5f-000000-000000") == point_uuid("5ddcfdb80e5f-000000-000000")
    assert point_uuid("x") != point_uuid("y")
    assert str(uuid.UUID(point_uuid("x"))) == point_uuid("x")
    assert norm_title("The Dungeon of Harrow!") == "dungeon of harrow"
    assert norm_title("Amélie") == "amelie"
    assert norm_title(None) == ""
    assert [year_int(v) for v in ("1999", " 2001 ", "99", "abcd", "1700", "2200", None, 1950)] == [
        1999, 2001, None, None, None, None, None, 1950]


def test_client_and_server_versions_are_pinned_together():
    pin = re.search(r"^qdrant-client==(\S+)$", (ROOT / "requirements.txt").read_text(), re.M)
    assert pin and pin.group(1) == QDRANT_CLIENT_VERSION
    assert importlib.metadata.version("qdrant-client") == QDRANT_CLIENT_VERSION
    assert versions_compatible(QDRANT_CLIENT_VERSION, QDRANT_SERVER_VERSION)
    assert versions_compatible("1.20.0", "1.20.3") and not versions_compatible("1.20.0", "1.19.0")


@pytest.mark.qdrant_server
@pytest.mark.skipif(not os.getenv("QDRANT_URL"), reason="QDRANT_URL not set")
def test_running_server_matches_the_pinned_version():
    client = open_client("server", url=os.environ["QDRANT_URL"])
    version = client.info().version  # to be confirmed against a real server
    assert versions_compatible(QDRANT_CLIENT_VERSION, version)
    assert version.split(".")[:2] == QDRANT_SERVER_VERSION.split(".")[:2]
