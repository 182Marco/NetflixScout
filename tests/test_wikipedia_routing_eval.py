"""Offline part of the Wikipedia routing evaluation: the cases and the argument checks.

Nothing here calls an LLM. What the real planner chooses is measured only by
`python -m movie_db.harness.evaluation.run_routing_eval --live --tool wikipedia_search`, which
costs API credits and has to be authorized separately.
"""
from __future__ import annotations

import json

import pytest

from movie_db.harness.evaluation.routing_cases import ROUTING_CASES, TMDB, WIKIPEDIA, WikipediaExpectation
from movie_db.harness.evaluation.run_routing_eval import check_any_wikipedia, check_wikipedia, main, select_cases
from tool.wikipedia.tool import WikipediaTool

WIKI_CASES = select_cases(WIKIPEDIA)
BY_QUESTION = {case.question: case for case in ROUTING_CASES}
PARK = BY_QUESTION["Raccontami la vita e la carriera di Park Chan-wook"]
FOLLOW_UP = BY_QUESTION["Parlami meglio della sua formazione"]


def _arguments_for(option: WikipediaExpectation, **extra) -> dict:
    return {"topic": option.topic.title(), "kind": option.kinds[0], "depth": option.depths[0], **extra}


def test_there_are_wikipedia_cases_with_a_follow_up_and_a_boundary_with_tmdb() -> None:
    assert len(WIKI_CASES) == 12  # 11 + the plot in English follow-up (2026-10-27)
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
        ({"topic": "Park Chan-wook", "kind": "person", "depth": "full", "language": "it"}, "language 'it' not in (None, 'en')"),
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


def test_english_is_the_default_search_even_for_an_italian_question() -> None:
    for case in (PARK, BY_QUESTION["Com'è nata la Nouvelle Vague e quali sono state le sue influenze?"]):
        options = case.expected_wikipedia if isinstance(case.expected_wikipedia, tuple) else (case.expected_wikipedia,)
        for option in options:
            assert option.languages == (None, "en")
            plan = _arguments_for(option)
            assert check_wikipedia(option, plan, "q") is None
            assert check_wikipedia(option, {**plan, "language": "en"}, "q") is None
            assert check_wikipedia(option, {**plan, "language": "it"}, "q") == "language 'it' not in (None, 'en')"


def test_a_local_topic_may_ask_for_the_italian_edition_and_keywords_are_not_checked_as_given() -> None:
    local = BY_QUESTION["Raccontami la storia del doppiaggio italiano nel cinema degli anni Trenta"]
    plan = {"topic": "Italian dubbing", "kind": "topic", "depth": "full", "keywords": ["dubbing", "1930s"]}

    assert check_any_wikipedia(local.expected_wikipedia, plan, "q") is None
    assert check_any_wikipedia(local.expected_wikipedia, {**plan, "language": "it"}, "q") is None
    assert check_any_wikipedia(local.expected_wikipedia, {**plan, "language": "en"}, "q") is None
    assert check_any_wikipedia(local.expected_wikipedia, {**plan, "topic": "Neorealism"}, "q") is not None


def test_a_page_or_section_copied_from_the_conversation_is_accepted() -> None:
    plan = {"topic": "Park Chan-wook", "kind": "person", "depth": "sections", "page": "Park Chan-wook"}

    assert check_any_wikipedia(FOLLOW_UP.expected_wikipedia, plan, "q") is None
    assert check_any_wikipedia(FOLLOW_UP.expected_wikipedia, {**plan, "sections": ["Vita"]}, "q") == "sections not given in the conversation"


def test_the_turn_language_is_ignored_like_the_tool_does() -> None:
    plan = {"topic": "Park Chan-wook", "kind": "person", "depth": "full", "turn_language": "it"}

    assert check_any_wikipedia(PARK.expected_wikipedia, plan, "q") is None


def test_the_planned_arguments_are_validated_against_the_tools_own_schema() -> None:
    schema = WikipediaTool.__dataclass_fields__["input_schema"].default_factory()

    assert {"topic", "kind", "year", "language", "depth", "page", "sections", "keywords"} <= set(schema["properties"])


REGRESSIONS = {
    "Q1": "Quali cortometraggi compongono Three Extremes (2004) e chi ha diretto ciascun segmento?",
    "Q5": "Chi ha diretto i singoli segmenti di Paris, je t'aime (2006) e quanti sono complessivamente?",
    "Q8": "In The Congress (2013), come si alternano la parte in live action e quella animata, e quale "
          "ruolo ha il personaggio interpretato da Robin Wright?",
}


def test_the_live_regressions_must_start_from_wikipedia_not_from_tmdb() -> None:
    for name, question in REGRESSIONS.items():
        case = BY_QUESTION[question]
        assert case.expected_tool == WIKIPEDIA, name
        option = case.expected_wikipedia
        assert option.kinds == ("film",) and "intro" not in option.depths


def test_a_plan_that_stays_on_the_given_year_passes_and_an_invented_year_fails() -> None:
    case = BY_QUESTION[REGRESSIONS["Q1"]]
    plan = {"topic": "Three Extremes", "kind": "film", "depth": "full", "year": 2004, "keywords": ["Fruit Chan"]}

    assert check_any_wikipedia(case.expected_wikipedia, plan, "q") is None
    assert check_any_wikipedia(case.expected_wikipedia, {**plan, "year": 2005}, "q") == "year not given in the conversation"


def test_simple_structured_questions_about_the_same_films_are_tmdb_controls() -> None:
    for question in ("Quanto dura Paris, je t'aime?", "Chi recita in The Congress?", "Chi ha diretto Solaris, quello del 1972?"):
        assert BY_QUESTION[question].expected_tool == TMDB and BY_QUESTION[question].expected_request is not None


# --- plans that must use both tools, and the trilogy that is not a TMDb collection ----------------------------

BUSTER = "Quali episodi compongono The Ballad of Buster Scruggs (2018) e quali attori interpretano i protagonisti di ciascun episodio?"
TRILOGY = "Quali film compongono la trilogia della vendetta di Park Chan-wook e in quale ordine sono usciti?"


class _Tool:
    description, input_schema = "fake", {}

    def __init__(self, name: str) -> None:
        self.name = name

    def run(self, **kwargs):
        raise AssertionError("routing eval must not run tools")


class _Planner:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs, self.responses = outputs, self

    def create(self, **kwargs):
        return type("Response", (), {"output_text": self.outputs.pop(0)})()


def _run(case, plan: dict):
    from movie_db.harness.evaluation.routing_cases import DB, RAG, YOUTUBE
    from movie_db.harness.evaluation.run_routing_eval import RecordingClient, run_routing_cases
    from orchestrator import LLMOrchestrator

    tools = [RAG, DB, TMDB, YOUTUBE, WIKIPEDIA]
    orch = LLMOrchestrator(
        config={"orchestrator": {"fallback_tool": RAG, "tool_confidence_threshold": 0.6, "allowed_tools": tools}},
        tools=[_Tool(name) for name in tools],
        client=RecordingClient(_Planner([json.dumps({"standalone_query": case.question, "confidence": 0.9, **plan})])),
    )
    (result,) = run_routing_cases(
        (case,), orchestrator=orch, classify=lambda q, h: {"is_cinema": True, "language": "it"}, context_size=0
    )
    return result


def _wiki_args(**fields):
    return {"topic": "The Ballad of Buster Scruggs", "kind": "film", "year": 2018, "depth": "sections", **fields}


def test_the_cast_by_episode_case_needs_both_tools_in_the_plan() -> None:
    case = BY_QUESTION[BUSTER]
    both_wiki_first = _run(case, {"tool_name": WIKIPEDIA, "arguments": _wiki_args(),
                                  "parts": [{"part": "episodi", "tool": WIKIPEDIA}, {"part": "attori", "tool": TMDB}]})
    both_tmdb_first = _run(case, {"tool_name": TMDB, "arguments": {"requests": [{"operation": "movie_details", "title": "x"}]},
                                  "parts": [{"part": "attori", "tool": TMDB}, {"part": "episodi", "tool": WIKIPEDIA}]})
    wikipedia_only = _run(case, {"tool_name": WIKIPEDIA, "arguments": _wiki_args(), "parts": [{"part": "episodi", "tool": WIKIPEDIA}]})
    tmdb_only = _run(case, {"tool_name": TMDB, "arguments": {"requests": [{"operation": "movie_details", "title": "x"}]}})

    assert both_wiki_first.passed and both_tmdb_first.passed
    assert not wikipedia_only.passed and wikipedia_only.uses_problem == "plan does not use ['tmdb_search']"
    assert not tmdb_only.passed and tmdb_only.uses_problem == "plan does not use ['wikipedia_search']"


def test_the_cast_by_episode_case_accepts_tmdb_as_the_first_step_only_when_wikipedia_follows() -> None:
    case = BY_QUESTION[BUSTER]

    assert case.alternative_first_tools == (TMDB,) and case.also_uses == (WIKIPEDIA, TMDB)
    assert _run(case, {"tool_name": "rag_search", "arguments": {}}).passed is False


def test_the_trilogy_case_starts_from_wikipedia_and_a_tmdb_collection_search_fails_it() -> None:
    case = BY_QUESTION[TRILOGY]
    right = _run(case, {"tool_name": WIKIPEDIA, "arguments": {"topic": "Vengeance Trilogy", "kind": "topic", "depth": "intro"}})
    local = _run(case, {"tool_name": WIKIPEDIA, "arguments": {"topic": "trilogia della vendetta", "kind": "topic", "depth": "full"}})
    wrong = _run(case, {"tool_name": TMDB, "arguments": {"requests": [{"operation": "collection_details", "name": "Vengeance Trilogy"}]}})

    assert right.passed and local.passed and not wrong.passed
