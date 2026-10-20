from __future__ import annotations

import json

from movie_db.harness.evaluation.cases import CASES, EvalCase
from movie_db.harness.evaluation.run_eval import ScriptedParserClient, run_cases
from movie_db.tool.models import MovieDbOperation, MovieDbQuery


def test_offline_evaluation_passes_on_the_fixture_db(movie_db_config) -> None:
    results = run_cases(CASES, config=movie_db_config, client=ScriptedParserClient(CASES))

    failed = [(r.case.question, r.operation, r.titles, r.error) for r in results if not r.passed]
    assert not failed
    assert {case.expected.operation for case in CASES} == {r.case.expected.operation for r in results}


class FixedClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.responses = self

    def create(self, **kwargs):
        return type("Response", (), {"output_text": json.dumps(self.payload)})()


SCI_FI = EvalCase(
    question="i migliori sci-fi",
    expected=MovieDbQuery(operation=MovieDbOperation.top_rated, genre="Sci-Fi"),
    expected_titles=("The Matrix",),
)


def test_genre_ranking_accepts_the_equivalent_operation(movie_db_config) -> None:
    [result] = run_cases((SCI_FI,), config=movie_db_config, client=FixedClient({"operation": "by_genre_year", "genre": "Sci-Fi"}))

    assert result.operation == "by_genre_year"
    assert result.executed == result.expected_executed
    assert result.passed


def test_equivalent_operation_with_different_sql_still_fails(movie_db_config) -> None:
    parsed = {"operation": "by_genre_year", "genre": "Sci-Fi", "year_from": 1990}

    [result] = run_cases((SCI_FI,), config=movie_db_config, client=FixedClient(parsed))

    assert result.executed != result.expected_executed
    assert not result.passed


def test_no_equivalence_with_a_year_range_or_without_genre() -> None:
    with_years = EvalCase("q", MovieDbQuery(operation="by_genre_year", genre="Horror", year_from=1970), ("Alien",))
    no_genre = EvalCase("q", MovieDbQuery(operation="top_rated"), ("The Matrix",))
    most_rated = EvalCase("q", MovieDbQuery(operation="most_rated", genre="Horror"), ("Alien",))

    assert with_years.equivalent_operations() == frozenset()
    assert no_genre.equivalent_operations() == frozenset()
    assert most_rated.equivalent_operations() == frozenset()


def test_other_operations_are_not_accepted(movie_db_config) -> None:
    [result] = run_cases((SCI_FI,), config=movie_db_config, client=FixedClient({"operation": "most_rated", "genre": "Sci-Fi"}))

    assert not result.passed
