"""Offline helpers for the TMDb tests: a fake transport that counts calls, fake credentials
and small TMDb-shaped payloads. Nothing here reads `.env` or touches the network."""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from tool.tmdb.auth import AuthMode, TmdbCredentials
from tool.tmdb.cache import TtlCache
from tool.tmdb.config import TmdbConfig
from tool.tmdb.tool import TmdbTool

SECRET = "0123456789abcdef0123456789abcdef"
TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.c2lnbmF0dXJlLXNlY3JldA"
BASE = "https://api.themoviedb.org/3"

Route = dict[str, Any] | tuple[int, dict[str, str], Any] | Callable[[dict[str, str]], Any]


class FakeTransport:
    """Routes by path (without `/3`); unknown paths answer 404. Records every call."""

    def __init__(self, routes: dict[str, Route] | None = None) -> None:
        self.routes: dict[str, Route] = dict(routes or {})
        self.calls: list[tuple[str, dict[str, str], dict[str, str], str]] = []

    def __call__(self, url: str, headers: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
        parts = urlsplit(url)
        path = parts.path.removeprefix("/3")
        params = dict(parse_qsl(parts.query))
        self.calls.append((path, params, dict(headers), url))
        route = self.routes.get(path)
        if callable(route):
            route = route(params)
        if route is None:
            return 404, {}, b""
        if isinstance(route, Exception):
            raise route
        if isinstance(route, tuple):
            status, response_headers, body = route
            return status, response_headers, body if isinstance(body, bytes) else json.dumps(body).encode()
        return 200, {}, json.dumps(route).encode()

    @property
    def paths(self) -> list[str]:
        return [call[0] for call in self.calls]

    def params(self, path: str) -> dict[str, str]:
        return next(call[1] for call in self.calls if call[0] == path)


def credentials(mode: AuthMode = AuthMode.query) -> TmdbCredentials:
    return TmdbCredentials(secret=TOKEN if mode is AuthMode.bearer else SECRET, base_url=BASE, mode=mode)


def make_tool(
    routes: dict[str, Route] | None = None,
    *,
    max_results: int = 5,
    max_calls: int = 6,
    cache_ttl: int = 3600,
    mode: AuthMode = AuthMode.query,
    clock: Callable[[], float] | None = None,
) -> tuple[TmdbTool, FakeTransport]:
    config = TmdbConfig(max_results=max_results, max_calls_per_turn=max_calls, cache_ttl=cache_ttl)
    transport = FakeTransport(routes)
    cache = TtlCache(cache_ttl, clock=clock) if clock else None
    tool = TmdbTool(config=config, credentials=credentials(mode), transport=transport, cache=cache)
    return tool, transport


def run(tool: TmdbTool, *requests: dict[str, Any], language: str | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {"requests": list(requests)}
    if language:
        params["turn_language"] = language
    return tool.run(query="domanda", params=params, conversation_history=[])


def tmdb_meta(result: dict[str, Any]) -> dict[str, Any]:
    return result["metadata"]["tmdb"]


def calls_shown(result: dict[str, Any]) -> list[str]:
    """URLs of the calls recorded in the step (each call is `{"method", "url"}`)."""
    return [call["url"] for call in result["trace"][0]["data"]["calls"]] if result["trace"] else []


# --- payloads -------------------------------------------------------------------------

MOVIE_ID = 157336


def search_movie_payload() -> dict[str, Any]:
    return {
        "total_results": 3,
        "results": [
            {"id": 99, "title": "Interstellar Wars", "release_date": "2016-01-01", "popularity": 1},
            {
                "id": MOVIE_ID,
                "title": "Interstellar",
                "original_title": "Interstellar",
                "release_date": "2014-11-05",
                "popularity": 100,
                "genre_ids": [878],
                "vote_average": 8.4,
                "vote_count": 35000,
                "overview": "Esploratori nello spazio.",
            },
            {"id": 98, "title": "Interstellar", "release_date": "1990-01-01", "popularity": 2},
        ],
    }


def movie_payload(**extra: Any) -> dict[str, Any]:
    return {
        "id": MOVIE_ID,
        "title": "Interstellar",
        "original_title": "Interstellar",
        "original_language": "en",
        "release_date": "2014-11-05",
        "imdb_id": "tt0816692",
        "overview": "Un gruppo di esploratori viaggia attraverso un wormhole.",
        "runtime": 169,
        "status": "Released",
        "genres": [{"id": 878, "name": "Fantascienza"}],
        "vote_average": 8.4,
        "vote_count": 35000,
        "production_countries": [{"iso_3166_1": "US"}],
        "credits": {
            "cast": [{"name": f"Actor {i}", "character": f"Role {i}", "order": i} for i in range(30)],
            "crew": [{"name": "Christopher Nolan", "job": "Director"}, {"name": "Hans Zimmer", "job": "Original Music Composer"}],
        },
        "translations": {
            "translations": [
                {"iso_639_1": "en", "iso_3166_1": "US", "data": {"title": "Interstellar", "overview": "English overview."}}
            ]
        },
        **extra,
    }


def providers_payload(region: str = "IT") -> dict[str, Any]:
    return {
        "results": {
            region: {
                "link": "https://www.themoviedb.org/movie/157336/watch",
                "flatrate": [{"provider_name": "Netflix"}],
                "rent": [{"provider_name": "Apple TV"}],
            }
        }
    }


GENRES_MOVIE = {"genres": [{"id": 878, "name": "Science Fiction"}, {"id": 18, "name": "Drama"}, {"id": 27, "name": "Horror"}]}
