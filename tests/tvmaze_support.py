"""Offline helpers for the TVmaze tests: a fake transport that records calls and TVmaze-shaped
answers. Nothing here touches the network. Series, names and numbers are invented fixtures, not
real TVmaze data."""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from tool.tvmaze.session import HttpSession, RateLimitPause

HOST = "api.tvmaze.com"

Route = Any  # payload | (status, headers, body) | Exception | None (404)


class FakeTransport:
    """Routes by path. Records every call as (path, params, headers, url)."""

    def __init__(self, routes: dict[str, Route] | Callable[[str, list[tuple[str, str]]], Route] | None = None) -> None:
        self.routes = routes or {}
        self.calls: list[tuple[str, list[tuple[str, str]], dict[str, str], str]] = []

    def __call__(self, url: str, headers: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
        parts = urlsplit(url)
        assert parts.netloc == HOST and parts.scheme == "https", url
        params = parse_qsl(parts.query, keep_blank_values=True)
        self.calls.append((parts.path, params, dict(headers), url))
        route = self.routes(parts.path, params) if callable(self.routes) else self.routes.get(parts.path)
        if isinstance(route, Exception):
            raise route
        if route is None:
            return 404, {}, b""
        if isinstance(route, tuple):
            status, response_headers, body = route
            return status, response_headers, body if isinstance(body, bytes) else json.dumps(body).encode()
        return 200, {}, json.dumps(route).encode()

    @property
    def paths(self) -> list[str]:
        return [call[0] for call in self.calls]


def make_session(routes: Any = None, *, max_calls: int = 6, pause: RateLimitPause | None = None) -> tuple[HttpSession, FakeTransport]:
    transport = FakeTransport(routes)
    return HttpSession(transport=transport, max_calls=max_calls, pause=pause or RateLimitPause()), transport


def make_tool(routes: Any = None, *, max_calls: int = 6):
    from tool.tvmaze.config import TvmazeConfig
    from tool.tvmaze.tool import TvmazeTool

    transport = FakeTransport(routes)
    # A private pause per tool, so tests do not share the process-wide one.
    tool = TvmazeTool(config=TvmazeConfig(max_calls_per_turn=max_calls), transport=transport, pause=RateLimitPause())
    return tool, transport


def show(show_id: int = 1, name: str = "Sample Show", premiered: str = "2016-07-15", **extra: Any) -> dict[str, Any]:
    return {
        "id": show_id,
        "url": f"https://www.tvmaze.com/shows/{show_id}/sample-show",
        "name": name,
        "type": "Scripted",
        "language": "English",
        "genres": ["Drama", "Thriller"],
        "status": "Running",
        "runtime": 60,
        "averageRuntime": 58,
        "premiered": premiered,
        "ended": None,
        "network": {"id": 1, "name": "Sample Net", "country": {"name": "United States", "code": "US"}},
        "webChannel": None,
        "externals": {"imdb": "tt1000001"},
        "summary": "<p>A <b>sample</b> premise &amp; more.</p>",
        **extra,
    }


def search(*shows: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"score": 0.9 - i / 10, "show": item} for i, item in enumerate(shows)]


def episode(season: int, number: int | None, name: str = "Ep", airdate: str = "2016-07-15", **extra: Any) -> dict[str, Any]:
    return {
        "id": season * 100 + (number or 0),
        "season": season,
        "number": number,
        "name": name,
        "airdate": airdate,
        "airstamp": f"{airdate}T21:00:00+00:00",
        "runtime": 60,
        "type": "regular",
        "summary": "<p>A spoiler that must never reach the model.</p>",
        **extra,
    }


def routes_for(show_data: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    show_data = show_data or show()
    sid = show_data["id"]
    base: dict[str, Any] = {
        "/search/shows": search(show_data),
        f"/shows/{sid}": {
            **show_data,
            "_embedded": {
                "cast": [{"person": {"name": "Ann Actor"}, "character": {"name": "Cora"}}],
                "nextepisode": episode(3, 1, "Next One", "2030-01-01"),
            },
        },
        f"/shows/{sid}/seasons": [
            {"number": 1, "episodeOrder": 10, "premiereDate": "2016-07-15", "endDate": "2016-09-16"},
            {"number": 2, "episodeOrder": 8, "premiereDate": "2017-07-14", "endDate": "2017-09-01"},
        ],
        f"/shows/{sid}/episodes": [
            episode(1, 1, "Pilot"),
            episode(1, 2, "Second", "2016-07-22"),
            episode(2, 1, "Return", "2017-07-14"),
            episode(2, None, "A Special", "2017-12-24", type="significant_special"),
        ],
    }
    base.update(extra)
    return base


def doc_step():
    """The `tvmaze_calls` step whose web form is the example in `web_api/contracts/chat_stream.md`:
    a title search whose series card (cast, next episode) is read with a second request."""
    from tool.tvmaze.trace import build_tvmaze_trace
    from turn import TraceStep

    (step,) = build_tvmaze_trace(
        [
            {"method": "GET", "url": "https://api.tvmaze.com/search/shows?q=Sample+Show"},
            {"method": "GET", "url": "https://api.tvmaze.com/shows/1?embed%5B%5D=cast&embed%5B%5D=nextepisode"},
        ],
        status="ok",
        show={
            "name": "Sample Show",
            "url": "https://www.tvmaze.com/shows/1/sample-show",
            "status": "Running",
            "premiered": "2016-07-15",
            "network": "Sample Net",
        },
        facets=["info", "cast", "next"],
    )
    return TraceStep(**step)
