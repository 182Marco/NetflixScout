from __future__ import annotations

import json

import pytest

from movie_db.harness.evaluation.routing_cases import DB, RAG, ROUTING_CASES, TMDB, RequestExpectation, RoutingCase
from movie_db.harness.evaluation.run_routing_eval import (
    RecordingClient,
    check_any_request,
    check_requests,
    main,
    run_routing_cases,
    select_cases,
)
from orchestrator import LLMOrchestrator


class FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = "fake"
        self.input_schema = {}

    def run(self, *, query, params=None, conversation_history=None):
        raise AssertionError("routing eval must not run tools")


class ScriptedClient:
    def __init__(self, outputs: list[str | Exception]) -> None:
        self.outputs = outputs
        self.responses = self

    def create(self, **kwargs):
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return type("Response", (), {"output_text": output})()


def _run(cases, outputs):
    config = {"orchestrator": {"fallback_tool": RAG, "tool_confidence_threshold": 0.6, "allowed_tools": [RAG, DB, TMDB]}}
    orchestrator = LLMOrchestrator(
        config=config,
        tools=[FakeTool(RAG), FakeTool(DB), FakeTool(TMDB)],
        client=RecordingClient(ScriptedClient(outputs)),
    )
    return run_routing_cases(
        cases,
        orchestrator=orchestrator,
        classify=lambda q, history=None: {"is_cinema": True, "is_italian": True},
        context_size=2,
    )


def _plan(tool: str, confidence: float = 0.9, standalone: str = "q", arguments=None) -> str:
    return json.dumps(
        {"standalone_query": standalone, "tool_name": tool, "arguments": arguments or {}, "confidence": confidence}
    )


def _arguments_for(expected: RequestExpectation) -> dict:
    request = {"operation": expected.operation, **dict(expected.fields)}
    if expected.facets:
        request["facets"] = list(expected.facets)
    return {"requests": [request]}


TMDB_CASES = tuple(case for case in ROUTING_CASES if case.expected_tool == TMDB)
DUNE = next(case for case in TMDB_CASES if "Dune" in case.question)


def test_explicit_choice_passes() -> None:
    [result] = _run((RoutingCase("film più votati", DB),), [_plan(DB)])

    assert result.source == "planner"
    assert result.passed


def test_silent_fallbacks_are_detected_and_fail() -> None:
    db_case = RoutingCase("film più votati", DB)
    rag_case = RoutingCase("di cosa parla Inception?", RAG)

    invalid, low, crashed = _run((rag_case, db_case, rag_case), ["not json", _plan(DB, 0.2), RuntimeError("offline")])

    # The fallback tool is rag_search: even the "right" tool fails when it was not chosen.
    assert (invalid.tool, invalid.source, invalid.passed) == (RAG, "fallback: invalid JSON", False)
    assert low.source.startswith("fallback: confidence") and not low.passed
    assert (crashed.tool, crashed.source, crashed.passed) == (RAG, "fallback: planner call failed", False)


def test_follow_up_requires_the_rewritten_query() -> None:
    case = next(c for c in ROUTING_CASES if c.history)

    good, bad = _run((case, case), [_plan(DB, standalone="Film horror più votati anni '90"), _plan(DB, standalone="E degli anni '90?")])

    assert good.passed
    assert not bad.passed


def test_cases_cover_every_tool_and_follow_ups() -> None:
    tools = [case.expected_tool for case in ROUTING_CASES]

    assert tools.count(DB) >= 5 and tools.count(RAG) >= 5 and tools.count(TMDB) >= 10
    assert any(case.history and case.expected_tool == TMDB for case in ROUTING_CASES)
    assert len(ROUTING_CASES) == 22


def test_every_tmdb_case_has_a_valid_request_expectation() -> None:
    assert len(TMDB_CASES) == 11
    for case in TMDB_CASES:
        assert case.expected_request is not None
        options = case.expected_request if isinstance(case.expected_request, tuple) else (case.expected_request,)
        for option in options:
            # Every alternative must itself be a request the tool accepts.
            assert check_requests(option, _arguments_for(option), case.question) is None


def test_coherent_tmdb_requests_pass() -> None:
    arguments = {
        "requests": [
            {"operation": "movie_details", "title": "Dune: Part Two", "facets": ["watch_providers", "credits"], "region": "it"},
        ],
    }

    [result] = _run((DUNE,), [_plan(TMDB, arguments=arguments)])

    assert result.requests_problem is None and result.passed


def test_flat_request_and_extra_requests_are_accepted() -> None:
    flat = {"operation": "movie_details", "title": "Dune - Parte Due", "facets": ["watch_providers"]}
    several = {"requests": [{"operation": "search", "kind": "movie", "search_query": "Dune"}, flat]}

    assert check_requests(DUNE.expected_request, flat, "q") is None
    assert check_requests(DUNE.expected_request, several, "q") is None


@pytest.mark.parametrize(
    ("arguments", "problem"),
    [
        ({}, "invalid requests"),
        ({"requests": [{"operation": "watch_now", "title": "Dune"}]}, "invalid requests"),
        ({"requests": [{"operation": "trending", "title": "Dune"}]}, "invalid requests"),
        ({"requests": [{"operation": "movie_details", "title": "Dune", "facets": ["seasons"]}]}, "invalid requests"),
        ({"requests": [{"operation": "movie_details", "title": "Dune"}]}, "no request matches"),
        ({"requests": [{"operation": "movie_details", "title": "Arrival", "facets": ["watch_providers"]}]}, "no request matches"),
        ({"requests": [{"operation": "tv_details", "title": "Dune", "facets": ["watch_providers"]}]}, "no request matches"),
        (["movie_details"], "arguments is not an object"),
    ],
)
def test_invalid_or_incoherent_tmdb_requests_fail(arguments, problem) -> None:
    [result] = _run((DUNE,), [_plan(TMDB, arguments=arguments)])

    assert result.tool == TMDB and result.source == "planner"
    assert result.requests_problem.startswith(problem)
    assert not result.passed


def test_requests_are_not_checked_when_the_tool_is_wrong() -> None:
    [result] = _run((DUNE,), [_plan(RAG)])

    assert result.requests_problem is None and not result.passed


def test_enum_fields_must_match() -> None:
    trending = next(
        case for case in TMDB_CASES
        if not isinstance(case.expected_request, tuple) and case.expected_request.operation == "trending"
    )
    day = {"requests": [{"operation": "trending", "media": "movie", "window": "day"}]}
    week = {"requests": [{"operation": "trending", "media": "movie", "window": "week"}]}

    assert check_requests(trending.expected_request, day, "q").startswith("no request matches")
    assert check_requests(trending.expected_request, week, "q") is None


def test_select_cases_filters_by_expected_tool() -> None:
    assert select_cases(TMDB) == TMDB_CASES
    assert select_cases(None) == ROUTING_CASES


def test_cli_requires_live_and_accepts_only_known_tools() -> None:
    with pytest.raises(SystemExit):
        main(["--tool", TMDB])
    with pytest.raises(SystemExit):
        main(["--live", "--tool", "unknown_tool"])


def test_known_regressions_are_routing_cases() -> None:
    by_question = {case.question: case for case in ROUTING_CASES}

    assert by_question["Parlami del film Arrival"].expected_tool == TMDB
    assert by_question["Dimmi qualcosa su Dune"].expected_tool == TMDB
    assert by_question["Di cosa parla Inception?"].expected_tool == TMDB
    assert sum(case.expected_tool == RAG and "temi di Mare dentro" in case.question for case in ROUTING_CASES) == 1


def test_any_acceptable_request_passes_and_none_fails() -> None:
    dune = next(case for case in ROUTING_CASES if case.question == "Dimmi qualcosa su Dune")
    details = {"requests": [{"operation": "movie_details", "title": "Dune"}]}
    search = {"requests": [{"operation": "search", "kind": "movie", "search_query": "Dune"}]}
    trending = {"requests": [{"operation": "trending", "media": "movie", "window": "week"}]}

    assert check_any_request(dune.expected_request, details, "q") is None
    assert check_any_request(dune.expected_request, search, "q") is None
    assert check_any_request(dune.expected_request, trending, "q").startswith("no request matches")
