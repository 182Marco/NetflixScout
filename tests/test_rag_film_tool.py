"""The film tool `rag_search` (tool/rag/film/): contract, planner hint, `k_finale` clamp, trace outside metadata. The retriever itself is replaced by a canned
`RagResult` (SIMULATED): its real path is covered by tests/test_film_index.py and the live harness."""
from __future__ import annotations

from tool.rag.film.params import resolve_retrieval
from tool.rag.film.results import QuerySignals, RagChunk, RagResult
from tool.rag.film.tool import RagTool


def _chunk(idx: int, title: str) -> RagChunk:
    return RagChunk(id=f"c{idx}", testo=f"trama {idx}", score=0.9 - idx / 10, title=title, release_year="1999")


def _result(query: str, **kw) -> RagResult:
    return RagResult(query=query, chunks=[_chunk(1, "Matrix")], candidates=[_chunk(1, "Matrix"), _chunk(2, "Dark City")], rerank_engine="llm",
                     signals=QuerySignals(semantic_query="Movies about robots", genres=["Science Fiction"]), embedded_text="Movies about robots", **kw)


def test_the_tool_returns_its_trace_outside_metadata(monkeypatch) -> None:
    monkeypatch.setattr("tool.rag.film.tool.run_film_index", lambda *, config, query, query_hint=None: _result(query))
    result = RagTool(config={}).run(query="film con robot", params={}, conversation_history=[])
    assert [step["kind"] for step in result["trace"]] == ["retrieval", "rerank", "selection"]
    assert len(result["trace"][0]["data"]["chunks"]) == 2
    assert [c["id"] for c in result["trace"][2]["data"]["chunks"]] == [c["id"] for c in result["chunks"]]
    assert result["trace"][1]["data"]["backend"] == "llm" and result["trace"][2]["title"] == "K stretto"
    assert "trace" not in result["metadata"] and result["outcome"]["status"] == "ok"
    assert result["trace"][0]["data"]["embedded_text"] == "Movies about robots"
    assert result["trace"][0]["data"]["signals"]["genres"] == ["Science Fiction"]


def test_the_user_query_drives_the_search_and_the_planner_rewrite_is_only_a_hint(monkeypatch) -> None:
    """Real case 13: a vague planner rewrite must not replace the user's request."""
    received: dict = {}

    def fake(*, config, query, query_hint=None):
        received.update(query=query, hint=query_hint)
        return RagResult(query=query, chunks=[], rerank_query="themes")

    monkeypatch.setattr("tool.rag.film.tool.run_film_index", fake)
    user = "Mare dentro mi ha colpito molto. Mi consigli altri film che affrontano temi simili?"
    vague = "Consiglia film simili a Mare dentro, che affrontino temi e atmosfere analoghi."
    planned = RagTool(config={}).run(query=user, params={"query": vague, "turn_language": "it"})
    assert received == {"query": user, "hint": vague} and planned["query"] == user
    assert planned["trace"][0]["data"]["planner_query"] == vague and planned["outcome"]["status"] == "empty"
    RagTool(config={}).run(query=user, params={"query": user})
    assert received["hint"] is None  # identical rewrite: no hint


def test_the_planner_k_finale_is_applied_to_a_copy_of_the_config(monkeypatch) -> None:
    seen: dict = {}

    def fake(*, config, query, query_hint=None):
        seen.update(config["retrieval"])
        return RagResult(query=query, chunks=[])

    monkeypatch.setattr("tool.rag.film.tool.run_film_index", fake)
    config = {"retrieval": {"k_finale": 3, "limits": {"k_finale": {"min": 1, "max": 10}}}}
    planned = RagTool(config=config).run(query="dammi 5 film", params={"query": "dammi 5 film", "k_finale": 50, "search_mode": "hybrid", "turn_id": "t1"})  # extras ignored
    assert seen == {"k_finale": 10} and config["retrieval"]["k_finale"] == 3
    data = planned["trace"][0]["data"]["retrieval_params"]
    assert data["overridden"] == ["k_finale"] and data["effective"] == {"k_finale": 10} and planned["metadata"]["k_finale"] == 10


DEFAULTS = {"k_finale": 3, "limits": {"k_finale": {"min": 1, "max": 10}}}


def test_k_finale_is_clamped_and_unusable_values_are_ignored() -> None:
    assert resolve_retrieval(DEFAULTS, {"query": "x", "turn_id": "t"}) == ({"k_finale": 3}, {})
    assert resolve_retrieval(DEFAULTS, {"k_finale": 99}) == ({"k_finale": 10}, {"k_finale": 10})
    assert resolve_retrieval(DEFAULTS, {"k_finale": 0})[0]["k_finale"] == 1
    for bad in ("tre", True, float("nan"), float("inf")):
        assert resolve_retrieval(DEFAULTS, {"k_finale": bad}) == ({"k_finale": 3}, {})
