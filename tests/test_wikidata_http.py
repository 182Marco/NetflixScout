"""The only module that talks to Wikidata: memo, pause on 429, budget, errors, recorded calls (offline)."""
from __future__ import annotations

import ast
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import pytest
from wikidata_support import make_session, search_payload, sparql

from tool.wikidata import http, settings
from tool.wikidata.errors import (
    WikidataHttpError,
    WikidataNetworkError,
    WikidataRateLimited,
    WikidataResponseTooLarge,
    WikidataTimeout,
    WikidataTurnLimit,
)
from tool.wikidata.queries import relations_request, search_request
from tool.wikidata.session import RateLimitPause


def test_every_request_sent_is_recorded_with_its_full_url_and_a_user_agent() -> None:
    session, transport = make_session({"search": search_payload()})
    http.get_json(session, search_request("The Thing", "en"))

    [call] = session.calls
    assert call["method"] == "GET" and call["url"] == transport.calls[0][3]
    assert call["url"].startswith("https://www.wikidata.org/w/api.php?action=wbsearchentities&search=The+Thing&language=en")
    assert "NetflixScout" in transport.calls[0][2]["User-Agent"]


def test_the_sparql_text_is_in_the_recorded_url_exactly_as_sent() -> None:
    session, transport = make_session({"relations": sparql([])})
    request = relations_request("Q9000001")
    http.get_json(session, request)

    url = session.calls[0]["url"]
    parts = urlsplit(url)
    assert parts.netloc == "query.wikidata.org" and parts.path == "/sparql"
    assert dict(parse_qsl(parts.query))["query"] == dict(request[1])["query"]
    assert url == transport.calls[0][3]


def test_memo_hits_send_and_record_nothing() -> None:
    session, transport = make_session({"search": search_payload()})
    http.get_json(session, search_request("x", "en"))
    http.get_json(session, search_request("x", "en"))
    assert len(transport.calls) == 1 == len(session.calls)


def test_budget_is_enforced_and_failures_are_not_retried() -> None:
    session, transport = make_session({"search": (500, {}, b"")}, max_calls=1)
    with pytest.raises(WikidataHttpError):
        http.get_json(session, search_request("a", "en"))
    with pytest.raises(WikidataHttpError):  # same request: remembered failure, not sent again
        http.get_json(session, search_request("a", "en"))
    with pytest.raises(WikidataTurnLimit):
        http.get_json(session, search_request("b", "en"))
    assert len(transport.calls) == 1


def test_a_query_that_ran_too_long_is_an_error_whose_text_is_not_read() -> None:
    session, _ = make_session({"relations": (504, {}, b"upstream request timeout SELECT secret")})
    with pytest.raises(WikidataHttpError) as caught:
        http.get_json(session, relations_request("Q9000001"))
    assert "SELECT" not in str(caught.value) and "http" not in str(caught.value).lower().replace("http 504", "")


def test_429_starts_a_pause_during_which_nothing_is_sent_and_is_not_retried() -> None:
    now = [100.0]
    pause = RateLimitPause(clock=lambda: now[0])
    session, transport = make_session({"search": (429, {"Retry-After": "3"}, b"")}, pause=pause)
    with pytest.raises(WikidataRateLimited):
        http.get_json(session, search_request("a", "en"))
    assert pause.active()
    with pytest.raises(WikidataRateLimited):
        http.get_json(session, search_request("b", "en"))
    assert len(transport.calls) == 1
    now[0] += 3.5
    assert not pause.active()


def test_transport_failures_have_safe_messages_and_no_chained_exceptions() -> None:
    for failure, expected in ((TimeoutError("https://www.wikidata.org/secret"), WikidataTimeout), (OSError("https://x/y"), WikidataNetworkError)):
        session, _ = make_session({"search": failure})
        with pytest.raises(expected) as caught:
            http.get_json(session, search_request("a", "en"))
        assert "http" not in str(caught.value) and caught.value.__cause__ is None and caught.value.__context__ is None


def test_bad_payloads_api_errors_and_oversized_answers_are_errors() -> None:
    for body in (b"<html>", b"[]", b'{"error": {"code": "bad"}}'):
        session, _ = make_session({"search": (200, {}, body)})
        with pytest.raises(WikidataHttpError):
            http.get_json(session, search_request("a", "en"))

    session, _ = make_session({"search": (200, {}, b"x" * (settings.MAX_RESPONSE_BYTES + 1))})
    with pytest.raises(WikidataResponseTooLarge):
        http.get_json(session, search_request("a", "en"))


def test_endpoints_outside_the_allowlist_are_refused_without_sending() -> None:
    session, transport = make_session({})
    with pytest.raises(WikidataHttpError):
        http.get_json(session, ("elsewhere", (("query", "x"),)))
    assert transport.calls == []


def test_only_http_py_sends_requests() -> None:
    root = Path(http.__file__).parent
    io_modules = {"urllib.request", "urllib.error", "http.client", "socket", "requests", "httpx"}
    offenders = []
    for path in root.rglob("*.py"):
        if "harness" in path.parts or path.name == "http.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            if any(name in io_modules or name.startswith("urllib.request") or name.startswith("urllib.error") for name in names):
                offenders.append(path.name)
    assert offenders == []
