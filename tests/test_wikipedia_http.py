"""Offline tests of `wikipedia/http.py`: fake transport, no network."""
from __future__ import annotations

import ast
import traceback
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path

import pytest
from wikipedia_support import FakeTransport, error_body, make_session

from wikipedia import http as wiki_http
from wikipedia.budget import TurnState
from wikipedia.errors import (
    WikipediaBudgetExhausted,
    WikipediaError,
    WikipediaHttpError,
    WikipediaNetworkError,
    WikipediaRateLimited,
    WikipediaResponseTooLarge,
    WikipediaTimeout,
)
from wikipedia.http import RateLimitPause, TtlCache, get_json, retry_after, urllib_transport
from wikipedia.settings import MAX_RESPONSE_BYTES, USER_AGENT

ROOT = Path(__file__).resolve().parents[1]
PARAMS = {"action": "query", "gsrsearch": '"Park Chan-wook"'}
OK = {"query": {"pages": []}}


def test_success_sends_the_user_agent_and_records_only_the_base_url() -> None:
    transport = FakeTransport(it=OK)
    session = make_session(transport)

    assert get_json(session, "it", PARAMS) == OK

    language, params, headers, url = transport.calls[0]
    assert language == "it" and params == PARAMS and headers["User-Agent"] == USER_AGENT
    assert url.startswith("https://it.wikipedia.org/w/api.php?")
    assert session.calls == ["https://it.wikipedia.org/w/api.php"] and "gsrsearch" not in repr(session.calls)


def test_an_unsupported_language_is_refused_before_any_call() -> None:
    transport = FakeTransport(fr=OK)

    with pytest.raises(ValueError):
        get_json(make_session(transport), "fr", PARAMS)
    assert transport.calls == []


def test_the_same_request_is_sent_once_per_run_and_once_per_ttl_across_runs() -> None:
    transport = FakeTransport(it=OK)
    cache = TtlCache(3600)
    first = make_session(transport, cache=cache)

    get_json(first, "it", PARAMS)
    get_json(first, "it", PARAMS)
    second = make_session(transport, cache=cache, state=TurnState())
    get_json(second, "it", PARAMS)

    assert len(transport.calls) == 1 and first.reused == 0 and second.reused == 1
    assert second.calls == [] and second.state.http_used == 0  # a cache hit costs nothing


def test_a_zero_ttl_disables_the_cache() -> None:
    transport = FakeTransport(it=OK)
    cache = TtlCache(0)

    get_json(make_session(transport, cache=cache), "it", PARAMS)
    get_json(make_session(transport, cache=cache), "it", PARAMS)

    assert len(transport.calls) == 2


def test_cache_entries_expire_and_are_bounded() -> None:
    now = [0.0]
    cache = TtlCache(10, max_entries=2, clock=lambda: now[0])
    keys = [wiki_http.request_key("it", {"q": str(i)}) for i in range(3)]
    for key in keys:
        cache.set(key, {"v": 1})

    assert cache.get(keys[0]) is None and cache.get(keys[2]) == {"v": 1}
    now[0] = 11.0
    assert cache.get(keys[2]) is None


def test_a_failed_request_is_not_sent_again_in_the_same_turn() -> None:
    transport = FakeTransport(it=(500, {}, b""))
    state = TurnState()

    for _ in range(2):
        with pytest.raises(WikipediaHttpError):
            get_json(make_session(transport, state=state), "it", PARAMS)

    assert len(transport.calls) == 1


def test_the_turn_budget_counts_sent_requests_only() -> None:
    transport = FakeTransport(it=OK)
    state = TurnState()
    session = make_session(transport, max_calls=2, state=state)

    get_json(session, "it", {"a": "1"})
    get_json(session, "it", {"a": "2"})
    get_json(session, "it", {"a": "1"})  # memo: free
    with pytest.raises(WikipediaBudgetExhausted):
        get_json(session, "it", {"a": "3"})

    assert len(transport.calls) == 2 and state.http_used == 2


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        ((429, {"Retry-After": "7"}, b""), WikipediaRateLimited),
        ((200, {"Retry-After": "5"}, error_body("maxlag")), WikipediaRateLimited),
        ((200, {}, error_body("ratelimited")), WikipediaRateLimited),
        ((200, {}, error_body("badvalue")), WikipediaHttpError),
        ((500, {}, b""), WikipediaHttpError),
        ((404, {}, b""), WikipediaHttpError),
        ((200, {}, b"not json"), WikipediaHttpError),
        ((200, {}, b"[1, 2]"), WikipediaHttpError),
        ((200, {}, b"x" * (MAX_RESPONSE_BYTES + 1)), WikipediaResponseTooLarge),
    ],
)
def test_answers_are_mapped_to_errors_from_status_and_error_code_only(answer, error) -> None:
    with pytest.raises(error):
        get_json(make_session(FakeTransport(it=answer)), "it", PARAMS)


def test_maxlag_comes_with_status_200_and_still_pauses_without_retrying() -> None:
    transport = FakeTransport(it=(200, {"Retry-After": "5"}, error_body("maxlag")))
    pause = RateLimitPause(clock=lambda: 100.0)
    session = make_session(transport, pause=pause)

    with pytest.raises(WikipediaRateLimited):
        get_json(session, "it", PARAMS)
    # Paused: the next request that would be sent fails at once, without any call or budget.
    with pytest.raises(WikipediaRateLimited):
        get_json(make_session(transport, pause=pause), "it", {"other": "1"})

    assert len(transport.calls) == 1 and pause.active()


def test_the_pause_follows_retry_after_within_its_limits() -> None:
    now = [0.0]
    pause = RateLimitPause(clock=lambda: now[0])

    pause.trip(None)
    assert 4.9 < pause.remaining() <= 5.0
    pause.trip(30)
    assert 29.9 < pause.remaining() <= 30.0
    pause.trip(100_000)
    assert pause.remaining() <= 60.0
    now[0] = 61.0
    assert not pause.active()


def test_a_pause_does_not_block_the_cache() -> None:
    transport = FakeTransport(it=OK)
    cache = TtlCache(3600)
    get_json(make_session(transport, cache=cache), "it", PARAMS)
    pause = RateLimitPause()
    pause.trip(30)

    assert get_json(make_session(transport, cache=cache, pause=pause), "it", PARAMS) == OK


@pytest.mark.parametrize(
    ("failure", "error"),
    [
        (TimeoutError("timed out for https://it.wikipedia.org/?q=SECRET"), WikipediaTimeout),
        (urllib.error.URLError(TimeoutError("t")), WikipediaTimeout),
        (urllib.error.URLError("dns SECRET"), WikipediaNetworkError),
        (ConnectionResetError("reset SECRET"), WikipediaNetworkError),
    ],
)
def test_transport_failures_are_classified_without_leaking_the_query(failure, error) -> None:
    topic = {"gsrsearch": "SECRET-TOPIC"}
    with pytest.raises(error) as caught:
        get_json(make_session(FakeTransport(it=failure)), "it", topic)

    assert "SECRET" not in str(caught.value) and caught.value.__cause__ is None
    assert "SECRET" not in "".join(traceback.format_exception(caught.value))


def test_no_error_exposes_the_user_agent_or_the_query() -> None:
    for answer in ((429, {}, b""), (500, {}, b""), (200, {}, error_body("maxlag"))):
        with pytest.raises(WikipediaError) as caught:
            get_json(make_session(FakeTransport(it=answer)), "it", {"gsrsearch": "SECRET-TOPIC"})
        assert "SECRET" not in str(caught.value) and "marcomilza" not in str(caught.value)


def test_retry_after_reads_any_case_and_ignores_garbage() -> None:
    assert retry_after({"retry-after": "12"}) == 12.0
    assert retry_after({"Retry-After": "soon"}) is None
    assert retry_after({}) is None


def test_urllib_transport_returns_the_status_and_headers_of_http_errors(monkeypatch) -> None:
    headers = Message()
    headers["Retry-After"] = "9"

    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 429, "Too Many", headers, None)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    status, response_headers, body = urllib_transport("https://it.wikipedia.org/w/api.php?q=SECRET", {}, 1.0)

    assert status == 429 and response_headers["Retry-After"] == "9" and body == b""


def test_every_error_class_is_a_wikipedia_error() -> None:
    for cls in (WikipediaRateLimited, WikipediaTimeout, WikipediaNetworkError, WikipediaHttpError,
                WikipediaResponseTooLarge, WikipediaBudgetExhausted):
        assert issubclass(cls, WikipediaError)


def test_only_http_py_does_network_io_in_the_wikipedia_package() -> None:
    offenders = set()
    for path in sorted((ROOT / "wikipedia").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            network = [name for name in names if name != "urllib.parse"]
            if any(name.split(".")[0] in {"urllib", "http", "socket", "requests", "httpx"} for name in network):
                offenders.add(path.relative_to(ROOT).as_posix())
            if isinstance(node, ast.Attribute) and node.attr == "urlopen":
                offenders.add(path.relative_to(ROOT).as_posix())
    assert offenders == {"wikipedia/http.py"}
