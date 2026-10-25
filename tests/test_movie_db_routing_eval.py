from __future__ import annotations

import json

import pytest

from movie_db.harness.evaluation.routing_cases import (
    DB,
    RAG,
    ROUTING_CASES,
    TMDB,
    YOUTUBE,
    RequestExpectation,
    RoutingCase,
    VideoExpectation,
)
from movie_db.harness.evaluation.run_routing_eval import (
    RecordingClient,
    check_any_request,
    check_any_video,
    check_requests,
    check_video,
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
    tools = [RAG, DB, TMDB, YOUTUBE]
    config = {"orchestrator": {"fallback_tool": RAG, "tool_confidence_threshold": 0.6, "allowed_tools": tools}}
    orchestrator = LLMOrchestrator(
        config=config,
        tools=[FakeTool(name) for name in tools],
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


def _video_arguments_for(expected: VideoExpectation) -> dict:
    """The smallest arguments meeting `expected`: title and kinds, every optional field empty."""
    return {"title": expected.title, "kinds": list(expected.kinds)}


TMDB_CASES = tuple(case for case in ROUTING_CASES if case.expected_tool == TMDB)
DUNE = next(case for case in TMDB_CASES if "Dune" in case.question)
YOUTUBE_CASES = tuple(case for case in ROUTING_CASES if case.expected_tool == YOUTUBE)
OPPENHEIMER = next(case for case in YOUTUBE_CASES if "Cillian Murphy" in case.question)


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
    assert tools.count(YOUTUBE) == 7
    assert any(case.history and case.expected_tool == TMDB for case in ROUTING_CASES)
    assert any(case.history and case.expected_tool == YOUTUBE for case in ROUTING_CASES)
    assert len(ROUTING_CASES) == 43


def test_every_tmdb_case_has_a_valid_request_expectation() -> None:
    assert len(TMDB_CASES) == 18
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


def test_clarification_is_an_explicit_planner_choice() -> None:
    sorrentino = next(case for case in ROUTING_CASES if "Sorrentino" in case.question)
    plan = json.dumps({"standalone_query": "q", "tool_name": None, "arguments": {}, "confidence": 0.9,
                       "needs_clarification": True, "clarification_question": "Quale film?"})

    [asked] = _run((sorrentino,), [plan])
    [searched] = _run((sorrentino,), [_plan(RAG)])

    assert asked.tool == "clarification" and asked.source == "planner" and asked.passed
    assert not searched.passed


def test_every_youtube_case_has_a_valid_video_expectation() -> None:
    for case in YOUTUBE_CASES:
        assert case.expected_video is not None and case.expected_request is None
        options = case.expected_video if isinstance(case.expected_video, tuple) else (case.expected_video,)
        for option in options:
            # Every alternative must itself be input the tool accepts.
            assert check_video(option, _video_arguments_for(option), case.question) is None


def test_youtube_cases_cover_the_agreed_rules() -> None:
    by_question = {case.question: case for case in ROUTING_CASES}

    def kinds(question: str) -> set[str]:
        expected = by_question[question].expected_video
        options = expected if isinstance(expected, tuple) else (expected,)
        return {kind for option in options for kind in option.kinds}

    assert kinds("Trovami un'intervista al regista di Past Lives") == {"director_interview"}
    assert kinds("Ci sono interviste a Cillian Murphy su Oppenheimer?") == {"cast_interview"}
    assert kinds("Ci sono video del dietro le quinte di Barbie?") == {"behind_the_scenes", "making_of"}
    assert kinds("Cercami su YouTube il trailer di Past Lives") == {"trailer"}
    # A trailer without YouTube stays on TMDb; accepting the YouTube offer moves it there.
    assert by_question["Mostrami il trailer di Past Lives"].expected_tool == TMDB
    accepted = by_question["Sì, cercalo pure"]
    assert accepted.history and "YouTube" in accepted.history[-1]["content"]
    assert kinds("Sì, cercalo pure") == {"trailer"}


def test_youtube_plan_with_given_values_passes() -> None:
    arguments = {"title": "Oppenheimer", "cast": ["Cillian Murphy"], "kinds": ["cast_interview"]}

    [result] = _run((OPPENHEIMER,), [_plan(YOUTUBE, arguments=arguments)])

    assert result.requests_problem is None and result.passed


@pytest.mark.parametrize(
    ("arguments", "problem"),
    [
        ({}, "invalid arguments"),
        ({"title": "Oppenheimer", "kinds": ["interview"]}, "invalid arguments"),
        ({"title": "Oppenheimer", "kinds": ["cast_interview"], "channel": "x"}, "invalid arguments"),
        ({"title": "Dune", "kinds": ["cast_interview"]}, "title"),
        ({"title": "Oppenheimer", "kinds": ["director_interview"]}, "missing kinds"),
        ({"title": "Oppenheimer", "kinds": ["cast_interview", "trailer"]}, "kinds not requested"),
        # Values the user never gave, even if true, are invented.
        ({"title": "Oppenheimer", "kinds": ["cast_interview"], "year": 2023}, "year not given"),
        ({"title": "Oppenheimer", "kinds": ["cast_interview"], "director": "Christopher Nolan"}, "director not given"),
        ({"title": "Oppenheimer", "kinds": ["cast_interview"], "cast": ["Cillian Murphy", "Emily Blunt"]}, "cast not given"),
        (["cast_interview"], "arguments is not an object"),
    ],
)
def test_invalid_or_invented_youtube_arguments_fail(arguments, problem) -> None:
    [result] = _run((OPPENHEIMER,), [_plan(YOUTUBE, arguments=arguments)])

    assert result.tool == YOUTUBE and result.source == "planner"
    assert result.requests_problem.startswith(problem)
    assert not result.passed


def test_localized_title_only_rejects_deduced_titles_and_people() -> None:
    case = next(case for case in YOUTUBE_CASES if "airone" in case.question)
    base = {"title": "Il ragazzo e l'airone", "kinds": ["cast_interview"]}

    assert check_any_video(case.expected_video, base, "q") is None
    for extra in ({"alternative_titles": ["The Boy and the Heron"]}, {"director": "Hayao Miyazaki"}, {"year": 2023}):
        assert check_any_video(case.expected_video, {**base, **extra}, "q") is not None


def test_title_given_in_parentheses_may_be_copied_either_way() -> None:
    case = next(case for case in YOUTUBE_CASES if "Zone of Interest" in case.question)
    italian = {"title": "La zona d'interesse", "alternative_titles": ["The Zone of Interest"], "kinds": ["director_interview"]}
    english = {"title": "The Zone of Interest", "alternative_titles": ["La zona d'interesse"], "kinds": ["director_interview"]}
    invented = {**italian, "alternative_titles": ["Strefa interesów"]}

    assert check_any_video(case.expected_video, italian, "q") is None
    assert check_any_video(case.expected_video, english, "q") is None
    assert check_any_video(case.expected_video, invented, "q") == "alternative_titles not given in the conversation"


def test_accepted_offer_needs_the_title_and_allows_the_year_from_the_history() -> None:
    case = next(case for case in YOUTUBE_CASES if case.history)
    arguments = {"title": "Aftersun", "year": 2022, "kinds": ["trailer"]}

    good, vague = _run(
        (case, case),
        [_plan(YOUTUBE, standalone="Cerca su YouTube il trailer di Aftersun", arguments=arguments),
         _plan(YOUTUBE, standalone="Sì, cercalo pure", arguments=arguments)],
    )

    assert good.passed
    assert not vague.passed
    assert check_any_video(case.expected_video, {**arguments, "year": 2023}, "q") == "year not given in the conversation"


def test_turn_language_is_ignored_like_the_tool_does() -> None:
    arguments = {"title": "Oppenheimer", "cast": ["Cillian Murphy"], "kinds": ["cast_interview"], "turn_language": "it"}

    assert check_any_video(OPPENHEIMER.expected_video, arguments, "q") is None


def test_select_cases_includes_youtube() -> None:
    assert select_cases(YOUTUBE) == YOUTUBE_CASES


def test_check_rag_requires_the_asked_count() -> None:
    from movie_db.harness.evaluation.routing_cases import RagExpectation
    from movie_db.harness.evaluation.run_routing_eval import check_rag

    assert check_rag(RagExpectation(k_finale=5), {"query": "x", "k_finale": 5}) is None
    assert "k_finale" in check_rag(RagExpectation(k_finale=5), {"k_finale": 3})
    assert check_rag(RagExpectation(k_finale=(None, 1)), {"query": "x"}) is None


def test_rag_params_verdict_counts_only_objective_gains() -> None:
    from movie_db.harness.evaluation.run_rag_params_eval import AbCase, verdict

    arm = {"returned": 3, "verified": 1, "contradicted": 0, "title_rank": None}
    asked = AbCase("dammi 5 film", count=5)
    assert verdict(arm, {**arm, "returned": 5}, asked) == "better"
    assert verdict({**arm, "returned": 5}, arm, asked) == "worse"
    assert verdict(arm, {**arm}, AbCase("x")) == "same"
    named = AbCase("quel film", title="truman")
    assert verdict(arm, {**arm, "title_rank": 1}, named) == "better"
