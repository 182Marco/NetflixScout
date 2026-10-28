"""Offline helpers for the OMDb tests: a fake transport that records calls, fake credentials and
OMDb-shaped answers. Nothing here reads `.env` or touches the network. Titles and numbers are
invented fixtures, not real OMDb data."""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from tool.omdb.auth import OmdbCredentials
from tool.omdb.http import HttpSession

SECRET = "omdbFAKEkey0123"
HOST = "www.omdbapi.com"

Route = dict[str, Any] | tuple[int, dict[str, str], Any] | Exception | Callable[[dict[str, str]], Any]


class FakeTransport:
    """One handler for every request (OMDb has a single endpoint). Records every call."""

    def __init__(self, handler: Route | None = None) -> None:
        self.handler = handler
        self.calls: list[tuple[dict[str, str], dict[str, str], str]] = []

    def __call__(self, url: str, headers: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
        parts = urlsplit(url)
        assert parts.netloc == HOST and parts.scheme == "https", url
        params = dict(parse_qsl(parts.query))
        self.calls.append((params, dict(headers), url))
        route = self.handler(params) if callable(self.handler) and not isinstance(self.handler, Exception) else self.handler
        if route is None:
            return 404, {}, b""
        if isinstance(route, Exception):
            raise route
        if isinstance(route, tuple):
            status, response_headers, body = route
            return status, response_headers, body if isinstance(body, bytes) else json.dumps(body).encode()
        return 200, {}, json.dumps(route).encode()

    @property
    def params(self) -> list[dict[str, str]]:
        return [{k: v for k, v in call[0].items() if k != "apikey"} for call in self.calls]


def credentials() -> OmdbCredentials:
    return OmdbCredentials(secret=SECRET)


def make_session(handler: Route | None = None, *, max_calls: int = 4) -> tuple[HttpSession, FakeTransport]:
    transport = FakeTransport(handler)
    return HttpSession(credentials=credentials(), transport=transport, max_calls=max_calls), transport


def make_tool(handler: Route | None = None, *, max_calls: int = 4):
    from tool.omdb.config import OmdbConfig
    from tool.omdb.tool import OmdbTool

    transport = FakeTransport(handler)
    tool = OmdbTool(config=OmdbConfig(max_calls_per_turn=max_calls), credentials=credentials(), transport=transport)
    return tool, transport


def record(
    imdb_id: str = "tt1000001",
    title: str = "Sample Movie",
    year: str = "2016",
    *,
    kind: str = "movie",
    imdb: str | None = "7.9",
    metascore: str | None = "81",
    rotten: str | None = "94%",
    votes: str | None = "720,000",
    plot: str = "A plot that must never reach the model.",
) -> dict[str, Any]:
    ratings = []
    if imdb is not None:
        ratings.append({"Source": "Internet Movie Database", "Value": f"{imdb}/10"})
    if rotten is not None:
        ratings.append({"Source": "Rotten Tomatoes", "Value": rotten})
    if metascore is not None:
        ratings.append({"Source": "Metacritic", "Value": f"{metascore}/100"})
    return {
        "Title": title,
        "Year": year,
        "Type": kind,
        "Plot": plot,
        "imdbID": imdb_id,
        "imdbRating": imdb if imdb is not None else "N/A",
        "imdbVotes": votes if votes is not None else "N/A",
        "Metascore": metascore if metascore is not None else "N/A",
        "Ratings": ratings,
        "Response": "True",
    }


def search_hit(imdb_id: str, title: str, year: str, kind: str = "movie") -> dict[str, str]:
    return {"Title": title, "Year": year, "imdbID": imdb_id, "Type": kind, "Poster": "N/A"}


def search_answer(*hits: dict[str, str]) -> dict[str, Any]:
    return {"Search": list(hits), "totalResults": str(len(hits)), "Response": "True"}


NOT_FOUND = {"Response": "False", "Error": "Movie not found!"}
# Observed live for an unknown IMDb ID (HTTP 200).
UNKNOWN_ID = {"Response": "False", "Error": "Error getting data."}
TOO_MANY = {"Response": "False", "Error": "Too many results."}
LIMIT = {"Response": "False", "Error": "Request limit reached!"}
BAD_KEY = {"Response": "False", "Error": "Invalid API key!"}


def by_endpoint(*, search: Any = None, by_id: dict[str, Any] | None = None) -> Callable[[dict[str, str]], Any]:
    """`s=` requests get `search`; `i=` requests get the record registered for that ID."""

    def handler(params: dict[str, str]) -> Any:
        if "s" in params:
            return search
        return (by_id or {}).get(params.get("i", ""), NOT_FOUND)

    return handler


def doc_step():
    """The `omdb_calls` step whose web form is the example in `web_api/contracts/chat_stream.md`:
    a title lookup (two requests) whose second request is the record by IMDb ID."""
    from tool.omdb.ratings import extract_ratings
    from tool.omdb.trace import build_omdb_trace
    from turn import TraceStep

    (step,) = build_omdb_trace(
        [
            {"method": "GET", "url": "https://www.omdbapi.com/?s=Sample+Movie&r=json&type=movie&apikey=***"},
            {"method": "GET", "url": "https://www.omdbapi.com/?i=tt1000001&r=json&apikey=***"},
        ],
        status="ok",
        title="Sample Movie",
        year="2016",
        work_type="movie",
        imdb_id="tt1000001",
        ratings=extract_ratings(record(rotten=None)),
    )
    return TraceStep(**step)
