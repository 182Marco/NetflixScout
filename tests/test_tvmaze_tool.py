"""Contract of the TVmaze tool: result shape, outcomes, follow_up, budget per turn (offline)."""
from __future__ import annotations

import json

from orchestrator import Tool
from tool.tvmaze.tool import TvmazeTool, planner_schema
from tvmaze_support import episode, make_tool, routes_for, search, show


def run(tool, **params):
    return tool.run(query="the request", params=params)


def test_it_is_a_tool_with_a_short_planner_schema() -> None:
    tool, _ = make_tool()
    assert isinstance(tool, Tool) and isinstance(tool, TvmazeTool) and tool.name == "tvmaze_search"
    assert "description" not in planner_schema() and len(json.dumps(planner_schema())) < 2500


def test_info_costs_one_call_and_leaves_urls_out_of_the_prompt_metadata() -> None:
    tool, transport = make_tool(routes_for())
    result = run(tool, title="Sample Show")

    assert transport.paths == ["/search/shows"]
    assert result["outcome"] == {"status": "ok", "reason": None} or result["outcome"]["status"] == "ok"
    info = result["metadata"]["tvmaze"]["show"]
    assert info["status"] == "Running" and info["network"] == "Sample Net"
    assert "tvmaze.com" not in json.dumps(result["metadata"]) and "http" not in json.dumps(result["metadata"])
    step = result["trace"][0]
    assert step["kind"] == "tvmaze_calls"
    assert step["data"]["show"]["url"] == "https://www.tvmaze.com/shows/1/sample-show"
    assert step["data"]["license"]["name"] == "CC BY-SA 4.0"
    assert [c["url"] for c in step["data"]["calls"]] == [call[3] for call in transport.calls]
    assert "follow_up" not in result


def test_cast_and_next_share_one_embedded_call() -> None:
    tool, transport = make_tool(routes_for())
    data = run(tool, title="Sample Show", facets=["cast", "next"])["metadata"]["tvmaze"]

    assert transport.paths == ["/search/shows", "/shows/1"]
    assert transport.calls[1][1] == [("embed[]", "cast"), ("embed[]", "nextepisode")]
    assert data["cast"] == [{"person": "Ann Actor", "character": "Cora"}]
    assert data["next_episode"]["name"] == "Next One" and data["next_episode"]["airdate"] == "2030-01-01"


def test_no_upcoming_episode_is_said_not_invented() -> None:
    routes = routes_for()
    routes["/shows/1"] = {**show(), "_embedded": {}}
    data = run(make_tool(routes)[0], title="Sample Show", facets=["next"])["metadata"]["tvmaze"]
    assert data["next_episode"] is None and "no upcoming" in data["next_episode_note"]


def test_seasons_and_one_season_of_episodes() -> None:
    tool, transport = make_tool(routes_for())
    data = run(tool, title="Sample Show", facets=["seasons", "episodes"], season=2)["metadata"]["tvmaze"]

    assert [row["season"] for row in data["seasons"]] == [1, 2]
    assert data["episodes"]["season"] == 2 and data["episodes"]["total_in_season"] == 2
    assert [row["name"] for row in data["episodes"]["episodes"]] == ["Return", "A Special"]
    assert transport.paths == ["/search/shows", "/shows/1/seasons", "/shows/1/episodes"]
    assert "spoiler" not in json.dumps(data)


def test_one_episode_by_number() -> None:
    data = run(make_tool(routes_for())[0], title="Sample Show", facets=["episodes"], season=1, episode=2)["metadata"]["tvmaze"]
    assert [row["name"] for row in data["episodes"]["episodes"]] == ["Second"]


def test_invalid_input_sends_nothing() -> None:
    tool, transport = make_tool(routes_for())
    result = run(tool, title="Sample Show", facets=["episodes"])
    assert result["outcome"]["reason"] == "invalid_request" and transport.calls == [] and result["trace"] == []


def test_unknown_title_offers_a_follow_up_to_another_source() -> None:
    tool, _ = make_tool({"/search/shows": []})
    result = run(tool, title="La casa di carta")
    assert result["outcome"]["status"] == "empty" and result["metadata"]["tvmaze"]["status"] == "not_found"
    assert result["follow_up"]["available"] and result["follow_up"]["reasons"] == ["not_found"]
    assert "tmdb_search" in result["follow_up"]["summary"]


def test_ambiguous_titles_return_alternatives_and_no_data() -> None:
    routes = {"/search/shows": search(show(1, "The Office", "2005-03-24"), show(2, "The Office", "2001-07-09"))}
    result = run(make_tool(routes)[0], title="The Office")
    meta = result["metadata"]["tvmaze"]
    assert meta["status"] == "ambiguous" and len(meta["candidates"]) == 2 and "show" not in meta
    assert "follow_up" not in result  # the user chooses; another source would not settle it


def test_a_rate_limit_is_an_error_with_a_follow_up_and_the_next_run_sends_nothing() -> None:
    tool, transport = make_tool({"/search/shows": (429, {}, b"")})
    first = run(tool, title="x")
    second = tool.run(query="again", params={"title": "y", "turn_id": "t2"})

    assert first["outcome"] == {"status": "error", "reason": "rate_limited"} or first["outcome"]["reason"] == "rate_limited"
    assert first["follow_up"]["available"] and second["follow_up"]["reasons"] == ["rate_limited"]
    assert len(transport.calls) == 1


def test_a_failing_section_does_not_lose_the_rest() -> None:
    routes = routes_for()
    routes["/shows/1/seasons"] = (500, {}, b"")
    result = run(make_tool(routes)[0], title="Sample Show", facets=["seasons", "episodes"], season=1)
    data = result["metadata"]["tvmaze"]
    assert data["unavailable"] == {"seasons": "http_error"} and data["episodes"]["total_in_season"] == 2
    assert result["outcome"]["status"] == "ok" and result["follow_up"]["available"]


def test_the_call_budget_is_shared_by_the_runs_of_a_turn() -> None:
    tool, transport = make_tool(routes_for(), max_calls=2)
    first = tool.run(query="q", params={"title": "Sample Show", "facets": ["seasons"], "turn_id": "t1"})
    second = tool.run(query="q", params={"title": "Sample Show", "facets": ["seasons", "episodes"], "season": 1, "turn_id": "t1"})
    assert first["metadata"]["tvmaze"]["seasons"]
    assert second["metadata"]["tvmaze"]["unavailable"] == {"episodes": "turn_limit"}
    assert len(transport.calls) == 2  # search + seasons; the second run reused both from the memo


def test_the_trace_of_a_run_lists_only_its_own_calls() -> None:
    tool, _ = make_tool(routes_for())
    tool.run(query="q", params={"title": "Sample Show", "turn_id": "t"})
    second = tool.run(query="q", params={"title": "Sample Show", "facets": ["seasons"], "turn_id": "t"})
    assert [c["url"].split("/")[-1] for c in second["trace"][0]["data"]["calls"]] == ["seasons"]
