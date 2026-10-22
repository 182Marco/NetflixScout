"""Every invalid input fails before any HTTP call, with errors that never echo values."""
from __future__ import annotations

import pytest
from tmdb_support import SECRET, make_tool, tmdb_meta

from tmdb.models.requests import MAX_REQUESTS_PER_RUN

SENTINEL = "zz-user-value-zz"

INVALID = {
    # missing required parameters
    "missing target": {"operation": "movie_details"},
    "missing season": {"operation": "tv_season", "title": "Dark"},
    "missing episode": {"operation": "tv_episode", "title": "Dark", "season": 1},
    "missing search text": {"operation": "search", "kind": "movie"},
    "missing media": {"operation": "trending", "window": "day"},
    "missing external source": {"operation": "find_by_external_id", "external_id": "tt0816692"},
    # parameters incompatible with the operation
    "season on a movie": {"operation": "movie_details", "title": "Dune", "season": 1},
    "title on a person": {"operation": "person_details", "title": SENTINEL},
    "filters on details": {"operation": "movie_details", "title": "Dune", "filters": {"genres": ["Drama"]}},
    "region on tv chart": {"operation": "chart", "media": "tv", "chart": "popular", "region": "IT"},
    "year on person search": {"operation": "search", "kind": "person", "search_query": "Nolan", "year": 2010},
    "chart not for media": {"operation": "chart", "media": "tv", "chart": "now_playing"},
    "media not allowed": {"operation": "genres", "media": "person"},
    # facets not supported by the resource
    "tv facet on movie": {"operation": "movie_details", "title": "Dune", "facets": ["aggregate_credits"]},
    "movie facet on person": {"operation": "person_details", "name": "Nolan", "facets": ["reviews"]},
    "facets on company": {"operation": "company_details", "name": "A24", "facets": ["images"]},
    "unknown facet": {"operation": "movie_details", "title": "Dune", "facets": [SENTINEL]},
    # invalid IDs, pages, years, seasons, episodes
    "id zero": {"operation": "movie_details", "tmdb_id": 0},
    "id too big": {"operation": "movie_details", "tmdb_id": 2**31},
    "id as text": {"operation": "movie_details", "tmdb_id": SENTINEL},
    "page": {"operation": "chart", "media": "movie", "chart": "popular", "page": 2},
    "year too old": {"operation": "movie_details", "title": "Dune", "year": 1500},
    "negative season": {"operation": "tv_season", "title": "Dark", "season": -1},
    "episode zero": {"operation": "tv_episode", "title": "Dark", "season": 1, "episode": 0},
    "bad imdb id": {"operation": "movie_details", "external_id": SENTINEL, "external_source": "imdb"},
    "person imdb on movie": {"operation": "movie_details", "external_id": "nm0634240", "external_source": "imdb"},
    "bad region": {"operation": "movie_details", "title": "Dune", "region": "ITA"},
    "limit too big": {"operation": "trending", "media": "movie", "window": "day", "limit": 50},
    # discover filters incompatible or malformed
    "people on tv": {"operation": "discover_tv", "filters": {"people": ["Nolan"]}},
    "tv status on movies": {"operation": "discover_movies", "filters": {"tv_status": "ended"}},
    "revenue sort on tv": {"operation": "discover_tv", "filters": {"sort": "revenue_desc"}},
    "inverted years": {"operation": "discover_movies", "filters": {"year_from": 2000, "year_to": 1990}},
    "inverted ratings": {"operation": "discover_movies", "filters": {"min_rating": 8, "max_rating": 5}},
    "certification alone": {"operation": "discover_movies", "filters": {"certification": "VM14"}},
    "providers without region": {"operation": "discover_movies", "filters": {"watch_providers": ["Netflix"]}},
    "monetization alone": {"operation": "discover_movies", "filters": {"monetization": ["flatrate"]}},
    "release types without region": {"operation": "discover_movies", "filters": {"release_types": ["theatrical"]}},
    "bad language": {"operation": "discover_movies", "filters": {"original_language": "ita"}},
    "too many genres": {"operation": "discover_movies", "filters": {"genres": ["a", "b", "c", "d", "e", "f"]}},
    "extra filter": {"operation": "discover_movies", "filters": {SENTINEL: 1}},
    # unknown operations and enum values
    "unknown operation": {"operation": SENTINEL},
    "unknown kind": {"operation": "search", "kind": "podcast", "search_query": "x"},
    "unknown window": {"operation": "trending", "media": "movie", "window": "month"},
    "unknown sort": {"operation": "discover_movies", "filters": {"sort": "random"}},
    # extra fields
    "extra field": {"operation": "movie_details", "title": "Dune", SENTINEL: 1},
    "url field": {"operation": "movie_details", "title": "Dune", "url": "https://evil.example.com"},
    "call limit field": {"operation": "movie_details", "title": "Dune", "max_calls_per_turn": 99},
}


@pytest.mark.parametrize("request_payload", INVALID.values(), ids=INVALID.keys())
def test_invalid_input_fails_without_http_and_without_echoing_values(request_payload) -> None:
    tool, transport = make_tool({})

    result = tool.run(query="q", params={"requests": [request_payload]}, conversation_history=[])

    meta = tmdb_meta(result)
    assert transport.calls == []
    assert result["trace"] == [] and result["chunks"] == []
    assert meta["status"] == "error" and meta["error"] == "invalid_request"
    assert meta["errors"] and all(error["request"] == 1 for error in meta["errors"] if "request" in error)
    assert SENTINEL not in repr(result) and SECRET not in repr(result)


def test_one_invalid_request_rejects_the_whole_run() -> None:
    tool, transport = make_tool({})
    good = {"operation": "trending", "media": "movie", "window": "day"}

    result = tool.run(query="q", params={"requests": [good, {"operation": "movie_details"}]}, conversation_history=[])

    assert transport.calls == []
    assert tmdb_meta(result)["errors"][0]["request"] == 2


def test_request_count_is_an_input_limit() -> None:
    tool, transport = make_tool({})
    trending = {"operation": "trending", "media": "movie", "window": "day"}

    result = tool.run(query="q", params={"requests": [trending] * (MAX_REQUESTS_PER_RUN + 1)}, conversation_history=[])
    empty = tool.run(query="q", params={"requests": []}, conversation_history=[])

    assert transport.calls == []
    assert tmdb_meta(result)["error"] == tmdb_meta(empty)["error"] == "invalid_request"


def test_missing_operation_and_extra_top_level_keys_are_rejected() -> None:
    tool, transport = make_tool({})

    for params in ({}, {"requests": [{}]}, {"operation": "trending", "media": "movie", "window": "day", "requests": []}):
        assert tmdb_meta(tool.run(query="q", params=params))["error"] == "invalid_request"
    assert transport.calls == []


def test_value_error_details_name_fields_not_values() -> None:
    tool, _ = make_tool({})

    result = tool.run(
        query="q",
        params={"operation": "movie_details", "title": "Dune", "season": 1},
        conversation_history=[],
    )

    [error] = tmdb_meta(result)["errors"]
    assert error["error"] == "value_error"
    assert error["detail"] == "field 'season' is not allowed for operation 'movie_details'."


def test_valid_inputs_are_normalized() -> None:
    from tmdb.models.requests import TmdbToolInput

    payload = TmdbToolInput.model_validate(
        {
            "query": "q",
            "operation": "movie_details",
            "title": "  Blade   Runner ",
            "region": "it",
            "facets": ["credits", "credits", "videos"],
        }
    )

    [request] = payload.requests
    assert (request.title, request.region, [f.value for f in request.facets]) == ("Blade Runner", "IT", ["credits", "videos"])
