from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from omdb_support import BAD_KEY, LIMIT, NOT_FOUND, SECRET, TOO_MANY, make_session, record
from tool.omdb import http
from tool.omdb.errors import (
    OmdbApiError,
    OmdbAuthError,
    OmdbError,
    OmdbHttpError,
    OmdbNetworkError,
    OmdbQuotaExceeded,
    OmdbTimeout,
    OmdbTurnLimit,
)

PARAMS = {"i": "tt1000001", "r": "json"}


def test_a_request_goes_to_the_fixed_https_host_with_the_key_and_the_full_url_is_recorded_masked() -> None:
    session, transport = make_session(record())

    assert http.get_json(session, PARAMS)["imdbID"] == "tt1000001"
    assert transport.calls[0][0]["apikey"] == SECRET
    # The URL actually sent, every parameter, with only the key value replaced.
    assert session.recorder.calls == [{"method": "GET", "url": "https://www.omdbapi.com/?i=tt1000001&r=json&apikey=***"}]
    assert transport.calls[0][2].replace(SECRET, "***") == session.recorder.calls[0]["url"]


def test_the_same_request_in_a_turn_is_answered_from_the_memo() -> None:
    session, transport = make_session(record())

    first = http.get_json(session, PARAMS)
    second = http.get_json(session, dict(reversed(list(PARAMS.items()))))

    assert first is second and len(transport.calls) == 1 and len(session.recorder.calls) == 1


def test_a_failed_request_is_not_sent_again_in_the_turn() -> None:
    session, transport = make_session((500, {}, b"oops"))

    for _ in range(2):
        with pytest.raises(OmdbHttpError):
            http.get_json(session, PARAMS)

    assert len(transport.calls) == 1  # no retry


def test_the_turn_budget_stops_the_requests_before_they_are_sent() -> None:
    session, transport = make_session(record(), max_calls=1)
    http.get_json(session, PARAMS)

    with pytest.raises(OmdbTurnLimit):
        http.get_json(session, {"i": "tt1000002"})

    assert len(transport.calls) == 1


def test_not_found_and_too_many_results_are_returned_for_the_caller_to_decide() -> None:
    assert http.get_json(make_session(NOT_FOUND)[0], PARAMS) == NOT_FOUND
    assert http.get_json(make_session(TOO_MANY)[0], {"s": "x"}) == TOO_MANY


@pytest.mark.parametrize(
    ("route", "error"),
    [
        ((401, {}, LIMIT), OmdbQuotaExceeded),
        ((200, {}, LIMIT), OmdbQuotaExceeded),
        ((401, {}, BAD_KEY), OmdbAuthError),
        ((401, {}, b""), OmdbAuthError),
        ((200, {}, {"Response": "False", "Error": "Something new"}), OmdbApiError),
        ((503, {}, b"<html>"), OmdbHttpError),
        ((200, {}, b"<html>not json"), OmdbHttpError),
        ((200, {}, b"[1, 2]"), OmdbHttpError),
        (TimeoutError("took too long"), OmdbTimeout),
        (OSError("connection refused"), OmdbNetworkError),
    ],
)
def test_failures_map_to_typed_errors(route, error) -> None:
    session, _ = make_session(route)

    with pytest.raises(error):
        http.get_json(session, PARAMS)


def test_a_transport_error_never_carries_the_url_or_the_key() -> None:
    class Leaky(Exception):
        pass

    def leaky(url, headers, timeout):
        raise Leaky(url)

    session, _ = make_session()
    session.transport = leaky
    with pytest.raises(OmdbError) as caught:
        http.get_json(session, PARAMS)

    error = caught.value
    assert SECRET not in str(error) and SECRET not in repr(error)
    assert error.__cause__ is None and error.__context__ is None


def test_the_api_error_text_is_not_copied_into_the_exception() -> None:
    text = "Request limit reached! secret-marker"
    session, _ = make_session((401, {}, json.dumps({"Response": "False", "Error": text}).encode()))

    with pytest.raises(OmdbQuotaExceeded) as caught:
        http.get_json(session, PARAMS)

    assert "secret-marker" not in str(caught.value) and caught.value.__context__ is None


def test_only_http_py_sends_requests() -> None:
    root = Path(http.__file__).parent
    io_modules = {"urllib.request", "urllib.error", "http.client", "socket", "requests", "httpx"}
    offenders = []
    for path in root.rglob("*.py"):
        if "harness" in path.parts or path.name == "http.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            if any(name in io_modules or name.startswith("urllib.") for name in names):
                offenders.append(path.name)

    assert offenders == []
