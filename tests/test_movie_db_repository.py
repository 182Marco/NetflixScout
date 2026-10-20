from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from movie_db.tool.models import MovieDbOperation, MovieDbQuery
from movie_db.tool.sql.connection import readonly_connection
from movie_db.tool.sql.queries import QUERY_BUILDERS, build_query, escape_like
from movie_db.tool.sql.repository import effective_limit, run_query


def _run(config, **fields):
    with readonly_connection(config.db_path, timeout_ms=config.query.timeout_ms) as conn:
        return run_query(conn, MovieDbQuery(**fields), config.query)


def _titles(rows) -> list[str]:
    return [row["title"] for row in rows]


def test_every_operation_has_a_query_builder() -> None:
    assert set(QUERY_BUILDERS) == set(MovieDbOperation)


def test_top_rated_with_genre_respects_min_ratings(movie_db_config) -> None:
    executed, rows = _run(movie_db_config, operation="top_rated", genre="horror")

    # The Shining has a 5.0 average but a single rating: below min_ratings=2.
    assert _titles(rows) == ["Alien", "Scream"]
    assert executed[0].params[0] == movie_db_config.query.min_ratings
    assert "Horror" in executed[0].params


def test_most_rated_and_limit(movie_db_config) -> None:
    _, rows = _run(movie_db_config, operation="most_rated", limit=2)

    assert _titles(rows) == ["Toy Story", "The Matrix"]


def test_limit_is_clamped_to_max_limit(movie_db_config) -> None:
    query = MovieDbQuery(operation="most_rated", limit=10_000)

    assert effective_limit(query, movie_db_config.query) == movie_db_config.query.max_limit
    executed, _ = _run(movie_db_config, operation="most_rated", limit=10_000)
    assert executed[0].params[-1] == movie_db_config.query.max_limit


def test_by_title_matches_clean_title_and_year_filter(movie_db_config) -> None:
    _, rows = _run(movie_db_config, operation="by_title", title="matrix", year_from=1999)

    assert _titles(rows) == ["The Matrix"]
    assert rows[0]["imdb_id"] == "0133093"


def test_by_tag_is_case_insensitive(movie_db_config) -> None:
    _, rows = _run(movie_db_config, operation="by_tag", tag="  TIME   travel ")

    assert _titles(rows) == ["Back to the Future"]
    assert rows[0]["tag_count"] == 2


def test_stats_by_genre(movie_db_config) -> None:
    _, rows = _run(movie_db_config, operation="stats_by_genre", genre="Sci-Fi")

    assert rows == [{"genre": "Sci-Fi", "n_movies": 4, "avg_rating": pytest.approx(4.302, abs=0.001), "n_ratings": 13}]


@pytest.mark.parametrize(
    "payload",
    [
        "x'); DROP TABLE movies;--",
        "' OR 1=1 --",
        "%",
        "_",
        "Matrix\" UNION SELECT * FROM ratings --",
    ],
)
def test_sql_injection_is_a_literal_and_db_is_unchanged(movie_db_config, payload) -> None:
    before = hashlib.sha256(Path(movie_db_config.db_path).read_bytes()).hexdigest()

    executed, rows = _run(movie_db_config, operation="by_title", title=payload)

    assert rows == []
    # Same SQL text as a harmless title: the payload only travels as a bind parameter.
    assert executed[0].sql == build_query(MovieDbQuery(operation="by_title", title="safe"), limit=1, min_ratings=0).sql
    assert hashlib.sha256(Path(movie_db_config.db_path).read_bytes()).hexdigest() == before


def test_no_request_value_enters_the_sql_text() -> None:
    query = MovieDbQuery(operation="by_tag", tag="robots", genre="Sci-Fi", year_from=1980, year_to=1989)

    executed = build_query(query, limit=5, min_ratings=10)

    assert "robots" not in executed.sql
    assert "1980" not in executed.sql
    assert executed.params == ["robots", "Sci-Fi", 1980, 1989, 5]


def test_escape_like() -> None:
    assert escape_like("100%_a\\b") == "100\\%\\_a\\\\b"
