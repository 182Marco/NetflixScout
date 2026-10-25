"""Offline part of the Wikipedia routing evaluation: the cases and the argument checks.

Nothing here calls an LLM. What the real planner chooses is measured only by
`python -m movie_db.harness.evaluation.run_routing_eval --live --tool wikipedia_search`, which
costs API credits and has to be authorized separately.
"""
from __future__ import annotations

import pytest

from movie_db.harness.evaluation.routing_cases import ROUTING_CASES, TMDB, WIKIPEDIA, WikipediaExpectation
from movie_db.harness.evaluation.run_routing_eval import check_any_wikipedia, check_wikipedia, main, select_cases
from wikipedia.tool import WikipediaTool

WIKI_CASES = select_cases(WIKIPEDIA)
BY_QUESTION = {case.question: case for case in ROUTING_CASES}
PARK = BY_QUESTION["Raccontami la vita e la carriera di Park Chan-wook"]
FOLLOW_UP = BY_QUESTION["Parlami meglio della sua formazione"]


def _arguments_for(option: WikipediaExpectation, **extra) -> dict:
    return {"topic": option.topic.title(), "kind": option.kinds[0], "depth": option.depths[0], **extra}


def test_there_are_wikipedia_cases_with_a_follow_up_and_a_boundary_with_tmdb() -> None:
    assert len(WIKI_CASES) == 4
    assert any(case.history for case in WIKI_CASES)
    assert BY_QUESTION["Dammi la filmografia di Park Chan-wook"].expected_tool == TMDB


def test_every_wikipedia_case_has_an_expectation_the_tool_accepts() -> None:
    for case in WIKI_CASES:
        assert case.expected_wikipedia is not None and case.expected_request is None and case.expected_video is None
        options = case.expected_wikipedia if isinstance(case.expected_wikipedia, tuple) else (case.expected_wikipedia,)
        for option in options:
            assert check_wikipedia(option, _arguments_for(option), case.question) is None


def test_the_cli_knows_the_wikipedia_tool() -> None:
    with pytest.raises(SystemExit):
        main(["--tool", WIKIPEDIA])  # --live is still required


def test_a_coherent_plan_passes() -> None:
    plan = {"topic": "Park Chan-wook", "kind": "person", "depth": "full"}

    assert check_any_wikipedia(PARK.expected_wikipedia, plan, "q") is None


@pytest.mark.parametrize(
    ("plan", "problem"),
    [
        ({"topic": "Oldboy", "kind": "person", "depth": "full"}, "topic 'Oldboy' does not contain 'park chan-wook'"),
        ({"topic": "Park Chan-wook", "kind": "film", "depth": "full"}, "kind 'film' not in ('person',)"),
        ({"topic": "Park Chan-wook", "kind": "person", "depth": "intro"}, "depth 'intro' not in ('sections', 'full')"),
        ({"topic": "Park Chan-wook", "kind": "person", "depth": "full", "year": 1963}, "year not given in the conversation"),
        ({"topic": "Park Chan-wook", "kind": "person", "depth": "full", "language": "en"}, "language not given in the conversation"),
        ({"topic": "Park Chan-wook", "kind": "person", "depth": "full", "page": "Park Chan-wook"}, "page not given in the conversation"),
        ({"topic": "Park Chan-wook", "kind": "person", "depth": "full", "sections": ["Carriera"]}, "sections not given in the conversation"),
        ({"topic": "Park Chan-wook", "kind": "person", "depth": "everything"}, None),
        ({"topic": "", "kind": "person"}, None),
        ("not an object", "arguments is not an object"),
    ],
)
def test_invalid_or_invented_arguments_fail(plan, problem) -> None:
    result = check_any_wikipedia(PARK.expected_wikipedia, plan, "q")

    assert result is not None and (problem is None or result == problem)


def test_a_page_or_section_copied_from_the_conversation_is_accepted() -> None:
    plan = {"topic": "Park Chan-wook", "kind": "person", "depth": "sections", "page": "Park Chan-wook"}

    assert check_any_wikipedia(FOLLOW_UP.expected_wikipedia, plan, "q") is None
    assert check_any_wikipedia(FOLLOW_UP.expected_wikipedia, {**plan, "sections": ["Vita"]}, "q") == "sections not given in the conversation"


def test_the_turn_language_is_ignored_like_the_tool_does() -> None:
    plan = {"topic": "Park Chan-wook", "kind": "person", "depth": "full", "turn_language": "it"}

    assert check_any_wikipedia(PARK.expected_wikipedia, plan, "q") is None


def test_the_planned_arguments_are_validated_against_the_tools_own_schema() -> None:
    schema = WikipediaTool.__dataclass_fields__["input_schema"].default_factory()

    assert {"topic", "kind", "year", "language", "depth", "page", "sections"} <= set(schema["properties"])
