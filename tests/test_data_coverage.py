from __future__ import annotations

import pytest

import app as app_module
import data_coverage
from movie_db.harness.evaluation.routing_cases import ROUTING_CASES
from orchestrator import LLMOrchestrator

COVERAGE = app_module.CONFIG["orchestrator"]["data_coverage"]


def test_rule_names_each_source_and_the_alternative() -> None:
    rule = data_coverage.coverage_rule(COVERAGE)
    assert "rag_search" not in rule      # the film index has no cut-off year: titles, people and years are served by it
    assert "movie_db_search: film fino al 2022" in rule
    assert "scegli tmdb_search" in rule
    assert "prevale sulle regole 2 e 3" in rule


def test_rule_is_empty_without_coverage() -> None:
    assert data_coverage.coverage_rule({}) == ""


def test_planner_instructions_carry_the_rule_only_for_allowed_tools() -> None:
    orch = LLMOrchestrator.__new__(LLMOrchestrator)
    orch.orchestrator_config = {"instructions": "BASE", "data_coverage": COVERAGE}
    orch._catalog_text = lambda allowed: ""
    text = orch._planning_instructions(["rag_search", "tmdb_search"], "")
    assert text.startswith("BASE")
    assert "rag_search: film fino" not in text
    assert "movie_db_search" not in text


def test_every_post_coverage_routing_case_expects_tmdb_and_controls_stay_local() -> None:
    by_question = {c.question: c for c in ROUTING_CASES}
    for question in (
        "Quali sono i film più votati usciti nel 2024?",
        "Qual è il film con il voto medio più alto del 2023?",
        "Quali sono le migliori commedie degli ultimi due anni?",
    ):
        assert by_question[question].expected_tool == "tmdb_search"
    # A recommendation by theme with a year is the film index's job; TMDb discover stays accepted as the first tool.
    for question in ("Consigliami un film horror uscito nel 2020 con atmosfera claustrofobica", "Dammi 3 film di fantascienza cupi usciti dopo il 2018"):
        assert by_question[question].expected_tool == "rag_search" and "tmdb_search" in by_question[question].alternative_first_tools
    for control in ("Qual è il film con il voto medio più alto del 2005?", "Quali sono i film più votati usciti nel 2021?"):
        assert by_question[control].expected_tool == "movie_db_search"
    assert by_question["Consigliami un film del 2008 su un robot che si innamora di un umano"].expected_tool == "rag_search"


def test_the_film_index_has_no_cut_off_year_in_the_planner_rule() -> None:
    assert "rag_search" not in COVERAGE and set(COVERAGE) == {"movie_db_search"}
