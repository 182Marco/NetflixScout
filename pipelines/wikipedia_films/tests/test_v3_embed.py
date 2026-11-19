"""`indexing.v3 embed`: the one command that makes the v3 vectors on a machine that has no Phase 3 shards (a fresh clone).
Offline: a fake OpenAI client, a tiny catalogue, temporary files; nothing touches the real data or the network."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from qdrant_client import QdrantClient

from pipelines.wikipedia_films.indexing import settings as S
from pipelines.wikipedia_films.indexing import v2 as V2M
from pipelines.wikipedia_films.indexing import v3


class FakeOpenAI:
    """Records every request; each text gets a deterministic vector, usage is one token per word."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.embeddings = SimpleNamespace(create=self._create)

    def _create(self, *, model, input, dimensions, encoding_format):
        assert (model, dimensions) == (S.MODEL, S.DIMENSIONS)
        self.calls.append(list(input))
        data = []
        for i, text in enumerate(input):
            rng = np.random.default_rng(abs(hash(text)) % (2**32))
            data.append(SimpleNamespace(index=i, embedding=rng.standard_normal(S.DIMENSIONS).astype(np.float32).tolist()))
        return SimpleNamespace(data=data, usage=SimpleNamespace(total_tokens=sum(len(t.split()) for t in input)), _request_id="req_fake")


@pytest.fixture()
def fresh_machine(tmp_path, monkeypatch):
    films = {f"Q{i}": {"film_id": f"Q{i}", "synopsis": f"Trama del film numero {i} con alcune parole."} for i in range(1, 6)}
    monkeypatch.setattr(v3, "catalogue", lambda: films)
    monkeypatch.setattr(v3, "_old_vectors", lambda: {})                      # no Phase 3 shards here
    monkeypatch.setattr(V2M, "NEW_VECTORS", tmp_path / "phase7_missing.npz")   # no Phase 7 file either
    monkeypatch.setattr(v3, "NEW_VECTORS", tmp_path / "new_vectors.npz")
    monkeypatch.setenv(v3.AUTH_ENV, "yes")
    return films


def test_embed_needs_the_authorisation_variable(fresh_machine, monkeypatch):
    monkeypatch.delenv(v3.AUTH_ENV)
    client = FakeOpenAI()
    with pytest.raises(SystemExit, match=v3.AUTH_ENV):
        v3.embed(client)
    assert client.calls == []


def test_embed_refuses_an_estimate_over_the_cap(fresh_machine):
    client = FakeOpenAI()
    with pytest.raises(SystemExit, match="exceeds the cap"):
        v3.embed(client, max_usd=0.0)
    assert client.calls == []


def test_embed_requests_every_missing_vector_then_nothing(fresh_machine):
    client = FakeOpenAI()
    first = v3.embed(client)
    assert first["to_embed"] == first["requested_now"] == 5 and first["requests"] == 1
    assert sum(len(c) for c in client.calls) == 5

    units = v3.all_units(v3.catalogue())
    vectors, missing = v3.vectors_for(units)          # `index` can now assemble all of them without any API call
    assert vectors.shape == (5, S.DIMENSIONS) and len(missing) == 5

    again = v3.embed(client)                           # idempotent: nothing is requested twice
    assert again["requested_now"] == 0 and again["requests"] == 0
    assert sum(len(c) for c in client.calls) == 5


def test_embed_resumes_after_an_interruption(fresh_machine):
    units = v3.all_units(v3.catalogue())
    missing = list(range(len(units)))
    have = {u.unit_id: np.ones(S.DIMENSIONS, dtype=np.float32) for u in units[:2]}   # two vectors were saved before the stop
    v3._save_fresh(units, missing, have, used_tokens=10, request_id="req_before")

    client = FakeOpenAI()
    result = v3.embed(client)
    assert result["requested_now"] == 3 and sum(len(c) for c in client.calls) == 3
    vectors, _ = v3.vectors_for(units)
    assert np.allclose(vectors[0], 1.0)               # the saved vectors are kept, not requested again


def test_index_stops_and_points_to_embed_when_a_vector_is_missing(fresh_machine):
    units = v3.all_units(v3.catalogue())
    with pytest.raises(SystemExit, match="embed"):
        v3.vectors_for(units)


def test_plan_says_what_a_fresh_machine_will_cost(fresh_machine):
    plan = v3.plan()
    assert plan["phase3_shards_found"] is False and plan["unavailable"] == 5
    assert plan["tokens_to_embed"] > 0 and plan["estimated_usd_to_embed"] >= 0 and plan["api_calls"] == 0


def test_legacy_collections_are_optional():
    """A new machine has no netflix_scout / v1 / v2: the digests are just empty, never an error."""
    client = QdrantClient(":memory:")
    assert v3._digests(client) == {}
