"""The only module that sends requests to TVmaze.

Order for every request: run memo (answers and failures) → rate-limit pause → turn budget → call
recorded → request sent. A memo hit sends nothing and records nothing; every request that is sent
is recorded, also when it fails. There are no retries: an HTTP 429 starts a short pause (shared by
the process) during which nothing is sent, and the caller falls back to another source.

TVmaze needs no key. Errors are raised outside any `except` block, so they have no `__cause__` or
`__context__`, and carry neither the URL nor the text of the answer.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode

from turn import http_call

from .errors import (
    TvmazeError,
    TvmazeHttpError,
    TvmazeNetworkError,
    TvmazeRateLimited,
    TvmazeResponseTooLarge,
    TvmazeTimeout,
    TvmazeTurnLimit,
)
from .queries import Request
from .session import HttpSession, MemoKey
from .settings import BASE_URL, HTTP_TIMEOUT_SECONDS, MAX_RESPONSE_BYTES, USER_AGENT

_ALLOWED_PATH = re.compile(r"^/(search/shows|shows/\d+(/seasons|/episodes)?)$")
_HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}


def urllib_transport(url: str, headers: Mapping[str, str], timeout: float) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (https, fixed host)
            return response.status, dict(response.headers.items()), response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, dict(exc.headers.items()) if exc.headers else {}, exc.read(MAX_RESPONSE_BYTES + 1) or b""
        finally:
            exc.close()


def _is_timeout(exc: BaseException) -> bool:
    return isinstance(exc, TimeoutError) or (
        isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, TimeoutError)
    )


def _transmit(session: HttpSession, url: str) -> tuple[int, Mapping[str, str], bytes] | TvmazeError:
    """Send one request; transport failures are returned, never raised."""
    # Recorded where the URL is built, so what is shown is what is sent.
    session.calls.append(http_call("GET", url))
    try:
        return session.transport(url, _HEADERS, HTTP_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 - any transport failure; its message may contain the URL
        if _is_timeout(exc):
            return TvmazeTimeout("TVmaze request timed out.")
        return TvmazeNetworkError("TVmaze request failed (network).")


def _retry_after(headers: Mapping[str, str]) -> str | None:
    for name, value in headers.items():
        if name.lower() == "retry-after":
            return value
    return None


def _decode(body: bytes) -> list[Any] | dict[str, Any] | None:
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, (list, dict)) else None


def _send(session: HttpSession, url: str) -> Any:
    if session.pause.active():
        raise TvmazeRateLimited("TVmaze asked to slow down: paused for a few seconds.")
    if len(session.calls) >= session.max_calls:
        raise TvmazeTurnLimit("TVmaze call limit of this turn reached.")
    response = _transmit(session, url)
    if isinstance(response, TvmazeError):
        raise response
    status, headers, body = response
    if status == 429:
        session.pause.trip(_retry_after(headers))
        raise TvmazeRateLimited("TVmaze rate limit reached.")
    if len(body) > MAX_RESPONSE_BYTES:
        raise TvmazeResponseTooLarge("TVmaze answer is too large.")
    if status == 404:
        return None
    if status != 200:
        raise TvmazeHttpError(f"TVmaze answered with HTTP {int(status)}.")
    payload = _decode(body)
    if payload is None:
        raise TvmazeHttpError("TVmaze answered with an unexpected payload.")
    return payload


def get_json(session: HttpSession, request: Request) -> Any:
    """One request; a 404 answers None (the caller decides). Anything else wrong raises a TvmazeError."""
    path, params = request
    if not _ALLOWED_PATH.match(path):
        raise TvmazeHttpError("TVmaze path is not allowed.")
    key: MemoKey = (path, tuple(sorted(params)))
    if key in session.memo:
        return session.memo[key]
    if key in session.failures:
        raise session.failures[key]
    url = f"{BASE_URL}{path}" + (f"?{urlencode(params)}" if params else "")
    sent = len(session.calls)
    try:
        payload = _send(session, url)
    except TvmazeError as exc:
        # Remembered only if it was sent and was not a rate limit (the pause already covers that).
        if len(session.calls) > sent and not isinstance(exc, TvmazeRateLimited):
            session.failures[key] = exc
        raise
    session.memo[key] = payload
    return payload
