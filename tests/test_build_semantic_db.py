"""Rebuilding the index from the dataset, on a temporary Qdrant storage (no network, no key, real data untouched)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from tool.rag.EmbeddingProcess import buildSemanticDb as bsd
from tool.rag.FromQueryEmbeddingToRes.store import point_uuid
from tool.rag.FromQueryEmbeddingToRes.store.base import IndexMeta
from tool.rag.FromQueryEmbeddingToRes.store.collection import close_clients, open_collection
from tool.rag.FromQueryEmbeddingToRes.store.qdrant_store import QdrantStore, open_client

MODEL, DIM = "text-embedding-3-small", 1536


def meta_row(i, title, date, genres="{\"/m/1\": \"Drama\"}"):
    cols = [str(i), "/m/x", title, date, "", "", "{\"/m/02h40lc\": \"English Language\"}", "{\"/m/09c7w0\": \"United States of America\"}", genres]
    return "\t".join(cols)


def char_row(i, actor):
    cols = [str(i), "/m/x", "", "", "", "", "", "", actor]
    return "\t".join(cols + ["", "", "", ""])


@pytest.fixture
def dataset(tmp_path):
    root = tmp_path / "dataset" / "MovieSummaries"
    root.mkdir(parents=True)
    (root / "movie.metadata.tsv").write_text("\n".join([
        meta_row(1, "Deep Door", "2014-05-01"), meta_row(2, "The Old Farm", "1950"), meta_row(3, "No Year", "")]) + "\n")
    (root / "character.metadata.tsv").write_text("\n".join([char_row(1, "Ann Lee"), char_row(1, "Bob Ray"), char_row(2, "Cy Dunn")]) + "\n")
    (root / "plot_summaries.txt").write_text("\n".join([
        "1\tA lighthouse keeper discovers a hidden door.", "2\tA farmer loses his land.", "3\tA film without a year."]) + "\n")
    return tmp_path / "dataset"


class FakeEmbed:
    def __init__(self, dim=DIM):
        self.dim, self.calls, self.texts = dim, 0, []

    def __call__(self, texts, backend=None, model=None):
        self.calls += 1
        self.texts += list(texts)
        return np.array([np.random.default_rng(abs(hash(t)) % 2**32).normal(size=self.dim) for t in texts], dtype=np.float32)


@pytest.fixture(autouse=True)
def _close():
    yield
    close_clients()


def build(dataset, folder, monkeypatch, fake=None, **kw):
    fake = fake or FakeEmbed()
    monkeypatch.setattr(bsd, "embed", fake)
    count = bsd.build_semantic_db(dataset, None, kw.pop("collection", "netflix_scout"), 0.78, "openai", MODEL, kw.pop("batch_size", 2),
                                  engine="qdrant", qdrant={"mode": "embedded", "path": str(folder)})
    return count, fake


def test_rebuild_on_a_temporary_embedded_storage_reads_back_like_the_runtime_does(dataset, tmp_path, monkeypatch):
    folder = tmp_path / "q"
    count, fake = build(dataset, folder, monkeypatch)
    assert count == 3 and fake.calls == 2  # batches of 2
    collection = open_collection("netflix_scout", {"qdrant": {"mode": "embedded", "path": str(folder), "model": MODEL}})
    assert collection.count() == 3  # also passes check_meta: model and dimension are those of the config
    page = collection.get(limit=10, offset=0)
    by_title = {m.get("title"): (i, m) for i, m in zip(page["ids"], page["metadatas"])}
    cid, meta = by_title["Deep Door"]
    assert cid == bsd._stable_id("MovieSummaries/plot_summaries.txt", 0, 0)
    assert meta["release_year"] == "2014" and meta["cast"] == "Ann Lee; Bob Ray" and meta["movie_id"] == "1"
    assert meta["genres"] == "Drama" and meta["source"] == "MovieSummaries/plot_summaries.txt"
    store = collection.store
    point = store.client.retrieve("netflix_scout", ids=[point_uuid(cid)], with_payload=True)[0]
    assert point.payload["legacy_id"] == cid and point.payload["title_norm"] == "deep door"
    assert point.payload["release_year_int"] == 2014 and point.payload["document"].startswith("A lighthouse keeper")
    no_year = next(i for i, m in zip(page["ids"], page["metadatas"]) if m.get("title") == "No Year")
    assert "release_year_int" not in store.client.retrieve("netflix_scout", ids=[point_uuid(no_year)], with_payload=True)[0].payload


def test_a_rebuilt_index_has_the_ids_and_documents_of_the_chunks_collected_for_any_engine(dataset, tmp_path, monkeypatch):
    ids, texts, metas = bsd.collect_chunks(dataset, 0.78, "openai", MODEL)
    build(dataset, tmp_path / "q", monkeypatch)
    store = QdrantStore(open_client("embedded", path=tmp_path / "q"), "netflix_scout", IndexMeta(MODEL, DIM))
    try:
        rows = {r["id"]: r for r in store.scroll()}
        assert set(rows) == set(ids) and all(rows[i]["testo"] == t for i, t in zip(ids, texts))
    finally:
        store.close()


def test_a_non_empty_storage_is_refused_before_any_embedding(dataset, tmp_path, monkeypatch):
    folder = tmp_path / "q"
    folder.mkdir()
    (folder / "precious").write_text("keep")
    fake = FakeEmbed()
    with pytest.raises(FileExistsError, match="never overwrite"):
        build(dataset, folder, monkeypatch, fake)
    assert fake.calls == 0 and (folder / "precious").read_text() == "keep"


def test_an_existing_collection_is_never_replaced_and_costs_nothing(dataset, tmp_path, monkeypatch):
    first, _ = build(dataset, tmp_path / "a", monkeypatch)
    from tool.rag.FromQueryEmbeddingToRes.store import collection as col

    client = open_client("memory")
    QdrantStore(client, "netflix_scout", IndexMeta(MODEL, DIM)).create()
    monkeypatch.setattr(col, "open_client", lambda *a, **k: client)
    created = []
    monkeypatch.setattr(QdrantStore, "create", lambda self: created.append(self.collection))
    fake = FakeEmbed()
    monkeypatch.setattr(bsd, "embed", fake)
    with pytest.raises(FileExistsError, match="already exists"):
        bsd.build_semantic_db(dataset, None, "netflix_scout", 0.78, "openai", MODEL, 2,
                              engine="qdrant", qdrant={"mode": "server", "url": "http://x"})
    assert fake.calls == 0 and created == []  # nothing embedded, nothing created or replaced


@pytest.mark.parametrize("vectors,message", [
    (lambda texts: np.zeros((len(texts), DIM), dtype=np.float32), "zero or not finite"),
    (lambda texts: np.full((len(texts), DIM), np.nan, dtype=np.float32), "zero or not finite"),
    (lambda texts: np.ones((len(texts) - 1, DIM), dtype=np.float32), "returned"),
])
def test_bad_embeddings_stop_the_build(dataset, tmp_path, monkeypatch, vectors, message):
    monkeypatch.setattr(bsd, "embed", lambda texts, backend=None, model=None: vectors(texts))
    with pytest.raises(ValueError, match=message):
        bsd.build_semantic_db(dataset, None, "c", 0.78, "openai", MODEL, 2, engine="qdrant",
                              qdrant={"mode": "embedded", "path": str(tmp_path / "q")})


def test_embeddings_with_a_changing_dimension_are_refused(dataset, tmp_path, monkeypatch):
    sizes = iter([8, 9])
    monkeypatch.setattr(bsd, "embed", lambda texts, backend=None, model=None: np.ones((len(texts), next(sizes)), dtype=np.float32))
    with pytest.raises(ValueError, match="dimensions"):
        bsd.build_semantic_db(dataset, None, "c", 0.78, "openai", MODEL, 2, engine="qdrant",
                              qdrant={"mode": "embedded", "path": str(tmp_path / "q")})


def test_non_string_metadata_is_refused():
    with pytest.raises(ValueError, match="non-string"):
        bsd._validate_qdrant_metadata([{"title": "x", "year": 1999}], 0)


@pytest.mark.parametrize("kwargs,error", [
    ({"engine": "qdrant", "qdrant": {"mode": "memory"}}, "lost at exit"),
    ({"engine": "qdrant", "qdrant": {"mode": "embedded"}}, "needs a storage path"),
    ({"engine": "qdrant", "qdrant": {"mode": "server"}}, "needs a URL"),
    ({"engine": "qdrant", "qdrant": {"mode": "embedded", "path": "x"}, "backend": "local"}, "openai embedding"),
    ({"engine": "nope"}, "unknown"),
])
def test_configuration_errors_are_explicit(dataset, tmp_path, monkeypatch, kwargs, error):
    backend = kwargs.pop("backend", "openai")
    if kwargs.get("qdrant", {}).get("path"):
        kwargs["qdrant"]["path"] = str(tmp_path / "q")
    with pytest.raises(ValueError, match=error):
        bsd.build_semantic_db(dataset, None, "c", 0.78, backend, MODEL, 2, **kwargs)


def test_the_chroma_engine_keeps_its_legacy_behaviour(dataset, tmp_path, monkeypatch):
    calls = []
    db = tmp_path / "chroma"
    db.mkdir()
    (db / "old").write_text("x")

    class Coll:
        def count(self):
            return 3

    monkeypatch.setattr(bsd, "crea_collection", lambda name, db_dir: calls.append(("create", name, Path(db_dir))) or Coll())
    monkeypatch.setattr(bsd, "indicizza", lambda c, ids, texts, vecs, metas: calls.append(("index", len(ids))))
    monkeypatch.setattr(bsd, "embed", FakeEmbed())
    assert bsd.build_semantic_db(dataset, db, "c", 0.78, "openai", MODEL, 2) == 3
    assert not (db / "old").exists()  # legacy: the Chroma folder is recreated
    assert calls == [("create", "c", db), ("index", 2), ("index", 1)]


def test_cli_defaults_follow_the_environment_like_the_app(monkeypatch):
    monkeypatch.setenv("VECTORSTORE_ENGINE", "qdrant")
    monkeypatch.setenv("VECTORSTORE_QDRANT_MODE", "embedded")
    monkeypatch.setenv("VECTORSTORE_QDRANT_PATH", "/tmp/qq")
    monkeypatch.setattr(sys, "argv", ["x"])
    args = bsd.parse_args()
    assert args.engine == "qdrant" and bsd.qdrant_settings(args) == {"mode": "embedded", "url": None, "path": "/tmp/qq"}
    monkeypatch.delenv("VECTORSTORE_ENGINE")
    monkeypatch.delenv("VECTORSTORE_QDRANT_MODE")
    args = bsd.parse_args()
    assert args.engine == "chroma" and args.qdrant_mode == "server" and args.qdrant_url == "http://127.0.0.1:6333"
