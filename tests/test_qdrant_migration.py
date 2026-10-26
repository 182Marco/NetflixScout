"""Offline tests of the Chroma -> Qdrant migration and of its validator (in-memory Qdrant)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from qdrant_client import models

from tool.rag.EmbeddingProcess import migrate_chroma_to_qdrant as mig
from tool.rag.EmbeddingProcess import validate_migration as val
from tool.rag.FromQueryEmbeddingToRes.store import point_uuid
from tool.rag.FromQueryEmbeddingToRes.store.base import IndexMeta
from tool.rag.FromQueryEmbeddingToRes.store.qdrant_store import QdrantStore, open_client

DIM = mig.DIMENSION
ROOT = Path(__file__).resolve().parents[1]


class FakeChroma:
    """The slice of the Chroma collection API the migration uses."""

    def __init__(self, n: int = 7, seed: int = 1) -> None:
        rng = np.random.default_rng(seed)
        self.ids = [f"hash-{i:06d}-000000" for i in range(n)]
        # Not exactly unit length, like the OpenAI vectors stored in Chroma.
        self.vectors = [(v / np.linalg.norm(v) * 1.0003).astype(np.float32) for v in rng.normal(size=(n, DIM))]
        self.docs = [f"plot {i}" for i in range(n)]
        years = ["1999", "2001", None, "19xx", "1850", "2150", "1950"]
        self.metas = []
        for i in range(n):
            meta = {"source": "plots", "movie_id": str(100 + i), "title": f"The Film {i}"}
            if years[i % len(years)] is not None:
                meta["release_year"] = years[i % len(years)]
            self.metas.append(meta)
        if n > 6:
            self.metas[6] = {"source": "readme.md"}  # a non-film chunk: no title, no year

    def count(self) -> int:
        return len(self.ids)

    def get(self, limit: int, offset: int, include: list[str]) -> dict:
        sl = slice(offset, offset + limit)
        return {"ids": self.ids[sl], "embeddings": self.vectors[sl], "documents": self.docs[sl],
                "metadatas": self.metas[sl]}


def _store(client=None) -> QdrantStore:
    return QdrantStore(client or open_client("memory"), mig.COLLECTION, IndexMeta(mig.MODEL, DIM))


def _migrate(chroma, store, tmp_path, **kwargs):
    return mig.migrate(chroma_collection=chroma, store=store, run=mig.Run(tmp_path / "run"),
                       batch_size=kwargs.pop("batch_size", 3), **kwargs)


def test_full_migration_validates(tmp_path):
    chroma, store = FakeChroma(), _store()
    state = _migrate(chroma, store, tmp_path)
    assert state["complete"] and state["target_count"] == 7
    report = val.validate(chroma, store, page=3)
    assert report["passed"], report["anomaly_samples"]
    assert all(c["ok"] for c in report["checks"].values())
    assert report["checks"]["vectors"]["max_error"] <= val.TOLERANCE


def test_unconvertible_years_are_reported_not_invented(tmp_path):
    chroma, store = FakeChroma(), _store()
    _migrate(chroma, store, tmp_path)
    check = val.validate(chroma, store, page=3)["checks"]["release_year_int"]
    bad = {value for _, value in check["not_convertible_values"]}
    assert bad == {"19xx", "2150"}  # a non-year and an out-of-range year, listed as found
    assert check["not_convertible"] == 2 and check["converted"] == 3 and check["no_year_in_source"] == 2
    points, _ = store.client.scroll(store.collection, limit=50, with_payload=True)
    by_legacy = {p.payload["legacy_id"]: p.payload for p in points}
    assert "release_year_int" not in by_legacy[chroma.ids[3]]  # "19xx"
    assert "release_year_int" not in by_legacy[chroma.ids[5]]  # 2150
    assert by_legacy[chroma.ids[0]]["release_year_int"] == 1999


def test_repeat_is_idempotent_and_never_duplicates(tmp_path):
    chroma, store = FakeChroma(), _store()
    _migrate(chroma, store, tmp_path)
    _migrate(chroma, store, tmp_path, restart=True)
    assert store.count() == 7
    assert val.validate(chroma, store, page=3)["passed"]


def test_interrupted_run_resumes_without_duplicates(tmp_path):
    chroma, store = FakeChroma(n=8), _store()
    first = _migrate(chroma, store, tmp_path, max_batches=1)
    assert not first["complete"] and first["next_offset"] == 3 and first["target_count"] == 3
    assert not val.validate(chroma, store, page=3)["passed"]  # a partial copy never validates
    final = _migrate(chroma, store, tmp_path)
    assert final["complete"] and final["target_count"] == 8
    assert val.validate(chroma, store, page=3)["passed"]
    progress = json.loads((tmp_path / "run" / "progress.json").read_text())
    assert progress["complete"] and progress["next_offset"] == 8


def test_progress_of_another_source_is_refused(tmp_path):
    store = _store()
    _migrate(FakeChroma(n=8), store, tmp_path, max_batches=1)
    with pytest.raises(SystemExit, match="different source"):
        _migrate(FakeChroma(n=9), store, tmp_path)


def test_existing_collection_with_another_model_is_refused(tmp_path):
    client = open_client("memory")
    QdrantStore(client, mig.COLLECTION, IndexMeta("other-model", DIM)).create()
    with pytest.raises(ValueError, match="rebuild the index"):
        _migrate(FakeChroma(), _store(client), tmp_path)


def test_failed_upsert_is_retried_then_raised(tmp_path, monkeypatch):
    store = _store()
    real, calls = store.upsert, {"n": 0}

    def flaky(points):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("boom")
        real(points)

    monkeypatch.setattr(store, "upsert", flaky)
    monkeypatch.setattr(mig.time, "sleep", lambda s: None)
    assert _migrate(FakeChroma(), store, tmp_path)["complete"]

    def always(points):
        raise ConnectionError("down")

    broken = _store()
    monkeypatch.setattr(broken, "upsert", always)
    with pytest.raises(ConnectionError):
        _migrate(FakeChroma(), broken, tmp_path / "other", retries=2)


def test_empty_source_is_refused(tmp_path):
    with pytest.raises(SystemExit, match="empty"):
        _migrate(FakeChroma(n=0), _store(), tmp_path)


def test_source_guard_refuses_original_and_backup(tmp_path):
    for bad in (ROOT / "dbVettoriale" / "openai", ROOT / "dbVettoriale" / "openai" / "sub",
                Path.home() / "Backups" / "NetflixScout" / "pre-qdrant-20261026" / "openai"):
        with pytest.raises(SystemExit, match="refused"):
            mig.check_source(bad)
    with pytest.raises(SystemExit, match="not a folder"):
        mig.check_source(tmp_path / "missing")
    mig.check_source(tmp_path)  # a disposable folder is accepted


# ---- the validator must catch every kind of damage

def _migrated(tmp_path):
    chroma, store = FakeChroma(), _store()
    _migrate(chroma, store, tmp_path)
    return chroma, store


def _set_payload(store, legacy_id, **fields):
    store.client.set_payload(store.collection, payload=fields, points=[point_uuid(legacy_id)])


def _failed(report, check):
    assert not report["passed"] and not report["checks"][check]["ok"], report["anomaly_counts"]


def test_validator_catches_missing_and_extra_points(tmp_path):
    chroma, store = _migrated(tmp_path)
    store.client.delete(store.collection, points_selector=models.PointIdsList(points=[point_uuid(chroma.ids[2])]))
    report = val.validate(chroma, store, page=3)
    _failed(report, "count")
    assert report["anomaly_counts"]["missing_in_qdrant"] == 1

    chroma, store = _migrated(tmp_path / "b")
    vec = np.ones(DIM, dtype=np.float32).tolist()
    store.client.upsert(store.collection, [models.PointStruct(
        id=point_uuid("stranger"), vector=vec, payload={"legacy_id": "stranger", "document": "x"})])
    report = val.validate(chroma, store, page=3)
    _failed(report, "identifiers")
    assert report["anomaly_counts"]["extra_in_qdrant"] == 1


def test_validator_catches_document_and_metadata_damage(tmp_path):
    chroma, store = _migrated(tmp_path)
    _set_payload(store, chroma.ids[1], document="altered")
    _failed(val.validate(chroma, store, page=3), "documents")

    chroma, store = _migrated(tmp_path / "b")
    _set_payload(store, chroma.ids[1], title="Another Title")
    _failed(val.validate(chroma, store, page=3), "metadata")

    chroma, store = _migrated(tmp_path / "c")
    _set_payload(store, chroma.ids[1], surplus="field")
    _failed(val.validate(chroma, store, page=3), "metadata")


def test_validator_catches_vector_damage(tmp_path):
    chroma, store = _migrated(tmp_path)
    other = np.random.default_rng(99).normal(size=DIM).astype(np.float32).tolist()
    store.client.update_vectors(store.collection, [models.PointVectors(id=point_uuid(chroma.ids[4]), vector=other)])
    report = val.validate(chroma, store, page=3)
    _failed(report, "vectors")
    assert report["anomaly_counts"]["vector_out_of_tolerance"] == 1


def test_validator_catches_derived_field_damage(tmp_path):
    chroma, store = _migrated(tmp_path)
    _set_payload(store, chroma.ids[0], title_norm="wrong")
    _failed(val.validate(chroma, store, page=3), "title_norm")

    chroma, store = _migrated(tmp_path / "b")
    _set_payload(store, chroma.ids[0], release_year_int=1900)
    _failed(val.validate(chroma, store, page=3), "release_year_int")

    chroma, store = _migrated(tmp_path / "c")
    _set_payload(store, chroma.ids[3], release_year_int=1900)  # "19xx" must never get a year
    report = val.validate(chroma, store, page=3)
    _failed(report, "release_year_int")
    assert report["anomaly_counts"]["release_year_int_invented"] == 1


def test_validator_catches_wrong_index_meta(tmp_path):
    chroma, _ = _migrated(tmp_path)
    store = _store()
    other = QdrantStore(store.client, mig.COLLECTION, IndexMeta("other-model", DIM))
    other.create()
    _failed(val.validate(chroma, store, page=3), "index_meta")
