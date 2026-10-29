"""Offline part of the TVmaze routing evaluation: the cases and the argument checks.

Nothing here calls an LLM. What the real planner chooses is measured only by
`python -m movie_db.harness.evaluation.run_routing_eval --live --tool tvmaze_search`, which costs API
credits and has to be authorized separately. The cases pair structured series data (TVmaze) with
requests about the same series that must stay on other tools (TMDb).
"""
from __future__ import annotations

import pytest

from movie_db.harness.evaluation.routing_cases import ROUTING_CASES, TMDB, TVMAZE, TvmazeExpectation
from movie_db.harness.evaluation.run_routing_eval import check_any_tvmaze, check_tvmaze, main, select_cases

CASES = select_cases(TVMAZE)
BY_QUESTION = {case.question: case for case in ROUTING_CASES}


def _arguments_for(option: TvmazeExpectation, **extra) -> dict:
    arguments = {"title": option.title.title(), "facets": list(option.facets), **extra}
    if "episodes" in option.facets:
        arguments["season"] = 2
    return arguments


def test_there_are_tvmaze_cases_a_mixed_one_and_boundaries_that_stay_on_tmdb() -> None:
    assert len(CASES) == 5  # seasons (moved from TMDb), episodes, cast, next episode, cast + streaming
    assert BY_QUESTION["Quante stagioni ha Breaking Bad?"].expected_tool == TVMAZE
    assert BY_QUESTION["Consigliami serie simili a Dark"].expected_tool == TMDB
    assert BY_QUESTION["Dove posso vedere The Bear in Italia?"].expected_tool == TMDB
    assert BY_QUESTION["Mostrami il trailer della serie Severance"].expected_tool == TMDB
    mixed = BY_QUESTION["Chi c'è nel cast di Dark e dove posso vederla in streaming?"]
    assert mixed.also_uses == (TVMAZE, TMDB) and TMDB in mixed.alternative_first_tools


def test_every_tvmaze_case_has_an_expectation_the_tool_accepts() -> None:
    for case in CASES:
        assert case.expected_tvmaze is not None and case.expected_request is None and case.expected_video is None
        options = case.expected_tvmaze if isinstance(case.expected_tvmaze, tuple) else (case.expected_tvmaze,)
        for option in options:
            assert check_tvmaze(option, _arguments_for(option), case.question) is None


def test_a_coherent_plan_passes_and_each_deviation_is_named() -> None:
    expected = BY_QUESTION["Chi recita in Killing Eve e quali personaggi interpretano?"].expected_tvmaze
    plan = {"title": "Killing Eve", "facets": ["cast"]}

    assert check_any_tvmaze(expected, plan, "q") is None
    assert check_any_tvmaze(expected, {**plan, "facets": ["cast", "info"]}, "q") is None
    assert "missing facets" in check_any_tvmaze(expected, {**plan, "facets": ["info"]}, "q")
    assert "facets not requested" in check_any_tvmaze(expected, {**plan, "facets": ["cast", "seasons"]}, "q")
    assert "does not contain" in check_any_tvmaze(expected, {**plan, "title": "Villanelle"}, "q")
    assert check_any_tvmaze(expected, {**plan, "year": 2018}, "q") == "year not given in the conversation"
    assert check_any_tvmaze(expected, "not an object", "q") == "arguments is not an object"


def test_arguments_the_tool_would_refuse_fail_the_check() -> None:
    expected = BY_QUESTION["Quanti episodi ha la stagione 2 di Severance e quando sono usciti?"].expected_tvmaze
    # `episodes` without `season` is refused by the tool, so it cannot count as a good plan.
    result = check_any_tvmaze(expected, {"title": "Severance", "facets": ["episodes"]}, "q")
    assert result is not None and result.startswith("invalid arguments")
    assert check_any_tvmaze(expected, {"title": "Severance", "facets": ["episodes"], "season": 2}, "q") is None


def test_the_cli_accepts_the_new_tool_name_only_with_live() -> None:
    with pytest.raises(SystemExit):
        main(["--tool", TVMAZE])
