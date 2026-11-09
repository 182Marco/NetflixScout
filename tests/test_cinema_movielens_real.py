"""`cinema_sql` `movielens` on the REAL schema-4 file against the ORIGINAL MovieLens database (offline, read-only; skipped when either file is absent).

The two guarantees that matter: the per-genre statistics equal the original computed over the same films (so every difference from the old tool is the documented
exclusion of films that are not catalogue works, nothing else), and the tag lists carry the same distinct-user counts."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tool.cinema_db.config import CinemaDbConfig
from tool.cinema_db.tool import CinemaSqlTool

ROOT = Path(__file__).resolve().parents[1]
V4 = ROOT / "cinema_db/data/cinema.v4.candidate6.sqlite3"
ML = ROOT / "movie_db/data/movielens32m.sqlite3"
pytestmark = pytest.mark.skipif(not (V4.is_file() and ML.is_file()), reason="needs the schema-4 candidate and the MovieLens database")


def _ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)


@pytest.fixture(scope="module")
def world():
    new, ml = _ro(V4), _ro(ML)
    ml.execute("CREATE TEMP TABLE mapped(movie_id INTEGER PRIMARY KEY)")
    ml.executemany("INSERT INTO mapped VALUES (?)", new.execute("SELECT movie_id FROM ml_movie WHERE work_id IS NOT NULL").fetchall())
    tool = CinemaSqlTool(config=CinemaDbConfig(enabled=True, db_path=str(V4), max_queries_per_turn=40, default_limit=10))
    return tool, ml


def _run(tool, **arguments):
    return tool.run(query="q", params={"operation": "movielens", **arguments})["metadata"]["cinema_db"]


@pytest.mark.parametrize("years", [(None, None), (1990, 1999), (1950, 1969)])
def test_genre_statistics_equal_the_original_over_the_same_films(world, years):
    """FASE 22: the statistics range over the films of the rankings (film, short, TV film), not over every linked work."""
    tool, ml = world
    ml.execute("CREATE TEMP TABLE IF NOT EXISTS film_mapped(movie_id INTEGER PRIMARY KEY)")
    if not ml.execute("SELECT 1 FROM film_mapped LIMIT 1").fetchone():
        new = _ro(V4)
        ml.executemany("INSERT INTO film_mapped VALUES (?)", new.execute("SELECT m.movie_id FROM ml_movie m JOIN work w ON w.work_id = m.work_id WHERE w.kind IN ('film','short','tv_film')").fetchall())
    yf, yt = years
    where = "s.n_ratings >= 50" + (f" AND m.year >= {yf} AND m.year <= {yt}" if yf else "")
    original = {g: (n, a, r) for g, n, a, r in ml.execute(
        f"SELECT g.genre, count(*), round(avg(s.avg_rating), 3), sum(s.n_ratings) FROM movie_genres g JOIN movie_stats s USING(movie_id) JOIN movies m USING(movie_id) "
        f"JOIN film_mapped USING(movie_id) WHERE {where} GROUP BY g.genre")}
    body = _run(tool, ml_mode="genre_stats", limit=50, **({"year_from": yf, "year_to": yt} if yf else {}))
    assert {g["genre"]: (g["films"], g["avg_rating"], g["ratings"]) for g in body["genres"]} == original


def test_tag_lists_carry_the_original_distinct_user_counts(world):
    tool, ml = world
    body = _run(tool, ml_mode="by_tag", tag="  Time   Travel ", limit=10)
    assert body["status"] == "ok" and all(m["tag_users"] >= 1 for m in body["movies"])
    imdb = {m["imdb_id"]: m["tag_users"] for m in body["movies"]}
    for imdb_id, users in imdb.items():
        row = ml.execute("SELECT count(DISTINCT t.user_id) FROM tags t JOIN links l USING(movie_id) WHERE t.tag_norm = 'time travel' AND ltrim(l.imdb_id, '0') = ?", (imdb_id.removeprefix("tt").lstrip("0"),)).fetchone()
        assert row[0] == users


def test_a_ranking_never_lists_a_series_an_episode_or_an_excluded_film(world):
    tool, _ = world
    for mode in ("top_rated", "most_rated"):
        body = _run(tool, ml_mode=mode, limit=50)
        assert len(body["movies"]) == 50 and {m["kind"] for m in body["movies"]} <= {"film", "short", "tv_film"} and all("status" not in m for m in body["movies"])
