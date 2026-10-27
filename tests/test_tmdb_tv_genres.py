"""Series have their own genre list: names that mean the same are aliased, names that do not exist for
series make the planner look elsewhere instead of the turn ending (live check of 2026-10-27: "Thriller")."""
from __future__ import annotations

from tmdb_support import GENRES_MOVIE, make_tool, run, tmdb_meta

from turn import RESULT_FOLLOW_UP

# The real list of TMDb for series (`GET /genre/tv/list`, checked live on 2026-10-27): no Thriller.
GENRES_TV = {
    "genres": [
        {"id": 10759, "name": "Action & Adventure"},
        {"id": 80, "name": "Crime"},
        {"id": 18, "name": "Drama"},
        {"id": 9648, "name": "Mystery"},
        {"id": 10765, "name": "Sci-Fi & Fantasy"},
        {"id": 10768, "name": "War & Politics"},
    ]
}
DISCOVER_TV = {"total_results": 1, "results": [{"id": 7, "name": "Una serie", "first_air_date": "2020-01-01", "genre_ids": [9648]}]}


def _discover_tv(genre: str):
    tool, transport = make_tool({"/genre/tv/list": GENRES_TV, "/discover/tv": DISCOVER_TV})
    result = run(tool, {"operation": "discover_tv", "filters": {"genres": [genre]}})
    return result, transport


def test_thriller_means_mystery_for_series() -> None:
    result, transport = _discover_tv("Thriller")

    assert transport.params("/discover/tv")["with_genres"] == "9648"
    assert result["outcome"]["status"] == "ok" and RESULT_FOLLOW_UP not in result


def test_science_fiction_means_sci_fi_and_fantasy_for_series() -> None:
    _, transport = _discover_tv("science fiction")

    assert transport.params("/discover/tv")["with_genres"] == "10765"


def test_names_that_already_match_are_unchanged() -> None:
    for name, expected in (("Mystery", "9648"), ("action", "10759"), ("War", "10768")):
        _, transport = _discover_tv(name)
        assert transport.params("/discover/tv")["with_genres"] == expected, name


def test_films_do_not_use_the_series_aliases() -> None:
    tool, transport = make_tool({"/genre/movie/list": GENRES_MOVIE, "/discover/movie": DISCOVER_TV})

    result = run(tool, {"operation": "discover_movies", "filters": {"genres": ["Thriller"]}})

    assert "/discover/movie" not in transport.paths
    assert tmdb_meta(result)["requests"][0]["error"] == "unresolved_filter"


def test_a_series_genre_without_an_equivalent_offers_the_planner_another_step() -> None:
    result, transport = _discover_tv("Horror")

    assert "/discover/tv" not in transport.paths
    assert result["outcome"] == {"status": "error", "reason": "unresolved_filter"}
    follow_up = result[RESULT_FOLLOW_UP]
    assert follow_up["available"] is True and follow_up["reasons"] == ["unresolved_filter"]
    assert "operazione genres" in follow_up["summary"] and "(unresolved_filter)" in follow_up["summary"]
