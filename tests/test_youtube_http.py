"""Offline tests of `youtube/http.py`: fake transport, no network, no `.env`."""
from __future__ import annotations

import ast
import io
import socket
import traceback
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path

import pytest
from youtube_support import BASE, SECRET, error_body, make_session

from youtube import http as yt_http
from youtube.calls import display_url
from youtube.errors import (
    YoutubeApiNotEnabled,
    YoutubeAuthError,
    YoutubeError,
    YoutubeHttpError,
    YoutubeNetworkError,
    YoutubeQuotaExceeded,
    YoutubeRateLimited,
    YoutubeTimeout,
)
from youtube.http import get_json, urllib_transport
from youtube.quota import QuotaBucket, QuotaLatch

ROOT = Path(__file__).resolve().parents[1]
SEARCH = {"part": "snippet", "q": '"Dune" interview', "type": "video"}
VIDEOS = {"part": "snippet,contentDetails", "id": "abcdefghijk"}
URL_WITH_KEY = f"{BASE}/search?part=snippet&key={SECRET}"


def test_success_sends_the_key_but_records_only_the_masked_endpoint() -> None:
    session, transport = make_session({"/search": {"items": []}})

    assert get_json(session, "/search", SEARCH) == {"items": []}

    path, params, headers, url = transport.calls[0]
    assert path == "/search" and params == {**SEARCH, "key": SECRET}
    assert url.startswith(f"{BASE}/search?") and headers == {"Accept": "application/json"}
    assert session.recorder.calls == [f"{BASE}/search?key=***"] == [display_url("/search")]
    assert "Dune" not in session.recorder.calls[0]


def test_the_same_request_is_sent_once_per_run() -> None:
    session, transport = make_session({"/search": {"items": [1]}})

    get_json(session, "/search", SEARCH)
    get_json(session, "/search", dict(reversed(list(SEARCH.items()))))

    assert len(transport.calls) == 1 and len(session.recorder.calls) == 1
    assert all(SECRET not in str(key) for key in session.memo)


def test_a_failed_request_is_not_retried_in_the_same_run() -> None:
    session, transport = make_session({"/search": (500, {}, b"")})

    for _ in range(2):
        with pytest.raises(YoutubeHttpError):
            get_json(session, "/search", SEARCH)

    assert len(transport.calls) == 1


def test_unsupported_endpoints_are_refused_before_any_call() -> None:
    session, transport = make_session({"/channels": {}})

    with pytest.raises(ValueError):
        get_json(session, "/channels", {})

    assert transport.calls == [] and session.recorder.calls == []


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        (error_body(403, "quotaExceeded"), YoutubeQuotaExceeded),
        (error_body(403, "dailyLimitExceeded"), YoutubeQuotaExceeded),
        (error_body(429, "quotaExceeded"), YoutubeQuotaExceeded),
        (error_body(403, "rateLimitExceeded"), YoutubeRateLimited),
        (error_body(403, "userRateLimitExceeded"), YoutubeRateLimited),
        (error_body(429, details_reason="RATE_LIMIT_EXCEEDED"), YoutubeRateLimited),
        (error_body(429), YoutubeRateLimited),
        (error_body(400, "keyInvalid"), YoutubeAuthError),
        (error_body(400, "badRequest", details_reason="API_KEY_INVALID"), YoutubeHttpError),
        (error_body(400, details_reason="API_KEY_INVALID"), YoutubeAuthError),
        (error_body(403, "forbidden"), YoutubeAuthError),
        (error_body(403, "ipRefererBlocked"), YoutubeAuthError),
        (error_body(401), YoutubeAuthError),
        (error_body(403, "accessNotConfigured"), YoutubeApiNotEnabled),
        (error_body(403, details_reason="SERVICE_DISABLED"), YoutubeApiNotEnabled),
        (error_body(403, "somethingNew"), YoutubeHttpError),
        (error_body(500, "backendError"), YoutubeHttpError),
        ((503, {}, b"<html>down</html>"), YoutubeHttpError),
        ((404, {}, b""), YoutubeHttpError),
    ],
)
def test_api_errors_are_mapped_from_the_reason_only(answer, error) -> None:
    session, _ = make_session({"/search": answer})

    with pytest.raises(error) as exc:
        get_json(session, "/search", SEARCH)

    assert type(exc.value) is error
    assert "Error message from Google" not in str(exc.value)


def test_the_first_reason_wins_over_details() -> None:
    # `errors[0]` is the documented YouTube field; `details` is the newer Google format.
    assert yt_http.error_reason(b'{"error": {"errors": [{"reason": "quotaExceeded"}], "details": [{"reason": "X"}]}}') == (
        "quotaExceeded"
    )
    assert yt_http.error_reason(b"not json") is None
    assert yt_http.error_reason(b'["error"]') is None
    assert yt_http.error_reason(b'{"error": "text"}') is None


def test_quota_error_on_search_pauses_only_the_search_bucket() -> None:
    latch = QuotaLatch()
    session, transport = make_session({"/search": error_body(403, "quotaExceeded"), "/videos": {"items": []}}, latch=latch)

    with pytest.raises(YoutubeQuotaExceeded):
        get_json(session, "/search", SEARCH)
    with pytest.raises(YoutubeQuotaExceeded):
        get_json(session, "/search", {**SEARCH, "q": "other"})

    # The second search was neither sent nor recorded; /videos uses another bucket.
    assert transport.paths == ["/search"] and len(session.recorder.calls) == 1
    assert get_json(session, "/videos", VIDEOS) == {"items": []}
    assert latch.blocked(QuotaBucket.search) == "quota_exceeded"
    assert latch.blocked(QuotaBucket.default) is None


def test_quota_spent_elsewhere_is_found_by_the_first_call() -> None:
    """The latch knows nothing about other processes: the API answer is the authority."""
    latch = QuotaLatch()
    assert latch.blocked(QuotaBucket.search) is None
    session, transport = make_session({"/search": error_body(403, "quotaExceeded")}, latch=latch)

    with pytest.raises(YoutubeQuotaExceeded):
        get_json(session, "/search", SEARCH)

    assert len(transport.calls) == 1 and latch.blocked(QuotaBucket.search) == "quota_exceeded"


def test_quota_error_on_videos_pauses_only_the_default_bucket() -> None:
    latch = QuotaLatch()
    session, _ = make_session({"/videos": error_body(403, "quotaExceeded"), "/search": {"items": []}}, latch=latch)

    with pytest.raises(YoutubeQuotaExceeded):
        get_json(session, "/videos", VIDEOS)

    assert latch.blocked(QuotaBucket.default) == "quota_exceeded"
    assert get_json(session, "/search", SEARCH) == {"items": []}


def test_the_latch_is_shared_by_the_runs_of_one_tool() -> None:
    latch = QuotaLatch()
    first, _ = make_session({"/search": error_body(403, "quotaExceeded")}, latch=latch)
    with pytest.raises(YoutubeQuotaExceeded):
        get_json(first, "/search", SEARCH)

    second, transport = make_session({"/search": {"items": []}}, latch=latch)
    with pytest.raises(YoutubeQuotaExceeded):
        get_json(second, "/search", SEARCH)

    assert transport.calls == [] and second.recorder.calls == []


def test_rate_limit_pauses_briefly() -> None:
    clock_now = [1_000.0]
    latch = QuotaLatch(lambda: clock_now[0])
    session, transport = make_session({"/search": error_body(403, "rateLimitExceeded")}, latch=latch)

    with pytest.raises(YoutubeRateLimited):
        get_json(session, "/search", SEARCH)
    assert latch.blocked(QuotaBucket.search) == "rate_limited"

    clock_now[0] += 10.0
    assert latch.blocked(QuotaBucket.search) is None


@pytest.mark.parametrize("body", [b"not json", b"[1, 2]", b'"text"', b"\xff\xfe"])
def test_invalid_success_payload_is_an_http_error(body) -> None:
    session, _ = make_session({"/search": (200, {}, body)})

    with pytest.raises(YoutubeHttpError) as exc:
        get_json(session, "/search", SEARCH)

    assert exc.value.__context__ is None


@pytest.mark.parametrize(
    ("failure", "error"),
    [
        (TimeoutError(f"timed out {URL_WITH_KEY}"), YoutubeTimeout),
        (socket.timeout(f"timed out {URL_WITH_KEY}"), YoutubeTimeout),
        (urllib.error.URLError(TimeoutError(URL_WITH_KEY)), YoutubeTimeout),
        (urllib.error.URLError(f"no route to {URL_WITH_KEY}"), YoutubeNetworkError),
        (ConnectionResetError(URL_WITH_KEY), YoutubeNetworkError),
        (ValueError(URL_WITH_KEY), YoutubeNetworkError),
    ],
)
def test_transport_failures_are_classified(failure, error) -> None:
    session, _ = make_session({"/search": failure})

    with pytest.raises(error):
        get_json(session, "/search", SEARCH)

    assert session.recorder.calls == [display_url("/search")]


def _assert_no_secret(exc: BaseException) -> None:
    assert exc.__cause__ is None and exc.__context__ is None
    rendered = [str(exc), repr(exc), repr(exc.args), "".join(traceback.format_exception(exc))]
    tb = exc.__traceback__
    while tb is not None:
        rendered.extend(repr(value) for value in tb.tb_frame.f_locals.values())
        tb = tb.tb_next
    for text in rendered:
        assert SECRET not in text


def _http_error(status: int, body: bytes) -> urllib.error.HTTPError:
    headers = Message()
    headers["Content-Type"] = "application/json"
    return urllib.error.HTTPError(URL_WITH_KEY, status, f"Forbidden {URL_WITH_KEY}", headers, io.BytesIO(body))


def test_urllib_transport_returns_http_errors_with_their_body(monkeypatch) -> None:
    body = b'{"error": {"errors": [{"reason": "quotaExceeded"}]}}'

    def _urlopen(request, timeout):
        raise _http_error(403, body)

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)

    status, headers, returned = urllib_transport(URL_WITH_KEY, {}, 1.0)

    assert (status, returned, headers.get("Content-Type")) == (403, body, "application/json")


@pytest.mark.parametrize(
    ("raised", "error"),
    [
        (lambda: _http_error(403, b'{"error": {"errors": [{"reason": "quotaExceeded"}]}}'), YoutubeQuotaExceeded),
        (lambda: _http_error(400, b'{"error": {"errors": [{"reason": "keyInvalid"}]}}'), YoutubeAuthError),
        (lambda: _http_error(500, b""), YoutubeHttpError),
        (lambda: urllib.error.URLError(f"unreachable {URL_WITH_KEY}"), YoutubeNetworkError),
        (lambda: urllib.error.URLError(socket.timeout(URL_WITH_KEY)), YoutubeTimeout),
        (lambda: OSError(URL_WITH_KEY), YoutubeNetworkError),
    ],
)
def test_no_error_exposes_the_key(monkeypatch, raised, error) -> None:
    """Through the real `urllib_transport`: HTTPError carries the URL with the key in
    `url`, `filename` and its message; none of it may reach the raised error."""

    def _urlopen(request, timeout):
        assert SECRET in request.full_url  # the key is really sent
        raise raised()

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    session, _ = make_session()
    session.transport = urllib_transport

    with pytest.raises(error) as exc:
        get_json(session, "/search", SEARCH)

    _assert_no_secret(exc.value)
    # The remembered failure, raised again from the memo, is just as clean.
    with pytest.raises(error) as again:
        get_json(session, "/search", SEARCH)
    _assert_no_secret(again.value)
    assert all(SECRET not in url for url in session.recorder.calls)


def test_errors_raised_by_an_active_latch_have_no_secret() -> None:
    latch = QuotaLatch()
    latch.trip_until_reset(QuotaBucket.search)
    session, _ = make_session(latch=latch)

    with pytest.raises(YoutubeQuotaExceeded) as exc:
        get_json(session, "/search", SEARCH)

    _assert_no_secret(exc.value)


def test_every_error_class_is_a_youtube_error() -> None:
    for cls in (YoutubeQuotaExceeded, YoutubeRateLimited, YoutubeAuthError, YoutubeApiNotEnabled, YoutubeTimeout,
                YoutubeNetworkError, YoutubeHttpError):
        assert issubclass(cls, YoutubeError)


def test_only_http_py_does_network_io_in_the_youtube_package() -> None:
    offenders = set()
    for path in sorted((ROOT / "youtube").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            # `urllib.parse` only builds strings; every other network module is I/O.
            network = [name for name in names if name != "urllib.parse"]
            if any(name.split(".")[0] in {"urllib", "http", "socket", "requests", "httpx"} for name in network):
                offenders.add(path.relative_to(ROOT).as_posix())
            if isinstance(node, ast.Attribute) and node.attr == "urlopen":
                offenders.add(path.relative_to(ROOT).as_posix())
    assert offenders == {"youtube/http.py"}
