"""Offline helpers for the Wikipedia tests: a fake transport that records calls, and
MediaWiki-shaped answers. Nothing here touches the network or reads `.env`."""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from wikipedia.budget import TurnRegistry, TurnState
from wikipedia.http import HttpSession, RateLimitPause, TtlCache

Route = dict[str, Any] | tuple[int, dict[str, str], Any] | Exception | Callable[[dict[str, str]], Any]

ARTICLE_TEXT = """Park Chan-wook è un regista sudcoreano. Ha diretto Oldboy.

== Biografia ==
Nato a Seul nel 1963, studiò filosofia all'università Sogang.

== Carriera ==
Esordì nel 1992 con The Moon Is... the Sun's Dream. Il successo arrivò con Joint Security Area.

== Filmografia ==
Elenco dei film diretti.

== Note ==
Nota 1.
"""


class FakeTransport:
    """Routes by a `(language, mode)` key chosen by `route_of`; records every call."""

    def __init__(self, handler: Callable[[str, dict[str, str]], Any] | None = None, **routes: Any) -> None:
        self.handler = handler
        self.routes = routes
        self.calls: list[tuple[str, dict[str, str], dict[str, str], str]] = []

    def __call__(self, url: str, headers: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
        parts = urlsplit(url)
        language = parts.netloc.split(".")[0]
        params = dict(parse_qsl(parts.query))
        self.calls.append((language, params, dict(headers), url))
        route = self.handler(language, params) if self.handler else self.routes.get(language)
        if callable(route) and not isinstance(route, Exception):
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
    def languages(self) -> list[str]:
        return [call[0] for call in self.calls]


def make_session(transport: FakeTransport, *, max_calls: int = 6, state: TurnState | None = None,
                 cache: TtlCache | None = None, pause: RateLimitPause | None = None) -> HttpSession:
    return HttpSession(
        transport=transport,
        state=state or TurnState(),
        max_calls=max_calls,
        cache=cache or TtlCache(3600),
        pause=pause or RateLimitPause(),
    )


def make_tool(handler=None, *, max_results: int = 3, max_calls: int = 6, cache_ttl: int = 3600,
              context_chars: int = 40_000, **routes):
    from wikipedia.config import WikipediaConfig
    from wikipedia.tool import WikipediaTool

    transport = FakeTransport(handler, **routes)
    tool = WikipediaTool(
        config=WikipediaConfig(
            max_results=max_results, max_calls_per_turn=max_calls, cache_ttl=cache_ttl, context_chars_per_turn=context_chars
        ),
        transport=transport,
    )
    return tool, transport


def lookup_answer(*pages: dict[str, Any]) -> dict[str, Any]:
    return {"batchcomplete": True, "query": {"pages": list(pages)}}


def page(title: str, extract: str = "Testo introduttivo.", *, index: int = 1, pageid: int | None = None,
         disambiguation: bool = False, touched: str = "2026-09-30T10:12:00Z") -> dict[str, Any]:
    row: dict[str, Any] = {
        "pageid": pageid or index * 100, "ns": 0, "title": title, "index": index, "extract": extract, "touched": touched,
    }
    if disambiguation:
        row["pageprops"] = {"disambiguation": ""}
    return row


def article_answer(title: str = "Park Chan-wook", text: str = ARTICLE_TEXT) -> dict[str, Any]:
    return lookup_answer(page(title, text, index=0))


def missing_answer(title: str = "Inesistente") -> dict[str, Any]:
    return {"batchcomplete": True, "query": {"pages": [{"title": title, "missing": True}]}}


def by_mode(*, lookup: Any, article: Any) -> Callable[[str, dict[str, str]], Any]:
    """Handler answering `generator=search` requests with `lookup` and `titles=` ones with `article`
    (each may be a dict, a tuple status/headers/body, an exception or a function of the params)."""

    def handler(language: str, params: dict[str, str]) -> Any:
        return lookup if "generator" in params else article

    return handler


def error_body(code: str = "maxlag") -> dict[str, Any]:
    return {"error": {"code": code, "info": "Waiting for a database server: 7 seconds lagged.", "host": "db1"}}


def run_tool(tool, *, query: str = "domanda", **arguments: Any) -> dict[str, Any]:
    # The turn language is Italian unless a test says otherwise (the fake pages are Italian).
    params = {"topic": "Park Chan-wook", "turn_language": "it", **arguments}
    return tool.run(query=query, params=params, conversation_history=[])


def doc_step():
    """The `wikipedia_calls` step whose web form is the example in `web_api/FRONTEND_API.md`."""
    from turn import STEP_WIKIPEDIA_CALLS, TraceStep

    return TraceStep(
        kind=STEP_WIKIPEDIA_CALLS,
        title="Wikipedia",
        data={
            "calls": ["https://it.wikipedia.org/w/api.php"],
            "reused": 0,
            "searches": [
                {"language": "it", "q": '"Park Chan-wook"', "result": "ok", "error": None, "returned": 3, "kept": 2,
                 "filtered_out": {"disambiguation": 1}}
            ],
            "opens": [{"language": "it", "title": "Park Chan-wook", "result": "ok", "error": None}],
            "pages": [
                {"title": "Park Chan-wook", "language": "it", "url": "https://it.wikipedia.org/wiki/Park_Chan-wook",
                 "verification": "confirmed", "notes": [], "last_revised": "2026-09-30T10:12:00Z",
                 "total_chars": 18420, "delivered_chars": 5230, "sections": ["Introduzione", "Biografia", "Carriera"],
                 "omitted": 6}
            ],
            "license": {"name": "CC BY-SA 4.0", "url": "https://creativecommons.org/licenses/by-sa/4.0/"},
        },
    )
