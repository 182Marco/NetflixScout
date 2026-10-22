"""One case per operation family, with the exact calls each one makes."""
from __future__ import annotations

from tmdb_support import (
    GENRES_MOVIE,
    MOVIE_ID,
    calls_shown,
    make_tool,
    movie_payload,
    providers_payload,
    run,
    search_movie_payload,
    tmdb_meta,
)


def _list(n: int, kind_key: str = "title") -> dict:
    return {
        "total_results": n,
        "results": [
            {"id": i, kind_key: f"Item {i}", "release_date": "2020-01-01", "genre_ids": [878], "vote_average": 7, "vote_count": 10}
            for i in range(1, n + 1)
        ],
    }


def _entities(result: dict) -> dict:
    return tmdb_meta(result)["requests"][0]["entities"]


def test_movie_details_with_facets_is_one_call() -> None:
    tool, transport = make_tool({f"/movie/{MOVIE_ID}": movie_payload(**{"watch/providers": providers_payload()})})

    result = run(tool, {"operation": "movie_details", "tmdb_id": MOVIE_ID, "facets": ["credits", "watch_providers", "videos"]})

    assert transport.paths == [f"/movie/{MOVIE_ID}"]
    params = transport.params(f"/movie/{MOVIE_ID}")
    assert params["append_to_response"] == "credits,translations,alternative_titles,release_dates,watch/providers,videos"
    essentials = _entities(result)[f"movie:{MOVIE_ID}"]["essentials"]
    assert essentials["directors"] == ["Christopher Nolan"]
    assert essentials["watch_providers"]["flatrate"] == ["Netflix"]
    assert essentials["top_cast"] == [f"Actor {i}" for i in range(5)]


def test_missing_append_key_triggers_a_counted_provider_fallback() -> None:
    tool, transport = make_tool({f"/movie/{MOVIE_ID}": movie_payload(), f"/movie/{MOVIE_ID}/watch/providers": providers_payload()})

    result = run(tool, {"operation": "movie_details", "tmdb_id": MOVIE_ID, "facets": ["watch_providers"]})

    assert transport.paths == [f"/movie/{MOVIE_ID}", f"/movie/{MOVIE_ID}/watch/providers"]
    assert len(calls_shown(result)) == 2
    assert _entities(result)[f"movie:{MOVIE_ID}"]["essentials"]["watch_providers"]["available"] is True


def test_movie_collection_is_movie_then_collection() -> None:
    collection = {
        "id": 10,
        "name": "Dune Collection",
        "overview": "Saga.",
        "parts": [{"id": 2, "title": "Dune: Part Two", "release_date": "2024-02-27"}, {"id": 1, "title": "Dune", "release_date": "2021-09-15"}],
    }
    tool, transport = make_tool(
        {f"/movie/{MOVIE_ID}": movie_payload(belongs_to_collection={"id": 10, "name": "Dune Collection"}), "/collection/10": collection}
    )

    result = run(tool, {"operation": "movie_collection", "tmdb_id": MOVIE_ID})

    assert transport.paths == [f"/movie/{MOVIE_ID}", "/collection/10"]
    parts = _entities(result)["collection:10"]["facets"]["parts"]
    assert [p["title"] for p in parts] == ["Dune", "Dune: Part Two"]


def test_tv_season_and_episode() -> None:
    season = {"id": 500, "name": "Stagione 1", "season_number": 1, "episodes": [{"episode_number": i, "name": f"Ep {i}"} for i in range(1, 41)]}
    episode = {"id": 600, "name": "Pilot", "season_number": 1, "episode_number": 1, "guest_stars": [{"name": "Guest"}], "crew": []}
    tool, transport = make_tool(
        {"/search/tv": {"results": [{"id": 70523, "name": "Dark", "first_air_date": "2017-12-01"}]}, "/tv/70523/season/1": season, "/tv/70523/season/1/episode/1": episode}
    )

    result = run(
        tool,
        {"operation": "tv_season", "title": "Dark", "season": 1},
        {"operation": "tv_episode", "title": "Dark", "season": 1, "episode": 1},
    )

    assert transport.paths == ["/search/tv", "/tv/70523/season/1", "/tv/70523/season/1/episode/1"]
    season_meta = tmdb_meta(result)["requests"][0]["entities"]["season:500"]
    assert len(season_meta["facets"]["episodes"]) == 30
    assert "r1 season:500 episodes: 30/40" in tmdb_meta(result)["omitted"]
    assert result["chunks"][0]["title"] == "Dark — Stagione 1"


def test_person_with_combined_credits() -> None:
    person = {
        "id": 525,
        "name": "Christopher Nolan",
        "biography": "Regista.",
        "combined_credits": {"cast": [], "crew": [{"title": f"Film {i}", "job": "Director", "popularity": i, "media_type": "movie"} for i in range(25)]},
    }
    tool, transport = make_tool({"/person/525": person})

    result = run(tool, {"operation": "person_details", "tmdb_id": 525, "facets": ["combined_credits"]})

    credits = _entities(result)["person:525"]["facets"]["combined_credits"]
    assert credits[0]["title"] == "Film 24" and len(credits) == 20
    assert transport.params("/person/525")["append_to_response"] == "translations,combined_credits"


def test_collection_facets_are_separate_optional_calls() -> None:
    collection = {"id": 10, "name": "Saga", "overview": "", "parts": []}
    tool, transport = make_tool(
        {
            "/search/collection": {"results": [{"id": 10, "name": "Saga"}]},
            "/collection/10": collection,
            "/collection/10/images": {"posters": [{"file_path": "/p.jpg"}]},
            "/collection/10/translations": {"translations": [{"iso_639_1": "en", "iso_3166_1": "US", "data": {"overview": "English saga."}}]},
        },
        max_calls=3,
    )

    result = run(tool, {"operation": "collection_details", "name": "Saga", "facets": ["images"]}, language="it")

    # search + collection + translations (empty Italian overview) = 3; images skipped for budget.
    assert transport.paths == ["/search/collection", "/collection/10", "/collection/10/translations"]
    request = tmdb_meta(result)["requests"][0]
    assert request["skipped_for_budget"] == ["images"] and request["status"] == "partial"
    essentials = request["entities"]["collection:10"]["essentials"]
    assert essentials["overview"] == "English saga." and essentials["overview_language"] == "en"


def test_company_details() -> None:
    tool, transport = make_tool({"/search/company": {"results": [{"id": 41077, "name": "A24"}]}, "/company/41077": {"id": 41077, "name": "A24", "origin_country": "US"}})

    result = run(tool, {"operation": "company_details", "name": "a24"})

    assert transport.paths == ["/search/company", "/company/41077"]
    assert _entities(result)["company:41077"]["essentials"]["origin_country"] == "US"


def test_discover_resolves_names_and_applies_max_results() -> None:
    tool, transport = make_tool(
        {
            "/genre/movie/list": GENRES_MOVIE,
            "/search/person": {"results": [{"id": 525, "name": "Christopher Nolan", "popularity": 50}]},
            "/watch/providers/movie": {"results": [{"provider_id": 8, "provider_name": "Netflix"}]},
            "/discover/movie": _list(20),
        },
        max_results=3,
    )

    result = run(
        tool,
        {
            "operation": "discover_movies",
            "filters": {
                "genres": ["science fiction"],
                "people": ["Christopher Nolan"],
                "watch_providers": ["netflix"],
                "watch_region": "it",
                "sort": "rating_desc",
                "year_from": 2000,
            },
        },
    )

    params = transport.params("/discover/movie")
    assert params["with_genres"] == "878" and params["with_people"] == "525"
    assert params["with_watch_providers"] == "8" and params["watch_region"] == "IT"
    assert params["sort_by"] == "vote_average.desc" and params["vote_count.gte"] == "200"
    assert params["primary_release_date.gte"] == "2000-01-01" and params["include_adult"] == "false"
    assert len(result["chunks"]) == 3 and result["chunks"][0]["genres"] == "Science Fiction"
    assert tmdb_meta(result)["requests"][0]["total_results"] == 20
    assert result["trace"][0]["data"]["attributions"] == ["justwatch"]


def test_discover_is_not_run_with_unresolved_filters() -> None:
    tool, transport = make_tool({"/genre/movie/list": GENRES_MOVIE})

    result = run(tool, {"operation": "discover_movies", "filters": {"genres": ["Telenovela"]}})

    assert "/discover/movie" not in transport.paths
    assert tmdb_meta(result)["requests"][0]["error"] == "unresolved_filter"


def test_discover_needs_budget_for_every_filter_name() -> None:
    tool, transport = make_tool(
        {"/genre/movie/list": GENRES_MOVIE, "/search/person": {"results": [{"id": 1, "name": "A"}]}, "/discover/movie": _list(2)},
        max_calls=2,
    )

    result = run(tool, {"operation": "discover_movies", "filters": {"genres": ["Drama"], "people": ["A", "B"]}})

    assert "/discover/movie" not in transport.paths and len(transport.calls) == 2
    assert tmdb_meta(result)["requests"][0]["error"] == "call_limit_reached"


def test_trending_and_charts_and_search() -> None:
    trending = {"results": [{"id": 1, "title": "Film", "media_type": "movie"}, {"id": 2, "name": "Serie", "media_type": "tv"}, {"id": 3, "name": "Persona", "media_type": "person", "known_for_department": "Acting"}]}
    tool, transport = make_tool(
        {"/trending/all/week": trending, "/movie/now_playing": _list(8), "/search/movie": search_movie_payload()},
        max_results=5,
    )

    result = run(
        tool,
        {"operation": "trending", "media": "all", "window": "week"},
        {"operation": "chart", "media": "movie", "chart": "now_playing", "region": "IT"},
        {"operation": "search", "kind": "movie", "search_query": "Interstellar", "limit": 2},
    )

    kinds = [chunk["kind"] for chunk in result["chunks"][:3]]
    assert kinds == ["movie", "tv", "person"]
    assert transport.params("/movie/now_playing")["region"] == "IT"
    assert len(result["chunks"]) == 3 + 5 + 2
    assert transport.paths.count("/genre/movie/list") == 1  # genre names fetched once (optional)


def test_reference_operations() -> None:
    tool, _ = make_tool(
        {
            "/genre/tv/list": {"genres": [{"id": 1, "name": "Animazione"}]},
            "/watch/providers/movie": {"results": [{"provider_id": i, "provider_name": f"P{i}", "display_priorities": {"IT": 10 - i}} for i in range(1, 9)]},
            "/certification/movie/list": {"certifications": {"IT": [{"certification": "VM14", "meaning": "Vietato ai minori di 14 anni.", "order": 2}, {"certification": "T", "meaning": "Per tutti.", "order": 1}]}},
        },
        max_results=5,
    )

    result = run(
        tool,
        {"operation": "genres", "media": "tv"},
        {"operation": "watch_providers_catalog", "media": "movie"},
        {"operation": "certifications", "media": "movie"},
    )

    genres, providers, certifications = tmdb_meta(result)["requests"]
    assert genres["reference"] == [{"id": 1, "name": "Animazione"}]
    assert [p["name"] for p in providers["reference"]] == ["P8", "P7", "P6", "P5", "P4"]
    assert providers["reference_total"] == 8
    assert [c["certification"] for c in certifications["reference"]] == ["T", "VM14"]
    assert result["trace"][0]["data"]["attributions"] == ["justwatch"]
