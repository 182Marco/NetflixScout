from __future__ import annotations

import pytest

import app as app_module
import data_coverage
from movie_db.harness.evaluation.routing_cases import ROUTING_CASES
from orchestrator import LLMOrchestrator

COVERAGE = app_module.CONFIG["orchestrator"]["data_coverage"]


def test_rule_names_each_source_and_the_alternative() -> None:
    rule = data_coverage.coverage_rule(COVERAGE)
    assert "rag_search: film fino al 2012" in rule
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
    assert "rag_search: film fino al 2012" in text
    assert "movie_db_search" not in text


def test_every_post_coverage_routing_case_expects_tmdb_and_controls_stay_local() -> None:
    by_question = {c.question: c for c in ROUTING_CASES}
    for question in (
        "Quali sono i film più votati usciti nel 2024?",
        "Consigliami un film horror uscito nel 2020 con atmosfera claustrofobica",
        "Qual è il film con il voto medio più alto del 2023?",
        "Dammi 3 film di fantascienza cupi usciti dopo il 2018",
        "Quali sono le migliori commedie degli ultimi due anni?",
    ):
        assert by_question[question].expected_tool == "tmdb_search"
    for control in ("Qual è il film con il voto medio più alto del 2005?", "Quali sono i film più votati usciti nel 2021?"):
        assert by_question[control].expected_tool == "movie_db_search"
    assert by_question["Consigliami un film del 2008 su un robot che si innamora di un umano"].expected_tool == "rag_search"


# The configured years must match the datasets (skipped where the data is not installed).
@pytest.mark.skipif(not (data_coverage.CMU_DIR / "plot_summaries.txt").exists(), reason="CMU dataset missing")
def test_rag_years_match_the_cmu_corpus() -> None:
    cmu = data_coverage.measure_cmu()
    last = COVERAGE["rag_search"]["last_complete_year"]
    per_year = cmu["films_per_year"]
    assert per_year[last] > 500  # the configured year is a full year
    after = sum(n for y, n in per_year.items() if y > last)
    assert after < 0.01 * sum(per_year.values())  # beyond it only a handful of titles
    assert cmu["latest_release"] <= "2014-12-31"


@pytest.mark.skipif(not data_coverage.MOVIELENS_DB.exists(), reason="MovieLens DB missing")
def test_db_years_match_movielens() -> None:
    ml = data_coverage.measure_movielens()
    last = COVERAGE["movie_db_search"]["last_complete_year"]
    per_year = ml["films_per_year"]
    assert ml["max_year"] == last + 1
    assert per_year[ml["max_year"]] < 0.6 * per_year[last]  # the last year is partial
    assert ml["last_rating"].startswith("2023-10")
