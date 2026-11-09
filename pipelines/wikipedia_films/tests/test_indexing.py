"""Phase 3 tests: units and exception chunking, resumable embedding with a fake API, offline verification, Qdrant collection
(in memory and on a local path), per-film deduplication, guards. No network."""
from __future__ import annotations

import json
import hashlib
import types

import numpy as np
import pytest

openai = pytest.importorskip("openai")
httpx2 = pytest.importorskip("httpx2")
pytest.importorskip("tiktoken")
qdrant_client = pytest.importorskip("qdrant_client")
from qdrant_client import QdrantClient  # noqa: E402

from pipelines.wikipedia_films.indexing import embed_run as E  # noqa: E402
from pipelines.wikipedia_films.indexing import qdrant_index as Q  # noqa: E402
from pipelines.wikipedia_films.indexing import settings as S  # noqa: E402
from pipelines.wikipedia_films.indexing import units as U  # noqa: E402
from pipelines.wikipedia_films.indexing import verify_embeddings as V  # noqa: E402
from pipelines.wikipedia_films.indexing import wiki_search as W  # noqa: E402

COLL = S.TEST_PREFIX + "t"


def film(i: int, n_sentences: int = 3) -> dict:
    syn = " ".join(f"Frase numero {k} del film {i}, con personaggi e conflitti diversi." for k in range(n_sentences))
    return {"film_id": f"Q{i}", "wikipedia_page_id": i, "title": f"Film {i}", "synopsis": syn, "year": 1990 + i % 10,
            "director": [{"name": f"Regista {i}", "wikidata_id": None}], "actors": [{"name": f"Attore {i}", "wikidata_id": None, "character": None}],
            "genres": ["film drammatico"], "country": ["Italia"], "language": ["italiano"], "imdb_id": None,
            "wikipedia_url": f"https://it.wikipedia.org/wiki/Film_{i}", "original_title": None, "duration_minutes": 90,
            "source_revision_id": "1", "retrieved_at": "2026-11-01T00:00:00Z", "wikidata_id": f"Q{i}"}


@pytest.fixture
def small_limits(monkeypatch):
    monkeypatch.setattr(U, "MAX_INPUT_TOKENS", 120)
    monkeypatch.setattr(U, "EXCEPTION_CHUNK_TOKENS", 50)


@pytest.fixture
def source(tmp_path, monkeypatch, small_limits):
    """films.jsonl with 5 ordinary films and 1 over-the-limit film (chunked); module paths redirected to tmp."""
    films = [film(1), film(2), film(3, n_sentences=30), film(4), film(5), film(6)]
    path = tmp_path / "films.jsonl"
    path.write_text("\n".join(json.dumps(f, sort_keys=True) for f in films) + "\n")
    monkeypatch.setattr(U, "FILMS", path)
    monkeypatch.setattr(S, "FILMS", path)
    monkeypatch.setattr(S, "MANIFEST", tmp_path / "manifest.json")
    monkeypatch.setattr(E.S, "MANIFEST", tmp_path / "manifest.json")
    return films


class FakeEmbeddings:
    def __init__(self, fail_first: int = 0, kind="conn"):
        self.calls = 0
        self.fail_first, self.kind = fail_first, kind
        self.inputs: list[list[str]] = []

    def create(self, *, model, input, dimensions, encoding_format):
        self.calls += 1
        assert model == S.MODEL and dimensions == S.DIMENSIONS
        if self.calls <= self.fail_first:
            req = httpx2.Request("POST", "https://api.test/v1/embeddings")
            if self.kind == "rate":
                raise openai.RateLimitError("limit", response=httpx2.Response(429, request=req), body=None)
            raise openai.APIConnectionError(request=req)
        self.inputs.append(list(input))
        data = []
        for i, t in enumerate(input):
            rng = np.random.default_rng(int(hashlib.sha256(t.encode()).hexdigest()[:8], 16))
            v = rng.normal(size=S.DIMENSIONS)
            data.append(types.SimpleNamespace(index=i, embedding=(v / np.linalg.norm(v)).tolist()))
        return types.SimpleNamespace(data=data[::-1], usage=types.SimpleNamespace(total_tokens=sum(U.ntok(t) for t in input)))


class FakeClient:
    def __init__(self, **kw):
        self.embeddings = FakeEmbeddings(**kw)


def test_ordinary_films_are_single_units_and_only_the_long_one_is_chunked(source):
    units = U.build_units()
    per = {}
    for u in units:
        per.setdefault(u.film_id, []).append(u)
    assert [len(per[f"Q{i}"]) for i in (1, 2, 4, 5, 6)] == [1] * 5
    chunks = per["Q3"]
    assert len(chunks) > 3
    assert all(c.film_id == "Q3" and c.chunk_count == len(chunks) and c.tokens <= 120 for c in chunks)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert len({u.unit_id for u in units}) == len(units)
    covered = " ".join(c.text for c in chunks)
    assert all(s in covered for s in U.sentences(source[2]["synopsis"]))  # nothing truncated, nothing lost


def test_ordinary_synopsis_is_embedded_unchanged(source):
    by = {u.film_id: u for u in U.build_units() if u.chunk_count == 1}
    assert by["Q1"].text == source[0]["synopsis"]


def test_shards_are_deterministic_and_respect_the_caps(source, monkeypatch):
    units = U.build_units()
    monkeypatch.setattr(U, "REQUEST_MAX_INPUTS", 4)
    monkeypatch.setattr(U, "REQUEST_MAX_TOKENS", 400)
    a, b = U.make_shards(units), U.make_shards(units)
    assert [[u.unit_id for u in s] for s in a] == [[u.unit_id for u in s] for s in b]
    assert all(len(s) <= 4 and sum(u.tokens for u in s) <= 400 for s in a)
    assert sum(len(s) for s in a) == len(units)


def test_embedding_run_verify_and_resume_without_new_requests(source, tmp_path, monkeypatch):
    monkeypatch.setattr(U, "REQUEST_MAX_INPUTS", 3)
    d = tmp_path / "shards"
    client = FakeClient()
    r = E.run(client, directory=d, workers=2)
    assert r["requested_now"] == r["shards"] and r["reused"] == 0
    first_calls = client.embeddings.calls
    r2 = E.run(client, directory=d, workers=2)
    assert r2["requested_now"] == 0 and r2["reused"] == r["shards"] and client.embeddings.calls == first_calls
    report = V.verify(directory=d)
    n_units = len(U.build_units())
    assert report["ok"] and report["vectors"] == n_units == report["units"]
    assert report["dimension"] == 1536 and report["nan"] == report["inf"] == report["zero_vectors"] == 0
    assert report["duplicate_unit_ids"] == 0 and list(report["chunked_films"]) == ["Q3"]
    assert report["api_tokens"] == report["local_tokens"]
    assert (tmp_path / "manifest.json").exists()


def test_corrupt_shard_is_regenerated_and_missing_shard_is_detected(source, tmp_path, monkeypatch):
    monkeypatch.setattr(U, "REQUEST_MAX_INPUTS", 3)
    d = tmp_path / "shards"
    client = FakeClient()
    E.run(client, directory=d, workers=1)
    victim = sorted(d.glob("shard_*.npz"))[1]
    victim.write_bytes(b"not a shard")
    before = client.embeddings.calls
    r = E.run(client, directory=d, workers=1)
    assert r["requested_now"] == 1 and client.embeddings.calls == before + 1
    victim.unlink()
    with pytest.raises(FileNotFoundError):
        V.verify(write_manifest=False, directory=d)


def test_changed_source_text_invalidates_the_plan(source, tmp_path, monkeypatch):
    d = tmp_path / "shards"
    E.run(FakeClient(), directory=d, workers=1)
    rows = [json.loads(l) for l in U.FILMS.read_text().splitlines()]
    rows[0]["synopsis"] += " Una frase aggiunta."
    U.FILMS.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n")
    with pytest.raises(ValueError):
        V.verify(write_manifest=False, directory=d)


def test_nan_vector_is_reported(source, tmp_path):
    d = tmp_path / "shards"
    E.run(FakeClient(), directory=d, workers=1)
    from pipelines.wikipedia_films.indexing.shardio import read_shard, shard_path, write_shard
    s = read_shard(shard_path(0, d))
    s.vectors[0, 0] = np.nan
    write_shard(shard_path(0, d), 0, s.unit_ids, s.vectors, list(s.tokens), s.meta)
    assert V.verify(write_manifest=False, directory=d)["ok"] is False


def test_transient_errors_are_retried_and_budget_is_enforced(source, tmp_path, monkeypatch):
    monkeypatch.setattr(E.time, "sleep", lambda s: None)
    monkeypatch.setattr(E, "_Pause", E._Pause)
    for kind in ("conn", "rate"):
        d = tmp_path / f"s_{kind}"
        monkeypatch.setattr(E.random, "uniform", lambda a, b: 0.0)
        monkeypatch.setattr(S, "MAX_ATTEMPTS", 4)
        client = FakeClient(fail_first=2, kind=kind)
        if kind == "rate":  # a 429 trips the shared pause: shrink it so the test does not wait
            monkeypatch.setattr(E, "_request", _fast_pause(E._request))
        r = E.run(client, directory=d, workers=1)
        assert r["errors"] == [] and client.embeddings.calls >= 3
    with pytest.raises(E.BudgetExceeded):
        E.run(FakeClient(), directory=tmp_path / "s_budget", max_usd=1e-9, workers=1)


def _fast_pause(orig):
    def run(client, shard, pause, sleep=None):
        pause.until = 0.0
        out = orig(client, shard, pause, sleep)
        pause.until = 0.0
        return out
    return run


def _memory_index(source, tmp_path, monkeypatch, client=None):
    monkeypatch.setattr(U, "REQUEST_MAX_INPUTS", 3)
    d = tmp_path / "shards"
    E.run(FakeClient(), directory=d, workers=1)
    units = U.build_units()
    vectors, _ = V.load_all(units, d)
    films = {f["film_id"]: f for f in source}
    client = client or QdrantClient(":memory:")
    rep = Q.build_index(client=client, collection=COLL, units=units, vectors=vectors, films=films)
    return client, units, vectors, films, rep


def test_collection_counts_vectors_payload_and_check(source, tmp_path, monkeypatch):
    client, units, vectors, films, rep = _memory_index(source, tmp_path, monkeypatch)
    assert rep["count_ok"] and rep["points_in_collection"] == len(units)
    chk = Q.check_index(client=client, collection=COLL, units=units, vectors=vectors, films=films)
    assert chk["ok"], chk
    assert chk["vector_size"] == 1536 and "cosine" in chk["distance"].lower()
    assert chk["chunked_films"]["Q3"]["points"] == chk["chunked_films"]["Q3"]["expected"] > 1
    p = client.retrieve(COLL, ids=[Q.point_id("Q1", 0)], with_payload=True)[0].payload
    assert p["title"] == "Film 1" and p["synopsis"] == films["Q1"]["synopsis"] and p["director_names"] == ["Regista 1"]


def test_search_returns_one_result_per_film_and_recovers_all_chunks(source, tmp_path, monkeypatch):
    client, units, vectors, films, _ = _memory_index(source, tmp_path, monkeypatch)
    chunked = [i for i, u in enumerate(units) if u.film_id == "Q3"]
    q = vectors[chunked].mean(axis=0)  # close to every chunk of the long film: the raw point search would return several
    raw = client.query_points(COLL, query=q.tolist(), limit=20).points
    assert sum(1 for p in raw if p.payload["film_id"] == "Q3") > 1
    hits = W.search_films(client, q, limit=6, collection=COLL)
    ids = [h.film_id for h in hits]
    assert len(ids) == len(set(ids)) and ids[0] == "Q3"
    assert hits[0].payload["title"] == "Film 3" and hits[0].payload["synopsis"] == films["Q3"]["synopsis"]
    full = W.get_film(client, "Q3", COLL)
    assert len(full["chunks"]) == len(chunked) and full["film"]["chunk_count"] == len(chunked)
    assert W.get_film(client, "Q404", COLL) is None


def test_similarity_search_finds_the_film_by_its_own_vector(source, tmp_path, monkeypatch):
    client, units, vectors, films, _ = _memory_index(source, tmp_path, monkeypatch)
    for i, u in enumerate(units):
        if u.chunk_count == 1:
            assert W.search_films(client, vectors[i], limit=1, collection=COLL)[0].film_id == u.film_id


def test_rebuild_is_idempotent_and_persistence_survives_reopen(source, tmp_path, monkeypatch):
    path = tmp_path / "qdrant"
    client = QdrantClient(path=str(path))
    client, units, vectors, films, rep = _memory_index(source, tmp_path, monkeypatch, client=client)
    again = Q.build_index(client=client, collection=COLL, units=units, vectors=vectors, films=films)
    assert again["points_in_collection"] == len(units) and again["resumed_existing"]       # upsert twice: no duplicates
    rebuilt = Q.build_index(client=client, collection=COLL, units=units, vectors=vectors, films=films, recreate=True)
    assert rebuilt["points_in_collection"] == len(units) and not rebuilt["resumed_existing"]
    client.close()
    reopened = QdrantClient(path=str(path))
    assert reopened.count(COLL, exact=True).count == len(units)
    assert W.search_films(reopened, vectors[0], limit=1, collection=COLL)[0].film_id == units[0].film_id


def test_the_old_collection_can_never_be_touched():
    for name in ("netflix_scout", "anything_else"):
        with pytest.raises(SystemExit):
            S.assert_own_collection(name)
        with pytest.raises(SystemExit):
            Q.build_index(client=QdrantClient(":memory:"), collection=name, units=[], vectors=np.zeros((0, 1536)), films={}, recreate=True)
    S.assert_own_collection(S.COLLECTION)


def test_check_accepts_vectors_that_qdrant_normalises(source, tmp_path, monkeypatch):
    """The API returns vectors within 1e-3 of unit norm; Qdrant (cosine) stores them normalised: the check must still pass."""
    monkeypatch.setattr(U, "REQUEST_MAX_INPUTS", 3)
    d = tmp_path / "shards"
    E.run(FakeClient(), directory=d, workers=1)
    units = U.build_units()
    vectors, _ = V.load_all(units, d)
    vectors = vectors * np.linspace(0.9993, 1.0008, len(units), dtype=np.float32)[:, None]
    films = {f["film_id"]: f for f in source}
    client = QdrantClient(":memory:")
    Q.build_index(client=client, collection=COLL, units=units, vectors=vectors, films=films)
    assert Q.check_index(client=client, collection=COLL, units=units, vectors=vectors, films=films)["ok"]
