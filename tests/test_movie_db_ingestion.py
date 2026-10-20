from __future__ import annotations

import sqlite3

import pytest

from movie_db import schema
from movie_db.harness.fixtures.build_fixture_db import FIXTURE_DIR, build_fixture_db
from movie_db.harness.ingestion.build import build_movie_db
from movie_db.harness.ingestion.load_csv import iter_movies, iter_tags, parse_genres, split_title_year


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Heat (1995)", ("Heat", 1995)),
        ("Matrix, The (1999)", ("The Matrix", 1999)),
        ("Babylon 5 (1994-1998)", ("Babylon 5", 1994)),
        ("Unknown Film", ("Unknown Film", None)),
        ("Mortal Kombat (1995) ", ("Mortal Kombat", 1995)),
    ],
)
def test_split_title_year(raw, expected) -> None:
    assert split_title_year(raw) == expected


def test_no_genres_listed_means_no_genre() -> None:
    assert parse_genres("(no genres listed)") == ()
    assert parse_genres("Action|Sci-Fi") == ("Action", "Sci-Fi")


def test_fixture_csv_quotes_and_utf8() -> None:
    movies = {movie.movie_id: movie for movie in iter_movies(FIXTURE_DIR)}

    assert movies[9].title.startswith("Amélie")
    assert movies[9].year == 2001
    tags = [tag for _, movie_id, tag, _, _ in iter_tags(FIXTURE_DIR) if movie_id == 6]
    assert tags == ["dark, atmospheric"]


def test_build_creates_tables_indexes_and_consistent_stats(movie_db_config) -> None:
    conn = sqlite3.connect(movie_db_config.db_path)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    mismatches = conn.execute(
        "SELECT count(*) FROM movie_stats s JOIN (SELECT movie_id, count(*) n, avg(rating) a "
        "FROM ratings GROUP BY movie_id) r ON r.movie_id = s.movie_id "
        "WHERE r.n != s.n_ratings OR abs(r.a - s.avg_rating) > 0.0001"
    ).fetchone()[0]
    conn.close()

    assert set(schema.TABLES) <= tables
    assert "idx_movie_genres_genre" in indexes
    assert mismatches == 0


def test_existing_db_is_not_overwritten_without_force(tmp_path, movie_db_config) -> None:
    db_path = tmp_path / "movies.sqlite3"
    db_path.write_bytes(b"keep me")

    with pytest.raises(FileExistsError):
        build_fixture_db(db_path, movie_db_config.ingestion)
    assert db_path.read_bytes() == b"keep me"

    build_movie_db(source_dir=FIXTURE_DIR, db_path=db_path, ingestion=movie_db_config.ingestion, force=True)
    assert db_path.read_bytes().startswith(b"SQLite format 3")
    assert not list(tmp_path.glob("*.building"))


def test_missing_csv_files_give_instructions(tmp_path, movie_db_config) -> None:
    with pytest.raises(FileNotFoundError, match="ml-32m.zip"):
        build_movie_db(source_dir=tmp_path, db_path=tmp_path / "x.sqlite3", ingestion=movie_db_config.ingestion)
