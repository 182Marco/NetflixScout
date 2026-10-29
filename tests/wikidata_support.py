"""Offline helpers for the Wikidata tests: a fake transport that records calls and answers shaped like the
entity search and the Query Service. Nothing here touches the network. Items, titles and numbers are invented
fixtures (ids in the Q9000000 range), not real Wikidata data."""
from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from tool.wikidata.session import HttpSession, RateLimitPause

TODAY = date(2026, 10, 29)
ENTITY = "http://www.wikidata.org/entity/"

Route = Any  # payload | (status, headers, body) | Exception


def kind_of(host: str, params: list[tuple[str, str]]) -> str:
    """Which request this is: search, label, details, relations or members."""
    if host == "www.wikidata.org":
        return "search"
    query = dict(params).get("query", "")
    if "?rel" in query:
        return "relations"
    if "VALUES ?f" in query:
        return "members"
    if "rdfs:label" in query:
        return "label"
    return "details"


class FakeTransport:
    """Routes by kind of request. Records every call as (kind, params, headers, url)."""

    def __init__(self, routes: dict[str, Route] | Callable[[str, list[tuple[str, str]]], Route] | None = None) -> None:
        self.routes = routes or {}
        self.calls: list[tuple[str, list[tuple[str, str]], dict[str, str], str]] = []

    def __call__(self, url: str, headers: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
        parts = urlsplit(url)
        assert parts.scheme == "https" and parts.netloc in {"www.wikidata.org", "query.wikidata.org"}, url
        params = parse_qsl(parts.query, keep_blank_values=True)
        kind = kind_of(parts.netloc, params)
        self.calls.append((kind, params, dict(headers), url))
        route = self.routes(kind, params) if callable(self.routes) else self.routes.get(kind)
        if callable(route):
            route = route(params)
        if isinstance(route, Exception):
            raise route
        if route is None:
            return 200, {}, json.dumps(sparql([]) if kind != "search" else {"search": []}).encode()
        if isinstance(route, tuple):
            status, response_headers, body = route
            return status, response_headers, body if isinstance(body, bytes) else json.dumps(body).encode()
        return 200, {}, json.dumps(route).encode()

    @property
    def kinds(self) -> list[str]:
        return [call[0] for call in self.calls]

    def sparql_texts(self) -> list[str]:
        return [dict(call[1]).get("query", "") for call in self.calls if call[0] != "search"]


def make_session(routes: Any = None, *, max_calls: int = 8, pause: RateLimitPause | None = None) -> tuple[HttpSession, FakeTransport]:
    transport = FakeTransport(routes)
    return HttpSession(transport=transport, max_calls=max_calls, pause=pause or RateLimitPause()), transport


def make_tool(routes: Any = None, *, max_calls: int = 8, today: date = TODAY):
    from tool.wikidata.config import WikidataConfig
    from tool.wikidata.tool import WikidataTool

    transport = FakeTransport(routes)
    # A private pause per tool, so tests do not share the process-wide one.
    tool = WikidataTool(
        config=WikidataConfig(max_calls_per_turn=max_calls), transport=transport, pause=RateLimitPause(), clock=lambda: today
    )
    return tool, transport


# --- answers ---------------------------------------------------------------------------------------------------


def search_payload(*rows: tuple[str, str]) -> dict[str, Any]:
    """`(id, matched text)` rows in the shape of `wbsearchentities`."""
    return {
        "search": [
            {"id": qid, "label": text, "description": "x", "match": {"type": "label", "language": "en", "text": text}}
            for qid, text in rows
        ]
    }


def sparql(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"head": {"vars": []}, "results": {"bindings": rows}}


def _cells(**values: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in values.items():
        if value is None:
            continue
        if isinstance(value, bool):
            out[key] = {"type": "literal", "value": "true" if value else "false"}
        elif key in {"w", "o", "f"}:
            out[key] = {"type": "uri", "value": ENTITY + value}
        else:
            out[key] = {"type": "literal", "value": str(value)}
    return out


def detail_row(
    qid: str,
    label: str,
    *,
    film: bool = True,
    series: bool = False,
    project: bool = False,
    pub: str | None = None,
    start: str | None = None,
    director: str | None = None,
    imdb: str | None = None,
    tmdb_movie: str | None = None,
    tmdb_tv: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    return _cells(
        w=qid, wLabel=label, wDescription=description, film=film, series=series, project=project,
        pub=pub, start=start, dirLabel=director, imdb=imdb, tmdbMovie=tmdb_movie, tmdbTv=tmdb_tv,
    )


def related_row(
    rel: str | None,
    qid: str,
    label: str,
    *,
    kind: str = "film",
    project: bool = False,
    pub: str | None = None,
    start: str | None = None,
    description: str | None = None,
    container: str | None = None,
) -> dict[str, Any]:
    flags = {name: name == kind for name in ("film", "series", "literary", "game", "comics")}
    return _cells(
        rel=rel, f=container, o=qid, oLabel=label, oDescription=description, project=project, pub=pub, start=start, **flags
    )


# One franchise of invented works.
SUBJECT = "Q9000001"
FRANCHISE = "Q9000100"


def _details(params: list[tuple[str, str]]) -> dict[str, Any]:
    """Two homonyms for a search by title; the one item an external id names."""
    first = detail_row(SUBJECT, "Sample Film", pub="1982-06-25T00:00:00Z", director="Ann Director", imdb="tt9000001", tmdb_movie="9001")
    second = detail_row("Q9000002", "Sample Film", pub="2004-05-06T00:00:00Z", director="Bo Director", imdb="tt9000002")
    query = dict(params).get("query", "")
    return sparql([first] if '"tt9000001"' in query or '"9001"' in query else [first, second])


def routes_for(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "search": search_payload((SUBJECT, "Sample Film"), ("Q9000002", "Sample Film")),
        "label": _details,
        "details": _details,
        "relations": sparql(
            [
                related_row("source", "Q9000010", "Sample Novel", kind="literary", pub="1968-01-01T00:00:00Z"),
                related_row("derived", "Q9000011", "Sample Remake", pub="2017-10-06T00:00:00Z"),
                related_row("next", "Q9000011", "Sample Remake", pub="2017-10-06T00:00:00Z"),
                related_row("container", FRANCHISE, "Sample Franchise", kind="none"),
            ]
        ),
        "members": sparql(
            [
                related_row(None, SUBJECT, "Sample Film", pub="1982-06-25T00:00:00Z", container=FRANCHISE),
                related_row(None, "Q9000011", "Sample Remake", pub="2017-10-06T00:00:00Z", container=FRANCHISE),
            ]
        ),
    }
    base.update(extra)
    return base


def doc_step():
    """The `wikidata_calls` step whose web form is the example in `web_api/contracts/chat_stream.md`:
    a title searched, identified and its relations read."""
    from tool.wikidata.trace import build_wikidata_trace
    from turn import TraceStep

    (step,) = build_wikidata_trace(
        [
            {"method": "GET", "url": "https://www.wikidata.org/w/api.php?action=wbsearchentities&search=Sample+Film&language=en&type=item&limit=10&format=json"},
            {"method": "GET", "url": "https://query.wikidata.org/sparql?query=SELECT+%3Fo+WHERE+%7B+...+%7D&format=json"},
        ],
        status="ok",
        operation="relations",
        work={"id": SUBJECT, "title": "Sample Film", "year": 1982, "kind": "film", "imdb_id": "tt9000001", "tmdb_id": 9001, "directors": ["Ann Director"]},
        relations={
            "sources": [{"id": "Q9000010", "title": "Sample Novel", "year": 1968, "kind": "literary"}],
            "derived": [{"id": "Q9000011", "title": "Sample Remake", "year": 2017, "kind": "film"}],
            "previous": [],
            "next": [],
        },
    )
    return TraceStep(**step)
