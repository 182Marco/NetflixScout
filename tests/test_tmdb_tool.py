from __future__ import annotations

from tmdb_support import MOVIE_ID, calls_shown, make_tool, movie_payload, run, tmdb_meta

from orchestrator import Tool
from tmdb.auth import load_credentials
from tmdb.config import TmdbConfig
from tmdb.models.requests import TmdbToolInput
from tmdb.tool import TMDB_TOOL_NAME, TmdbTool


def test_tool_satisfies_the_protocol_and_schema_comes_from_pydantic() -> None:
    tool, _ = make_tool({})

    assert isinstance(tool, Tool)
    assert tool.name == TMDB_TOOL_NAME == "tmdb_search"
    assert tool.input_schema == TmdbToolInput.model_json_schema()


def test_result_shape_keeps_trace_outside_metadata() -> None:
    tool, _ = make_tool({f"/movie/{MOVIE_ID}": movie_payload()})

    result = run(tool, {"operation": "movie_details", "tmdb_id": MOVIE_ID})

    assert set(result) == {"query", "chunks", "metadata", "trace"}
    assert "trace" not in result["metadata"] and "calls" not in repr(result["metadata"])
    assert result["trace"][0]["kind"] == "tmdb_calls"
    chunk = result["chunks"][0]
    assert chunk["source"] == "tmdb" and chunk["release_year"] == "2014" and chunk["genres"] == "Fantascienza"


def test_flat_single_request_is_accepted() -> None:
    tool, transport = make_tool({f"/movie/{MOVIE_ID}": movie_payload()})

    result = tool.run(query="trama?", params={"operation": "movie_details", "tmdb_id": MOVIE_ID})

    assert transport.paths == [f"/movie/{MOVIE_ID}"]
    assert result["query"] == "trama?" and tmdb_meta(result)["status"] == "ok"


def test_partial_results_survive_failures_of_other_requests() -> None:
    tool, transport = make_tool({f"/movie/{MOVIE_ID}": movie_payload()})

    result = run(tool, {"operation": "movie_details", "tmdb_id": MOVIE_ID}, {"operation": "movie_details", "tmdb_id": 404})

    meta = tmdb_meta(result)
    assert meta["status"] == "partial"
    assert [r["status"] for r in meta["requests"]] == ["ok", "error"]
    assert len(result["chunks"]) == 1 and len(calls_shown(result)) == 2


def test_failed_requests_are_not_retried_in_the_same_turn() -> None:
    tool, transport = make_tool({"/movie/1": (503, {}, {})})

    run(tool, {"operation": "movie_details", "tmdb_id": 1}, {"operation": "movie_details", "tmdb_id": 1})
    run(tool, {"operation": "movie_details", "tmdb_id": 1})

    assert transport.paths == ["/movie/1", "/movie/1"]  # once per turn, never cached


def test_missing_credentials_fail_without_http(monkeypatch) -> None:
    def no_env_key():
        return load_credentials({})

    def no_http(*args):
        raise AssertionError("no HTTP call expected")

    monkeypatch.setattr("tmdb.tool.load_credentials", no_env_key)
    tool = TmdbTool(config=TmdbConfig(max_results=5, max_calls_per_turn=6, cache_ttl=0), transport=no_http)

    result = tool.run(query="q", params={"operation": "trending", "media": "movie", "window": "day"})

    assert tmdb_meta(result) == {
        "status": "error",
        "error": "not_configured",
        "detail": "TMDb API key missing: set VUE_APP_TMDB_API_KEY in .env.",
    }
    assert result["trace"] == []


def test_the_cache_is_shared_by_one_tool_instance_across_runs() -> None:
    tool, transport = make_tool({"/trending/movie/day": {"results": [{"id": 1, "title": "A"}]}})
    request = {"operation": "trending", "media": "movie", "window": "day"}

    run(tool, request)
    run(tool, request)

    assert transport.paths == ["/trending/movie/day"]
