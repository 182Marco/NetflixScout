"""RagTool end to end on an embedded Qdrant index: a cited movie the index lacks steers the search with its stored vector."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from test_qdrant_app_integration import DIM, TITLES, _vec, build_index, env_for

import app as app_module
from tool.rag.FromQueryEmbeddingToRes import retrieval, vectorstore
from tool.rag.FromQueryEmbeddingToRes.models import QuerySignals, ReferenceTitle
from tool.rag.FromQueryEmbeddingToRes.reference_flow import ReferenceFlow
from tool.rag.FromQueryEmbeddingToRes.store import point_uuid
from tool.rag.FromQueryEmbeddingToRes.store.catalog import CatalogStore
from tool.rag.FromQueryEmbeddingToRes.store.collection import close_clients, open_collection
from tool.rag.FromQueryEmbeddingToRes.tool_interface import RagTool

PLOT = "A crew crosses a wormhole to find a new home for humanity while time slows down around them. " * 2


class TmdbScript:
    def __init__(self):
        self.calls = []

    def __call__(self, *, title=None, year=None, tmdb_id=None, turn_id=None):
        self.calls.append((title, year, tmdb_id, turn_id))
        if title == "Interstellar":
            rec = dict(tmdb_id=157336, title="Interstellar", overview=PLOT, year=2014, fetched_ts=2_000_000_000_000, genres=("Drama",))
            return SimpleNamespace(record=rec, reason="", calls=2, tmdb_id=157336)
        return SimpleNamespace(record=None, reason="not_found", calls=1, tmdb_id=None)


@pytest.fixture
def rig(tmp_path, monkeypatch):
    build_index(tmp_path / "q")
    overrides = {**app_module.vector_store_overrides(env_for(tmp_path / "q"))["rag"]}
    config = app_module.build_runtime_config({"rag": {**overrides, "reference": {"enabled": True},
                                                      "signals": {"avoid_query": True, "reference_titles": True}}})["rag"]
    config = app_module._resolve_runtime_config(config)
    col = open_collection("netflix_scout", config["vectorstore"])
    embedded = []

    def embed_text(text):
        embedded.append(text)
        return _vec(2)  # the plot of the absent movie is "like Film Gamma"

    tmdb = TmdbScript()
    flow = ReferenceFlow(store=col.store, catalog=CatalogStore(col.store.client, "netflix_scout", col.store.meta.model, DIM),
                         read_film=lambda **kw: tmdb(**kw), embed_text=embed_text, strategy="average_vector")
    parsed = {"signals": QuerySignals(semantic_query="a quiet drama", like_titles=[ReferenceTitle(title="Interstellar", year=2014)],
                                      avoid_titles=[ReferenceTitle(title="Film Delta")])}
    monkeypatch.setattr(retrieval, "_extract_query_signals", lambda query, llm_model, hint=None, **kw: parsed["signals"])
    monkeypatch.setattr(vectorstore, "embed", lambda texts, backend=None, model=None: np.array([_vec(0)], dtype=np.float32))  # the QUERY vector
    monkeypatch.setattr(retrieval, "rerank_cohere", lambda q, chunks, model, cohere_api_client=None:
                        [{**c, "score": 1.0 - n / 10} for n, c in enumerate(chunks)])
    yield SimpleNamespace(config=config, col=col, flow=flow, tmdb=tmdb, embedded=embedded, parsed=parsed)
    close_clients()


def run(rig, flow, **extra):
    tool = RagTool(config={**rig.config, "retrieval": {**rig.config["retrieval"], "k_finale": 2, "k_largo": 4}}, reference_flow=flow)
    result = tool.run(query="film come Interstellar ma non come Film Delta", params={"turn_id": "t1", **extra}, conversation_history=[])
    data = {s["kind"]: s["data"] for s in result["trace"]}
    return result, data


def test_the_persisted_vector_of_an_absent_movie_steers_the_qdrant_search(rig):
    plain, plain_trace = run(rig, None)  # no flow: today's behaviour, the query vector alone
    steered, trace = run(rig, rig.flow)
    assert [c["title"] for c in plain["chunks"]][0] == "Film Alpha"
    assert plain_trace["retrieval"]["references"] == {"used": False, "skipped": "reference_flow_unavailable"}
    refs = trace["retrieval"]["references"]
    assert refs["steered"] is True and refs["strategy"] == "average_vector" and refs["positive_vectors"] == 1 and refs["negative_vectors"] == 1
    by_title = {r["title"]: r for r in refs["references"]}
    assert by_title["Interstellar"]["status"] == "resolved" and by_title["Interstellar"]["source"] == "tmdb_inserted"
    assert by_title["Interstellar"]["detail"]["embedding_created"] is True and by_title["Film Delta"]["source"] == "index"
    # the query alone finds Alpha first; with X's persisted vector (axis 2) Gamma enters the final results too
    assert {c["title"] for c in steered["chunks"]} == {"Film Alpha", "Film Gamma"}
    assert "Film Delta" not in {c["title"] for c in trace["retrieval"]["chunks"]}  # the avoided reference never comes back
    assert steered["metadata"]["references_summary"] == [
        "like 'Interstellar': used, a vector made from its TMDb plot (new)", "avoid 'Film Delta': used, its vector from the index"]
    point = rig.col.store.client.retrieve("netflix_scout", ids=[point_uuid("tmdb:movie:157336")], with_vectors=True, with_payload=True)[0]
    assert point.payload["source"] == "tmdb" and np.allclose(point.vector, np.asarray(_vec(2)) / 1.0)
    assert rig.embedded == [PLOT.strip()] and rig.tmdb.calls == [("Interstellar", 2014, None, "t1")]


def test_the_second_request_reuses_the_stored_embedding(rig):
    run(rig, rig.flow)
    again, trace = run(rig, rig.flow)
    assert len(rig.embedded) == 1 and len(rig.tmdb.calls) == 1 and rig.col.count() == len(TITLES) + 1
    ref = next(r for r in trace["retrieval"]["references"]["references"] if r["title"] == "Interstellar")
    assert ref["detail"] == {"origin": "catalog", "tmdb_calls": 0, "embedding_created": False}


def test_when_tmdb_fails_the_search_goes_on_with_the_description_alone(rig):
    rig.parsed["signals"] = QuerySignals(semantic_query="a quiet drama", like_titles=[ReferenceTitle(title="Unknown", year=2030)])
    result, trace = run(rig, rig.flow)
    refs = trace["retrieval"]["references"]
    assert refs["steered"] is False and refs["references"][0]["status"] == "unavailable" and refs["references"][0]["detail"]["reason"] == "not_found"
    assert [c["title"] for c in result["chunks"]][0] == "Film Alpha" and rig.col.count() == len(TITLES)


def test_references_are_inert_without_the_switch_or_a_flow(rig):
    rig.config["reference"]["enabled"] = False
    result, trace = run(rig, rig.flow)
    assert trace["retrieval"]["references"] == {"used": False, "skipped": "disabled"} and rig.tmdb.calls == []
    assert "references_summary" not in result["metadata"]
