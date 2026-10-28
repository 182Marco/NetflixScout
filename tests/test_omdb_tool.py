from __future__ import annotations

import json
import re

import pytest

from omdb_support import (
    BAD_KEY,
    LIMIT,
    NOT_FOUND,
    SECRET,
    TOO_MANY,
    UNKNOWN_ID,
    by_endpoint,
    make_tool,
    record,
    search_answer,
    search_hit,
)
from orchestrator import Tool
from tool.omdb.tool import OMDB_TOOL_NAME, OmdbTool, planner_schema
from turn import STEP_OMDB_CALLS, TOOL_PARAM_TURN_ID, TOOL_PARAM_TURN_LANGUAGE

ID = "tt1000001"


def _meta(result):
    return result["metadata"]["omdb"]


def _run(tool, **params):
    params.setdefault("imdb_id", ID)
    return tool.run(query="punteggi della critica", params=params)


# --- contract ------------------------------------------------------------------------------


def test_the_tool_follows_the_common_contract() -> None:
    tool, _ = make_tool()

    assert isinstance(tool, Tool) and tool.name == OMDB_TOOL_NAME == "omdb_search"
    assert tool.input_schema == planner_schema() and "description" not in tool.input_schema
    assert len(json.dumps(tool.input_schema)) < 2000
    assert tool.credentials is not None


def test_the_result_has_the_common_shape_and_keeps_urls_out_of_the_prompt() -> None:
    tool, _ = make_tool(by_endpoint(by_id={ID: record()}))
    result = _run(tool)

    assert set(result) == {"query", "chunks", "outcome", "metadata", "trace"}
    assert result["chunks"] == [] and result["outcome"] == {"status": "ok", "reason": None}
    assert [step["kind"] for step in result["trace"]] == [STEP_OMDB_CALLS]
    assert "http" not in json.dumps(result["metadata"]) and "omdbapi" not in json.dumps(result["metadata"])


# --- identification ---------------------------------------------------------------------------


def test_an_imdb_id_costs_one_request_and_no_title_search() -> None:
    tool, transport = make_tool(by_endpoint(by_id={ID: record()}))
    result = _run(tool)

    assert transport.params == [{"i": ID, "r": "json"}]
    meta = _meta(result)
    assert (meta["status"], meta["imdb_id"], meta["title"], meta["year"], meta["type"]) == ("ok", ID, "Sample Movie", "2016", "movie")


def test_a_title_is_searched_then_the_record_is_read_by_id() -> None:
    tool, transport = make_tool(by_endpoint(search=search_answer(search_hit(ID, "Sample Movie", "2016")), by_id={ID: record()}))
    result = _run(tool, imdb_id=None, title="sample movie")

    assert [sorted(p) for p in transport.params] == [["r", "s"], ["i", "r"]]
    assert _meta(result)["status"] == "ok" and _meta(result)["imdb_id"] == ID


def test_the_type_goes_to_the_search_but_the_year_is_checked_locally() -> None:
    tool, transport = make_tool(by_endpoint(search=search_answer(search_hit(ID, "Sample", "2008–2013", "series")), by_id={ID: record(title="Sample", year="2008–2013", kind="series")}))
    result = _run(tool, imdb_id=None, title="Sample", year=2010, type="series")

    assert transport.params[0] == {"s": "Sample", "r": "json", "type": "series"}
    assert _meta(result)["status"] == "ok" and _meta(result)["type"] == "series"


def test_an_ambiguous_title_returns_alternatives_and_no_score_and_no_second_request() -> None:
    hits = [search_hit("tt1000001", "Sample Movie", "1984"), search_hit("tt1000002", "Sample Movie", "2021")]
    tool, transport = make_tool(by_endpoint(search=search_answer(*hits)))
    result = _run(tool, imdb_id=None, title="Sample Movie")

    meta = _meta(result)
    assert meta["status"] == "ambiguous" and meta["ratings"] == [] and len(meta["candidates"]) == 2
    assert result["outcome"] == {"status": "empty", "reason": "ambiguous"} and len(transport.calls) == 1


def test_a_similar_but_different_title_is_unverified_and_gets_no_score() -> None:
    tool, transport = make_tool(by_endpoint(search=search_answer(search_hit(ID, "The Sinners", "2025"))))
    result = _run(tool, imdb_id=None, title="The Sinner")

    assert _meta(result)["status"] == "unverified" and _meta(result)["ratings"] == [] and len(transport.calls) == 1


@pytest.mark.parametrize("answer", [NOT_FOUND, search_answer()])
def test_a_title_that_does_not_exist_is_not_found(answer) -> None:
    tool, _ = make_tool(by_endpoint(search=answer))
    result = _run(tool, imdb_id=None, title="Nothing Like This")

    assert _meta(result)["status"] == "not_found" and result["outcome"] == {"status": "empty", "reason": "not_found"}


def test_too_many_results_is_unverified_with_its_reason() -> None:
    tool, _ = make_tool(by_endpoint(search=TOO_MANY))
    result = _run(tool, imdb_id=None, title="a")

    assert _meta(result)["status"] == "unverified" and result["outcome"]["reason"] == "too_many_results"


@pytest.mark.parametrize("answer", [NOT_FOUND, UNKNOWN_ID])
def test_an_unknown_imdb_id_is_not_found(answer) -> None:
    tool, _ = make_tool(lambda params: answer)
    result = _run(tool)

    assert _meta(result)["status"] == "not_found" and result["outcome"] == {"status": "empty", "reason": "not_found"}


def test_a_record_with_another_id_is_never_given_scores() -> None:
    tool, _ = make_tool(by_endpoint(by_id={ID: record(imdb_id="tt9999999")}))
    result = _run(tool)

    assert result["outcome"] == {"status": "error", "reason": "id_mismatch"} and _meta(result)["status"] == "error"
    assert "ratings" not in _meta(result)


def test_a_record_with_another_title_than_the_identified_one_is_rejected() -> None:
    hit = search_hit(ID, "Sample Movie", "2016")
    tool, _ = make_tool(by_endpoint(search=search_answer(hit), by_id={ID: record(title="Other Movie")}))

    assert _run(tool, imdb_id=None, title="Sample Movie")["outcome"]["reason"] == "id_mismatch"


# --- scores ---------------------------------------------------------------------------------


def test_all_scores_available() -> None:
    tool, _ = make_tool(by_endpoint(by_id={ID: record()}))
    ratings = {row["source"]: row for row in _meta(_run(tool))["ratings"]}

    assert {k: v["value"] for k, v in ratings.items()} == {"imdb": 7.9, "metascore": 81.0, "rotten_tomatoes": 94.0}
    assert {k: v["kind"] for k, v in ratings.items()} == {"imdb": "audience", "metascore": "critics", "rotten_tomatoes": "critics"}


def test_missing_scores_are_listed_as_not_available_and_the_run_still_succeeds() -> None:
    tool, _ = make_tool(by_endpoint(by_id={ID: record(rotten=None, metascore=None)}))
    result = _run(tool)
    ratings = {row["source"]: row["status"] for row in _meta(result)["ratings"]}

    assert ratings == {"imdb": "available", "metascore": "not_available", "rotten_tomatoes": "not_available"}
    assert result["outcome"]["status"] == "ok"


def test_a_work_with_no_score_at_all_is_empty_with_a_reason_and_no_invented_value() -> None:
    tool, _ = make_tool(by_endpoint(by_id={ID: record(imdb=None, metascore=None, rotten=None, votes=None)}))
    result = _run(tool)

    assert result["outcome"] == {"status": "empty", "reason": "no_ratings"}
    assert [row["status"] for row in _meta(result)["ratings"]] == ["not_available"] * 3
    assert all(row["value"] is None for row in _meta(result)["ratings"])


def test_the_plot_and_other_fields_never_reach_the_prompt() -> None:
    tool, _ = make_tool(by_endpoint(by_id={ID: record()}))
    result = _run(tool)

    assert "must never reach" not in json.dumps(result)


# --- errors --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("route", "reason"),
    [
        ((401, {}, LIMIT), "quota_exceeded"),
        ((401, {}, BAD_KEY), "unauthorized"),
        ((500, {}, b"x"), "http_error"),
        (TimeoutError("t"), "timeout"),
        (OSError("n"), "network_error"),
    ],
)
def test_api_and_network_errors_are_an_error_outcome_with_the_call_in_the_trace(route, reason) -> None:
    tool, _ = make_tool(route)
    result = _run(tool)

    assert result["outcome"] == {"status": "error", "reason": reason}
    assert _meta(result)["status"] == "error" and result["chunks"] == []
    assert result["trace"][0]["data"]["calls"] == [{"method": "GET", "url": "https://www.omdbapi.com/?i=tt1000001&r=json&apikey=***"}]


def test_an_invalid_request_is_rejected_before_any_call_and_without_the_values() -> None:
    tool, transport = make_tool()

    for params in ({}, {"imdb_id": "not-an-id"}, {"title": "x", "stray": 1}, {"title": "x", "year": 1500}):
        result = tool.run(query="q", params=params)
        assert result["outcome"] == {"status": "error", "reason": "invalid_request"}
        assert "not-an-id" not in json.dumps(result)
    assert transport.calls == []


def test_a_missing_key_is_a_clean_error_without_any_call(monkeypatch) -> None:
    from tool.omdb import tool as tool_module
    from tool.omdb.config import OmdbConfig
    from tool.omdb.errors import OmdbConfigError

    def no_key():
        raise OmdbConfigError("OMDb API key missing: set OMDB_API_KEY in .env.")

    monkeypatch.setattr(tool_module, "load_credentials", no_key)
    tool = OmdbTool(config=OmdbConfig(max_calls_per_turn=2))
    result = tool.run(query="q", params={"imdb_id": ID})

    assert result["outcome"] == {"status": "error", "reason": "not_configured"} and result["trace"] == []


def test_the_key_never_appears_in_any_output() -> None:
    for route in (by_endpoint(by_id={ID: record()}), (401, {}, LIMIT), OSError(f"failed {SECRET}")):
        tool, _ = make_tool(route)
        assert SECRET not in json.dumps(_run(tool), default=str)


# --- turn scope: budget, memo, no cache between turns ----------------------------------------


def test_the_same_request_twice_in_a_turn_is_one_http_call() -> None:
    tool, transport = make_tool(by_endpoint(by_id={ID: record()}))

    first = _run(tool, **{TOOL_PARAM_TURN_ID: "t1"})
    second = _run(tool, **{TOOL_PARAM_TURN_ID: "t1"})

    assert len(transport.calls) == 1 and _meta(first)["ratings"] == _meta(second)["ratings"]


def test_a_new_turn_asks_omdb_again_there_is_no_cache_between_turns() -> None:
    tool, transport = make_tool(by_endpoint(by_id={ID: record()}))

    _run(tool, **{TOOL_PARAM_TURN_ID: "t1"})
    _run(tool, **{TOOL_PARAM_TURN_ID: "t2"})

    assert len(transport.calls) == 2


def test_runs_without_a_turn_id_do_not_share_anything() -> None:
    tool, transport = make_tool(by_endpoint(by_id={ID: record()}))

    _run(tool)
    _run(tool)

    assert len(transport.calls) == 2


def test_the_budget_is_per_turn_not_per_run() -> None:
    ids = {f"tt100000{n}": record(imdb_id=f"tt100000{n}") for n in range(1, 4)}
    tool, transport = make_tool(by_endpoint(by_id=ids), max_calls=2)
    results = [_run(tool, imdb_id=f"tt100000{n}", **{TOOL_PARAM_TURN_ID: "t1"}) for n in range(1, 4)]

    assert [r["outcome"]["status"] for r in results] == ["ok", "ok", "error"]
    assert results[2]["outcome"]["reason"] == "turn_limit" and len(transport.calls) == 2
    # The next turn has its own budget.
    assert _run(tool, imdb_id="tt1000001", **{TOOL_PARAM_TURN_ID: "t2"})["outcome"]["status"] == "ok"


def test_a_title_lookup_traces_both_requests_with_their_own_parameters_in_order() -> None:
    hit = search_hit(ID, "Sample Movie", "2016")
    tool, transport = make_tool(by_endpoint(search=search_answer(hit), by_id={ID: record()}))
    result = _run(tool, imdb_id=None, title="Sample Movie", type="movie")

    calls = result["trace"][0]["data"]["calls"]
    assert [call["method"] for call in calls] == ["GET", "GET"]
    assert [call["url"] for call in calls] == [
        "https://www.omdbapi.com/?s=Sample+Movie&r=json&type=movie&apikey=***",
        f"https://www.omdbapi.com/?i={ID}&r=json&apikey=***",
    ]
    assert len(transport.calls) == 2 and SECRET not in json.dumps(result)


def test_the_trace_of_a_run_lists_only_its_own_calls() -> None:
    ids = {"tt1000001": record(), "tt1000002": record(imdb_id="tt1000002")}
    tool, _ = make_tool(by_endpoint(by_id=ids))
    _run(tool, imdb_id="tt1000001", **{TOOL_PARAM_TURN_ID: "t1"})
    second = _run(tool, imdb_id="tt1000002", **{TOOL_PARAM_TURN_ID: "t1"})

    assert len(second["trace"][0]["data"]["calls"]) == 1


def test_the_turn_language_is_accepted_and_ignored() -> None:
    tool, _ = make_tool(by_endpoint(by_id={ID: record()}))

    assert _run(tool, **{TOOL_PARAM_TURN_LANGUAGE: "de"})["outcome"]["status"] == "ok"


def test_no_module_writes_a_cache_to_disk() -> None:
    from pathlib import Path

    import tool.omdb as package

    for path in Path(package.__file__).parent.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\bopen\(|write_text|sqlite3|pickle|shelve|lru_cache|functools\.cache", text), path.name


def test_five_candidates_of_one_turn_are_verified_by_title_within_the_budget_of_ten_requests() -> None:
    titles = [f"Film {n}" for n in range(1, 6)]
    ids = {f"tt200000{n}": record(imdb_id=f"tt200000{n}", title=f"Film {n}", year="2025") for n in range(1, 6)}

    def handler(params):
        if "s" in params:
            n = params["s"].split()[-1]
            return search_answer(search_hit(f"tt200000{n}", params["s"], "2025"))
        return ids.get(params["i"], NOT_FOUND)

    from tool.omdb.config import load_omdb_config
    import app as app_module

    tool, transport = make_tool(handler, max_calls=load_omdb_config(app_module.CONFIG["omdb"]).max_calls_per_turn)
    results = [tool.run(query="q", params={"title": t, "year": 2025, TOOL_PARAM_TURN_ID: "t1"}) for t in titles]

    assert [r["outcome"]["status"] for r in results] == ["ok"] * 5 and len(transport.calls) == 10
    assert [_meta(r)["title"] for r in results] == titles
    assert tool.run(query="q", params={"title": "Film 6", TOOL_PARAM_TURN_ID: "t1"})["outcome"]["reason"] == "turn_limit"


def test_a_title_with_no_score_at_all_or_not_found_never_gets_a_value_in_a_multi_title_turn() -> None:
    blank = record(imdb_id="tt3000001", title="New Film", imdb=None, metascore=None, rotten=None, votes=None)
    tool, _ = make_tool(
        lambda p: search_answer(search_hit("tt3000001", "New Film", "2026")) if "s" in p and p["s"] == "New Film"
        else blank if p.get("i") == "tt3000001" else NOT_FOUND
    )
    new = tool.run(query="q", params={"title": "New Film", TOOL_PARAM_TURN_ID: "t1"})
    missing = tool.run(query="q", params={"title": "Nothing Here", TOOL_PARAM_TURN_ID: "t1"})

    assert new["outcome"] == {"status": "empty", "reason": "no_ratings"}
    assert all(row["value"] is None and "display" not in row for row in _meta(new)["ratings"])
    assert missing["outcome"] == {"status": "empty", "reason": "not_found"} and _meta(missing)["ratings"] == []
