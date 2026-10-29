"""Offline part of the Wikidata routing evaluation: the cases and the argument checks.

Nothing here calls an LLM. What the real planner chooses is measured only by
`python -m movie_db.harness.evaluation.run_routing_eval --live --tool wikidata_search`, which costs API
credits and has to be authorized separately. The cases pair relations between works (Wikidata) with
requests about the same works that must stay on other tools (TMDb).
"""
from __future__ import annotations

import pytest

from movie_db.harness.evaluation.routing_cases import ROUTING_CASES, TMDB, WIKIDATA, WikidataExpectation
from movie_db.harness.evaluation.run_routing_eval import check_any_wikidata, check_wikidata, main, select_cases

CASES = select_cases(WIKIDATA)
BY_QUESTION = {case.question: case for case in ROUTING_CASES}


def _arguments_for(option: WikidataExpectation, **extra) -> dict:
    return {"operation": option.operation, "title": option.title.title(), **extra}


def test_there_are_wikidata_cases_and_a_boundary_that_stays_on_tmdb() -> None:
    assert len(CASES) == 4  # source, remakes, series order and franchise, homonyms
    assert BY_QUESTION["Quanto dura Blade Runner 2049 e chi l'ha diretto?"].expected_tool == TMDB


def test_every_wikidata_case_has_an_expectation_the_tool_accepts() -> None:
    for case in CASES:
        assert case.expected_wikidata is not None and case.expected_request is None and case.expected_tvmaze is None
        options = case.expected_wikidata if isinstance(case.expected_wikidata, tuple) else (case.expected_wikidata,)
        for option in options:
            assert check_wikidata(option, _arguments_for(option), case.question) is None


def test_a_coherent_plan_passes_and_each_deviation_is_named() -> None:
    expected = BY_QUESTION["Quali remake ha The Departed?"].expected_wikidata
    plan = {"operation": "relations", "title": "The Departed"}

    assert check_any_wikidata(expected, plan, "q") is None
    assert "operation 'resolve'" in check_any_wikidata(expected, {**plan, "operation": "resolve"}, "q")
    assert "does not contain" in check_any_wikidata(expected, {**plan, "title": "Infernal Affairs"}, "q")
    assert check_any_wikidata(expected, {**plan, "year": 2006}, "q") == "year not given in the conversation"
    assert check_any_wikidata(expected, {**plan, "imdb_id": "tt0407887"}, "q") == "imdb_id not given in the conversation"
    assert check_any_wikidata(expected, "not an object", "q") == "arguments is not an object"


def test_a_year_in_the_question_is_allowed_and_one_that_is_not_there_is_not() -> None:
    expected = BY_QUESTION["Cosa viene dopo La cosa di John Carpenter del 1982 nella sua serie e a quale franchise appartiene?"].expected_wikidata

    assert check_any_wikidata(expected, {"operation": "relations", "title": "The Thing", "year": 1982}, "q") is None
    assert check_any_wikidata(expected, {"operation": "relations", "title": "The Thing", "year": 2011}, "q") == "year not given in the conversation"


def test_arguments_the_tool_would_refuse_fail_the_check() -> None:
    expected = BY_QUESTION["Quali remake ha The Departed?"].expected_wikidata

    # A TMDb id without its type is refused by the tool, so it cannot count as a good plan.
    result = check_any_wikidata(expected, {"operation": "relations", "title": "The Departed", "tmdb_id": 1422}, "q")
    assert result is not None and result.startswith("invalid arguments")


def test_the_cli_accepts_the_new_tool_name_only_with_live() -> None:
    with pytest.raises(SystemExit):
        main(["--tool", WIKIDATA])
