"""The only module that talks to TVmaze: memo, pause on 429, budget, errors, recorded calls (offline)."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tool.tvmaze import http
from tool.tvmaze.errors import (
    TvmazeHttpError,
    TvmazeNetworkError,
    TvmazeRateLimited,
    TvmazeResponseTooLarge,
    TvmazeTimeout,
    TvmazeTurnLimit,
)
from tool.tvmaze.queries import search_request, seasons_request, show_request
from tool.tvmaze.session import RateLimitPause
from tvmaze_support import make_session


def test_every_request_sent_is_recorded_with_its_full_url_and_a_user_agent() -> None:
    session, transport = make_session({"/search/shows": []})
    http.get_json(session, search_request("The Bear"))
    assert session.calls == [{"method": "GET", "url": "https://api.tvmaze.com/search/shows?q=The+Bear"}]
    assert transport.calls[0][3] == session.calls[0]["url"]
    assert "NetflixScout" in transport.calls[0][2]["User-Agent"]


def test_embed_parameters_are_sent_in_the_array_syntax() -> None:
    session, transport = make_session({"/shows/1": {}})
    http.get_json(session, show_request(1, cast=True, next_episode=True))
    assert transport.calls[0][1] == [("embed[]", "cast"), ("embed[]", "nextepisode")]


def test_memo_hits_send_and_record_nothing() -> None:
    session, transport = make_session({"/search/shows": []})
    http.get_json(session, search_request("x"))
    http.get_json(session, search_request("x"))
    assert len(transport.calls) == 1 == len(session.calls)


def test_404_is_an_answer_not_an_error() -> None:
    session, _ = make_session({})
    assert http.get_json(session, seasons_request(9)) is None


def test_budget_is_enforced_and_failures_are_not_retried() -> None:
    session, transport = make_session({"/search/shows": (500, {}, b"")}, max_calls=1)
    with pytest.raises(TvmazeHttpError):
        http.get_json(session, search_request("a"))
    with pytest.raises(TvmazeHttpError):  # same request: remembered failure, not sent again
        http.get_json(session, search_request("a"))
    with pytest.raises(TvmazeTurnLimit):
        http.get_json(session, search_request("b"))
    assert len(transport.calls) == 1


def test_429_starts_a_pause_during_which_nothing_is_sent_and_is_not_retried() -> None:
    now = [100.0]
    pause = RateLimitPause(clock=lambda: now[0])
    session, transport = make_session({"/search/shows": (429, {"Retry-After": "3"}, b"")}, pause=pause)
    with pytest.raises(TvmazeRateLimited):
        http.get_json(session, search_request("a"))
    assert pause.active()
    with pytest.raises(TvmazeRateLimited):
        http.get_json(session, search_request("b"))
    assert len(transport.calls) == 1
    now[0] += 3.5
    assert not pause.active()


def test_retry_after_is_clamped_and_a_bad_value_uses_the_default() -> None:
    now = [0.0]
    for header, expected in (("9999", 60.0), ("0", 1.0), ("soon", 5.0), (None, 5.0)):
        pause = RateLimitPause(clock=lambda: now[0])
        pause.trip(header)
        now[0] = expected - 0.1
        assert pause.active(), header
        now[0] = expected + 0.1
        assert not pause.active(), header
        now[0] = 0.0


def test_transport_failures_have_safe_messages_and_no_chained_exceptions() -> None:
    for failure, expected in ((TimeoutError("https://api.tvmaze.com/secret"), TvmazeTimeout), (OSError("https://x/y"), TvmazeNetworkError)):
        session, _ = make_session({"/search/shows": failure})
        with pytest.raises(expected) as caught:
            http.get_json(session, search_request("a"))
        assert "http" not in str(caught.value) and caught.value.__cause__ is None and caught.value.__context__ is None


def test_bad_payload_and_oversized_answers_are_errors() -> None:
    session, _ = make_session({"/search/shows": (200, {}, b"<html>")})
    with pytest.raises(TvmazeHttpError):
        http.get_json(session, search_request("a"))
    from tool.tvmaze import settings

    session, _ = make_session({"/search/shows": (200, {}, b"x" * (settings.MAX_RESPONSE_BYTES + 1))})
    with pytest.raises(TvmazeResponseTooLarge):
        http.get_json(session, search_request("a"))


def test_paths_outside_the_allowlist_are_refused_without_sending() -> None:
    session, transport = make_session({})
    with pytest.raises(TvmazeHttpError):
        http.get_json(session, ("/people/1", ()))
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
