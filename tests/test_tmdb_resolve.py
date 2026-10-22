from __future__ import annotations

from tmdb_support import MOVIE_ID, make_tool, movie_payload, run, search_movie_payload, tmdb_meta

PERSON_SEARCH = {
    "results": [
        {"id": 1, "name": "Chris Evans", "known_for_department": "Acting", "popularity": 90},
        {"id": 2, "name": "Chris Evans", "known_for_department": "Directing", "popularity": 5},
    ]
}


def _person(person_id: int) -> dict:
    return {"id": person_id, "name": "Chris Evans", "known_for_department": "Directing", "biography": "Bio."}


def test_tmdb_id_needs_no_resolution_call() -> None:
    tool, transport = make_tool({f"/movie/{MOVIE_ID}": movie_payload()})

    run(tool, {"operation": "movie_details", "tmdb_id": MOVIE_ID})

    assert transport.paths == [f"/movie/{MOVIE_ID}"]


def test_external_id_is_resolved_with_find() -> None:
    tool, transport = make_tool(
        {"/find/tt0816692": {"movie_results": [{"id": MOVIE_ID, "title": "Interstellar"}]}, f"/movie/{MOVIE_ID}": movie_payload()}
    )

    result = run(tool, {"operation": "movie_details", "external_id": "tt0816692", "external_source": "imdb"})

    assert transport.paths == ["/find/tt0816692", f"/movie/{MOVIE_ID}"]
    assert transport.params("/find/tt0816692")["external_source"] == "imdb_id"
    assert result["chunks"][0]["tmdb_id"] == MOVIE_ID


def test_exact_title_and_year_win_and_ambiguity_is_reported() -> None:
    tool, transport = make_tool({"/search/movie": search_movie_payload(), f"/movie/{MOVIE_ID}": movie_payload()})

    result = run(tool, {"operation": "movie_details", "title": "interstellar", "year": 2014})

    request = tmdb_meta(result)["requests"][0]
    assert transport.params("/search/movie")["year"] == "2014"
    assert result["chunks"][0]["tmdb_id"] == MOVIE_ID
    # Two exact matches ("Interstellar" 2014 and 1990): the other one is a candidate.
    assert request["candidates"] == [{"tmdb_id": 98, "title": "Interstellar", "year": 1990}]


def test_year_off_by_one_falls_back_to_a_counted_search_without_year() -> None:
    def search(params):
        return {"results": []} if "year" in params else search_movie_payload()

    tool, transport = make_tool({"/search/movie": search, f"/movie/{MOVIE_ID}": movie_payload()})

    result = run(tool, {"operation": "movie_details", "title": "Interstellar", "year": 2015})

    assert transport.paths == ["/search/movie", "/search/movie", f"/movie/{MOVIE_ID}"]
    assert len(result["trace"][0]["data"]["calls"]) == 3
    assert result["chunks"][0]["tmdb_id"] == MOVIE_ID  # 2014 is within ±1 of 2015


def test_person_is_picked_by_department() -> None:
    tool, _ = make_tool({"/search/person": PERSON_SEARCH, "/person/1": _person(1), "/person/2": _person(2)})

    directing = run(tool, {"operation": "person_details", "name": "Chris Evans", "department": "directing"})
    default = run(tool, {"operation": "person_details", "name": "Chris Evans"})

    assert directing["chunks"][0]["tmdb_id"] == 2
    assert default["chunks"][0]["tmdb_id"] == 1


def test_same_title_in_one_turn_is_searched_once() -> None:
    tool, transport = make_tool(
        {"/search/movie": search_movie_payload(), f"/movie/{MOVIE_ID}": movie_payload(belongs_to_collection=None)},
        cache_ttl=0,
    )

    run(
        tool,
        {"operation": "movie_details", "title": "Interstellar", "facets": ["videos"]},
        {"operation": "movie_collection", "title": "  INTERSTELLAR "},
    )

    assert transport.paths.count("/search/movie") == 1


def test_no_match_is_a_request_error_not_a_crash() -> None:
    tool, transport = make_tool({"/search/movie": {"results": []}})

    result = run(tool, {"operation": "movie_details", "title": "Nessun film"})

    assert tmdb_meta(result)["requests"][0]["error"] == "not_found"
    assert transport.paths == ["/search/movie"]
