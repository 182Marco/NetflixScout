"""FASE 21: which works each `cinema_sql` operation ranges over (the populations), and that the order of what it returns is deterministic. Real file, read only;
skipped when the candidate is absent. The populations asserted here are the CURRENT ones, including the inconsistency documented in docs/cinema_db/PHASE21_POPULATIONS.md
(genre statistics, tags and titles are not limited to films); if the owner decides otherwise, this file changes in the same step as the queries."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tool.cinema_db.config import CinemaDbConfig
from tool.cinema_db.constants import FILM_KINDS, SCREEN_KINDS, SERIES_KINDS
from tool.cinema_db.tool import CinemaSqlTool

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "cinema_db/data/cinema.v4.candidate6.sqlite3"
pytestmark = pytest.mark.skipif(not CANDIDATE.is_file(), reason="needs the schema-4 candidate")

GENRES = ["Action", "Animation", "Comedy", "Documentary", "Drama", "Horror", "Sci-Fi", "War"]


@pytest.fixture(scope="module")
def tool():
    return CinemaSqlTool(config=CinemaDbConfig(enabled=True, db_path=str(CANDIDATE), max_queries_per_turn=40, default_limit=10))


@pytest.fixture(scope="module")
def ro():
    return sqlite3.connect(f"file:{CANDIDATE}?mode=ro&immutable=1", uri=True)


def run(tool, **params):
    body = tool.run(query="x", params=params)["metadata"]["cinema_db"]
    assert body["status"] in ("ok", "empty"), body
    return body


# ----------------------------------------------------------------------------------------------------------------------------- populations
@pytest.mark.parametrize("mode", ["top_rated", "most_rated"])
def test_movielens_rankings_range_over_films_shorts_and_tv_films_only(tool, mode) -> None:
    for genre in [None, *GENRES]:
        for years in [(None, None), (1950, 1969), (1990, 1999), (2010, 2022)]:
            movies = run(tool, operation="movielens", ml_mode=mode, genre=genre, year_from=years[0], year_to=years[1], limit=25)["movies"]
            assert movies and {m["kind"] for m in movies} <= set(FILM_KINDS), (mode, genre, years)
            assert all(m["ratings"] >= 50 for m in movies)                         # the default minimum


def test_the_imdb_ranking_follows_the_requested_type(tool) -> None:
    kinds = {t: {r["kind"] for r in run(tool, operation="ratings", type=t, limit=50)["ranking"]} for t in (None, "film", "series")}
    assert kinds["film"] <= set(FILM_KINDS) and kinds["series"] <= set(SERIES_KINDS) and kinds[None] <= set(SCREEN_KINDS)
    assert kinds["series"] and kinds[None] & set(SERIES_KINDS), "without a type the ranking mixes films and series (documented)"


def test_titles_tags_and_genre_statistics_are_not_limited_to_films_and_say_what_they_return(tool, ro) -> None:
    band = run(tool, operation="movielens", ml_mode="by_title", title="Band of Brothers")["movies"]
    assert any(m["kind"] == "miniseries" for m in band)                              # a title search returns the work and says its kind
    tagged = {r[0] for r in ro.execute("SELECT DISTINCT w.kind FROM work_tag t JOIN work w ON w.work_id = t.work_id")}
    assert {"miniseries", "series", "episode"} & tagged, "tags exist on works that are not films"
    assert all("kind" in m for m in run(tool, operation="movielens", ml_mode="by_tag", tag="world war ii", limit=25)["movies"])   # every item carries its kind
    # approved population (FASE 22): the statistics count the films of the rankings only; the tag search keeps every linked work and takes an optional type
    everything = ro.execute("SELECT count(*) FROM v_ml_genre g JOIN v_ml_movie m ON m.work_id = g.work_id WHERE m.n_ratings >= 50 AND g.genre = 'Drama'").fetchone()[0]
    films_only = ro.execute("SELECT count(*) FROM v_ml_genre g JOIN v_ml_movie m ON m.work_id = g.work_id WHERE m.n_ratings >= 50 AND g.genre = 'Drama' AND m.work_kind IN ('film','short','tv_film')").fetchone()[0]
    stats = {g["genre"]: g for g in run(tool, operation="movielens", ml_mode="genre_stats", limit=50)["genres"]}
    assert stats["Drama"]["films"] == films_only and everything > films_only
    tagged_films = run(tool, operation="movielens", ml_mode="by_tag", tag="world war ii", limit=50, type="film")["movies"]
    assert tagged_films and all(m["kind"] in {"film", "short", "tv_film"} for m in tagged_films)


def test_excluded_movielens_titles_appear_only_in_title_search_with_their_reason(tool) -> None:
    good = run(tool, operation="movielens", ml_mode="by_title", title="Good Boys")["movies"]
    assert any(m.get("status") == "excluded" and m["reason"] == "not_identifiable_via_imdb" and m["work_id"] is None for m in good)
    for mode, extra in (("top_rated", {}), ("most_rated", {}), ("by_tag", {"tag": "funny"}), ("genre_stats", {})):
        body = run(tool, operation="movielens", ml_mode=mode, limit=50, **extra)
        assert all(m.get("status") != "excluded" for m in body.get("movies", [])), mode


# ---------------------------------------------------------------------------------------------------------------------------- determinism
def _stable(body: dict) -> str:
    return json.dumps({k: v for k, v in body.items() if k not in ("timings", "elapsed_ms")}, sort_keys=True, default=str)


CASES = [
    {"operation": "find_work", "title": "Inception", "year": 2010}, {"operation": "find_person", "person": "Christopher Nolan"},
    {"operation": "work_card", "title": "Tenet", "year": 2020}, {"operation": "filmography", "person": "Tom Hanks"},
    {"operation": "cast", "title": "Inception", "year": 2010}, {"operation": "crew", "title": "Inception", "year": 2010},
    {"operation": "collaborations", "person": "Christopher Nolan"}, {"operation": "awards", "title": "Oppenheimer", "year": 2023},
    {"operation": "series", "title": "Breaking Bad"}, {"operation": "companies", "title": "Inception", "year": 2010},
    {"operation": "franchise", "franchise": "Star Wars"}, {"operation": "relations", "title": "The Thing", "year": 1982},
    {"operation": "ratings"}, {"operation": "ratings", "type": "series", "year_from": 2000, "year_to": 2009}, {"operation": "provenance", "imdb_id": "tt1375666"},
    {"operation": "movielens", "ml_mode": "top_rated"}, {"operation": "movielens", "ml_mode": "most_rated", "genre": "Horror"},
    {"operation": "movielens", "ml_mode": "by_title", "title": "Matrix"}, {"operation": "movielens", "ml_mode": "by_tag", "tag": "time travel"},
    {"operation": "movielens", "ml_mode": "genre_stats"},
]


@pytest.mark.parametrize("params", CASES, ids=lambda p: p["operation"] + ":" + str(p.get("ml_mode", "")))
def test_every_operation_returns_the_same_thing_every_time(tool, params) -> None:
    assert len({_stable(run(tool, **params)) for _ in range(3)}) == 1


def test_movielens_orderings_are_total_so_the_cut_is_never_ambiguous(ro) -> None:
    """The three MovieLens orderings end with the film id: no two rows can ever swap places."""
    for table_order in ("m.avg_rating DESC, m.n_ratings DESC, m.movie_id", "m.n_ratings DESC, m.avg_rating DESC, m.movie_id"):
        rows = ro.execute(f"SELECT m.movie_id, m.avg_rating, m.n_ratings FROM v_ml_movie m WHERE m.work_id IS NOT NULL AND m.n_ratings >= 50 ORDER BY {table_order} LIMIT 500").fetchall()
        assert len({r[0] for r in rows}) == len(rows)


def test_the_imdb_ranking_has_no_tie_at_the_cut_for_the_questions_people_ask(ro) -> None:
    """Not a proof (its ORDER BY has no unique last key): the measured fact on the current file, over types x decades x minimum votes x limits. A tie at the cut would make
    the 10th and 11th title interchangeable between runs on another SQLite build."""
    kinds = {"film": FILM_KINDS, "series": SERIES_KINDS, "all": SCREEN_KINDS}
    checked = 0
    for ks in kinds.values():
        marks = ",".join(f"'{k}'" for k in ks)
        for start in range(1920, 2030, 10):
            for votes in (100, 1000, 5000):
                for limit in (10, 25):
                    rows = ro.execute(f"SELECT rating, vote_count FROM v_work_rating WHERE source = 'imdb-datasets' AND vote_count >= ? AND work_kind IN ({marks}) AND work_year BETWEEN ? AND ? "
                                      f"ORDER BY rating DESC, vote_count DESC LIMIT {limit + 1}", (votes, start, start + 9)).fetchall()
                    if len(rows) > limit:
                        checked += 1
                        assert rows[limit - 1] != rows[limit], (ks, start, votes, limit)
    assert checked > 100
