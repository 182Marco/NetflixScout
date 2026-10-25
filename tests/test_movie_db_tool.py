from __future__ import annotations

import json

from tool.movie_db.movie_db_tool import MOVIE_DB_TOOL_NAME, WORK_TYPE_UNVERIFIED, MovieDbTool
from orchestrator import LLMOrchestrator, Tool
from turn import STEP_DB_QUERY, TraceStep


class FakeClient:
    def __init__(self, output: str) -> None:
        self.output = output
        self.responses = self

    def create(self, **kwargs):
        return type("Response", (), {"output_text": self.output})()


def _tool(config, plan: dict | str) -> MovieDbTool:
    output = plan if isinstance(plan, str) else json.dumps(plan)
    return MovieDbTool(config=config, client=FakeClient(output))


def test_tool_respects_the_protocol(movie_db_config) -> None:
    tool = _tool(movie_db_config, {"operation": "most_rated"})

    assert isinstance(tool, Tool)
    assert tool.name == MOVIE_DB_TOOL_NAME
    assert tool.input_schema["properties"]["query"]["type"] == "string"


def test_run_returns_chunks_metadata_and_a_queries_only_trace(movie_db_config, capsys) -> None:
    tool = _tool(movie_db_config, {"operation": "top_rated", "genre": "Sci-Fi", "limit": 2})

    result = tool.run(query="i migliori sci-fi", params={}, conversation_history=[])

    assert set(result) == {"query", "chunks", "metadata", "trace", "outcome"}
    assert [c["title"] for c in result["chunks"]] == ["The Matrix", "Blade Runner"]
    assert result["outcome"] == {"status": "ok", "reason": None}
    assert result["metadata"] == {"operation": "top_rated", "row_count": 2, **WORK_TYPE_UNVERIFIED}
    assert len(result["trace"]) == 1
    step = TraceStep(**result["trace"][0])
    assert step.kind == STEP_DB_QUERY
    assert set(step.data) == {"queries"}
    assert set(step.data["queries"][0]) == {"sql", "params"}
    assert step.data["queries"][0]["sql"].startswith("SELECT")
    assert movie_db_config.db_path not in json.dumps(result)
    assert capsys.readouterr().out == ""


def test_chunks_are_readable_by_the_orchestrator(movie_db_config) -> None:
    tool = _tool(movie_db_config, {"operation": "by_title", "title": "Heat"})
    result = tool.run(query="voto di Heat", params={}, conversation_history=[])
    orchestrator = LLMOrchestrator(config={"orchestrator": {}}, tools=[tool], client=FakeClient(""))

    content = orchestrator._build_final_context(
        query="voto di Heat",
        tool_result={"tool_name": tool.name, **result},
    )[-1]["content"]

    assert "Heat 1995" in content
    assert "generi=Action, Crime, Thriller" in content
    assert "Voto medio 4.00/5 su 2 voti." in content


def test_genre_stats_become_chunks(movie_db_config) -> None:
    tool = _tool(movie_db_config, {"operation": "stats_by_genre", "limit": 1})

    result = tool.run(query="genere migliore", params={})
    chunk = result["chunks"][0]

    assert chunk["title"] == "Action"
    # Genre statistics are not titles: no work-type caveat.
    assert "work_type_verified" not in result["metadata"]
    assert chunk["testo"].startswith("Genere Action:")


def test_parser_error_gives_empty_result_without_queries(movie_db_config) -> None:
    tool = _tool(movie_db_config, '{"operation": "top_rated", "sql": "DROP TABLE movies"}')

    result = tool.run(query="x", params={})

    assert result["chunks"] == []
    assert result["metadata"]["operation"] is None
    assert "error" in result["metadata"]
    # The parser answered but nothing in the whitelist fits (e.g. a filter by actor).
    assert result["metadata"]["error_kind"] == "unsupported_request"
    assert result["outcome"] == {"status": "error", "reason": "unsupported_request"}
    assert result["trace"][0]["data"] == {"queries": []}


def test_missing_db_gives_error_result_not_exception(movie_db_config, tmp_path) -> None:
    config = movie_db_config.model_copy(update={"db_path": str(tmp_path / "missing.sqlite3")})
    tool = _tool(config, {"operation": "most_rated"})

    result = tool.run(query="x", params={})

    assert result["metadata"]["operation"] == "most_rated"
    assert "buildMovieDb.py" in result["metadata"]["error"]
    assert str(tmp_path) not in json.dumps(result)


def test_llm_arguments_cannot_inject_operations(movie_db_config) -> None:
    tool = _tool(movie_db_config, {"operation": "most_rated", "limit": 1})

    # Planner arguments are ignored except `query`: they never reach the SQL layer.
    result = tool.run(query="x", params={"sql": "DROP TABLE movies", "operation": "drop"})

    assert result["metadata"]["operation"] == "most_rated"


def test_movie_rows_are_never_presented_as_verified_films(movie_db_config) -> None:
    """MovieLens lists series too (e.g. Planet Earth II): the type is declared unverified."""
    tool = _tool(movie_db_config, {"operation": "top_rated", "limit": 1})

    result = tool.run(query="il film con il voto più alto", params={})

    assert result["metadata"]["work_type_verified"] is False
    assert "serie" in result["metadata"]["work_type_note"]
