"""Offline part of the integrated routing evaluation: the expectation checker for `cinema_sql` calls and the case list (the live run, 2 API calls per case, needs authorisation)."""
from __future__ import annotations

from movie_db.harness.evaluation.routing_cases import CINEMA, INTEGRATED_ROUTING_CASES, CinemaExpectation
from movie_db.harness.evaluation.run_routing_eval import check_cinema


def test_a_correct_movielens_call_passes_and_each_wrong_detail_is_named():
    expected = CinemaExpectation("movielens", "top_rated", genre="Sci-Fi", year_from=1980, year_to=1989)
    good = {"operation": "movielens", "ml_mode": "top_rated", "genre": "sci-fi", "year_from": 1980, "year_to": 1989}
    assert check_cinema(expected, good, "q") is None
    assert "ml_mode" in check_cinema(expected, {**good, "ml_mode": "most_rated"}, "q")
    assert "year_to" in check_cinema(expected, {**good, "year_to": 1999}, "q")
    assert "operation" in check_cinema(expected, {"operation": "ratings", "title": "X"}, "q")
    assert "invalid arguments" in check_cinema(expected, {"operation": "movielens", "ml_mode": "top_rated", "genre": "Mystery-Thriller"}, "q")  # a genre MovieLens does not have
    assert "invalid arguments" in check_cinema(expected, {"operation": "movielens"}, "q")  # no mode


def test_type_and_tag_are_checked_for_ratings_and_by_tag():
    """FASE 23: `absent` = the question names no kind, so no kind may be passed; a string = exactly that kind."""
    mixed = CinemaExpectation("ratings", type="absent")
    assert check_cinema(mixed, {"operation": "ratings"}, "q") is None
    assert "type" in check_cinema(mixed, {"operation": "ratings", "type": "film"}, "q")
    films = CinemaExpectation("ratings", type="film")
    assert check_cinema(films, {"operation": "ratings", "type": "film"}, "q") is None
    assert "type" in check_cinema(films, {"operation": "ratings"}, "q") and "type" in check_cinema(films, {"operation": "ratings", "type": "series"}, "q")
    tagged = CinemaExpectation("movielens", "by_tag", type="series", tag="time travel")
    good = {"operation": "movielens", "ml_mode": "by_tag", "tag": "Time Travel", "type": "series"}
    assert check_cinema(tagged, good, "q") is None
    assert "tag" in check_cinema(tagged, {**good, "tag": "zombies"}, "q")
    kinds = {c.expected_cinema.type for c in INTEGRATED_ROUTING_CASES if c.expected_cinema}
    assert {"absent", "film", "series"} <= kinds


def test_alternatives_are_accepted_and_the_case_list_is_sound():
    expected = CinemaExpectation(("ratings", "movielens"), ("by_title", None))
    assert check_cinema(expected, {"operation": "ratings", "title": "Pulp Fiction"}, "q") is None
    assert check_cinema(expected, {"operation": "movielens", "ml_mode": "by_title", "title": "Pulp Fiction"}, "q") is None
    questions = [c.question for c in INTEGRATED_ROUTING_CASES]
    assert len(questions) == len(set(questions)) and sum(c.expected_tool == CINEMA for c in INTEGRATED_ROUTING_CASES) >= 10
    assert all(c.expected_cinema is not None for c in INTEGRATED_ROUTING_CASES if c.expected_tool == CINEMA)
