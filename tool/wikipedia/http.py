"""The only module that sends requests to Wikipedia.

Order for every request: run memo → failures of the turn → TTL cache → rate-limit pause →
turn call budget → call recorded → request sent. A memo or cache hit sends nothing, counts
nothing and is not recorded as a call (the cache hits are counted in `reused`); every request
that is sent counts and is recorded, also when it fails. There are no retries and no waiting:
a rate limit pauses the next sent requests (they fail at once) instead of sleeping.

`maxlag` is answered with HTTP 200 and `error.code == "maxlag"` (mediawiki.org/wiki/Manual:Maxlag_parameter),
so the body is read for errors whatever the status. Only the error `code` is read, never its text.

Errors are raised outside any `except` block (no `__cause__`): the URL, which holds the user's
topic, never reaches a message or a traceback. No key exists; the User-Agent identifies the client.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from turn import http_call

from .budget import TurnState
from .errors import (
    WikipediaBudgetExhausted,
    WikipediaError,
    WikipediaHttpError,
    WikipediaNetworkError,
    WikipediaRateLimited,
    WikipediaResponseTooLarge,
    WikipediaTimeout,
)
from .queries import api_url
from .settings import (
    CACHE_MAX_ENTRIES,
    HTTP_TIMEOUT_SECONDS,
    LANGUAGES,
    MAX_RESPONSE_BYTES,
    RATE_LIMIT_PAUSE_MAX_SECONDS,
    RATE_LIMIT_PAUSE_SECONDS,
    USER_AGENT,
)

# (url, headers, timeout) -> (status, response headers, body)
Transport = Callable[[str, Mapping[str, str], float], tuple[int, Mapping[str, str], bytes]]
RequestKey = tuple[str, tuple[tuple[str, str], ...]]

# Error codes of the API body that mean "wait": replication lag and the API's own rate limit.
WAIT_CODES = frozenset({"maxlag", "ratelimited"})


def urllib_transport(url: str, headers: Mapping[str, str], timeout: float) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (https, fixed hosts)
            # One byte more than the maximum tells the caller the answer was too large.
            return response.status, dict(response.headers.items()), response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        # Only the status and headers (Retry-After) matter; the exception, whose URL holds the query, is dropped.
        try:
            return exc.code, dict(exc.headers.items()) if exc.headers else {}, b""
        finally:
            exc.close()


class TtlCache:
    """Process-wide TTL cache of successful answers, shared by the turns; bounded, thread-safe."""

    def __init__(
        self,
        ttl_seconds: int,
        *,
        max_entries: int = CACHE_MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._clock = clock
        self._items: OrderedDict[RequestKey, tuple[float, dict[str, Any]]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: RequestKey) -> dict[str, Any] | None:
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            expires_at, value = item
            if self._clock() >= expires_at:
                del self._items[key]
                return None
            self._items.move_to_end(key)
            return value

    def set(self, key: RequestKey, value: dict[str, Any]) -> None:
        if self.ttl_seconds <= 0:
            return
        with self._lock:
            self._items[key] = (self._clock() + self.ttl_seconds, value)
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)


class RateLimitPause:
    """After a rate limit or lag answer, requests that would be sent fail at once for a while."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._until = 0.0
        self._lock = threading.Lock()

    def active(self) -> bool:
        with self._lock:
            return self._clock() < self._until

    def trip(self, seconds: float | None) -> None:
        wait = RATE_LIMIT_PAUSE_SECONDS if seconds is None else min(max(seconds, 1.0), RATE_LIMIT_PAUSE_MAX_SECONDS)
        with self._lock:
            self._until = max(self._until, self._clock() + wait)

    def remaining(self) -> float:
        with self._lock:
            return max(self._until - self._clock(), 0.0)


@dataclass(kw_only=True)
class HttpSession:
    """Dependencies of one tool run. The cache, the pause and the turn state outlive the run."""

    transport: Transport
    state: TurnState
    max_calls: int
    cache: TtlCache
    pause: RateLimitPause
    # Display URLs of the requests sent in this run (no parameters).
    calls: list[dict[str, str]] = field(default_factory=list)
    # Requests of this run served by the cache.
    reused: int = 0
    memo: dict[RequestKey, dict[str, Any]] = field(default_factory=dict)


def request_key(language: str, params: Mapping[str, str]) -> RequestKey:
    return language, tuple(sorted((key, str(value)) for key, value in params.items()))


def _is_timeout(exc: BaseException) -> bool:
    return isinstance(exc, TimeoutError) or (
        isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, TimeoutError)
    )


def _transmit(
    session: HttpSession, url: str
) -> tuple[int, Mapping[str, str], bytes] | WikipediaError:
    """Send one request; transport failures are returned, never raised, so this frame (the only
    one holding the URL with the topic) is never part of a traceback."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    try:
        return session.transport(url, headers, HTTP_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 - any transport failure; its message may contain the URL
        if _is_timeout(exc):
            return WikipediaTimeout("Wikipedia request timed out.")
        return WikipediaNetworkError("Wikipedia request failed (network).")


def retry_after(headers: Mapping[str, str]) -> float | None:
    """Seconds asked by a `Retry-After` header (any case); None if absent or not a number."""
    for name, value in headers.items():
        if name.lower() == "retry-after":
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    return None


def _decode(body: bytes) -> dict[str, Any] | None:
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _send(session: HttpSession, language: str, params: Mapping[str, str]) -> dict[str, Any]:
    if session.pause.active():
        raise WikipediaRateLimited("Wikipedia rate limit: paused.")
    if not session.state.try_reserve_http(session.max_calls):
        raise WikipediaBudgetExhausted("Wikipedia call limit for this turn reached.")
    # Recorded where the URL is built, so what is shown is what is sent (Wikipedia needs no key).
    url = f"{api_url(language)}?{urlencode(dict(params))}"
    session.calls.append(http_call("GET", url))

    response = _transmit(session, url)
    if isinstance(response, WikipediaError):
        raise response
    status, headers, body = response
    if len(body) > MAX_RESPONSE_BYTES:
        raise WikipediaResponseTooLarge("Wikipedia answer too large to read.")
    if status == 429:
        session.pause.trip(retry_after(headers))
        raise WikipediaRateLimited("Wikipedia rate limit reached.")
    if status != 200:
        raise WikipediaHttpError(f"Wikipedia answered with HTTP {int(status)}.")

    payload = _decode(body)
    if payload is None:
        # Raised here, not in the `except` of `_decode`: no `__context__`.
        raise WikipediaHttpError("Wikipedia answered with an unexpected payload.")
    error = payload.get("error")
    if error is not None:
        code = error.get("code") if isinstance(error, dict) else None
        if code in WAIT_CODES:
            session.pause.trip(retry_after(headers))
            raise WikipediaRateLimited("Wikipedia rate limit reached.")
        raise WikipediaHttpError("Wikipedia answered with an API error.")
    return payload


def get_json(session: HttpSession, language: str, params: Mapping[str, str]) -> dict[str, Any]:
    if language not in LANGUAGES:
        raise ValueError(f"Unsupported Wikipedia language: {language}")
    key = request_key(language, params)
    if key in session.memo:
        return session.memo[key]
    failure = session.state.failures.get(key)
    if failure is not None:
        raise failure[0](failure[1])
    cached = session.cache.get(key)
    if cached is not None:
        session.reused += 1
        session.memo[key] = cached
        return cached
    sent = session.state.http_used
    try:
        payload = _send(session, language, params)
    except WikipediaError as exc:
        if session.state.http_used > sent and not isinstance(exc, WikipediaRateLimited):
            # It was sent and failed: the same request is not sent again in this turn.
            session.state.failures[key] = (type(exc), str(exc))
        raise
    session.cache.set(key, payload)
    session.memo[key] = payload
    return payload
