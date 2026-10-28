"""The only module that sends requests to OMDb.

Order for every request: run memo (answers and failures) → turn budget → call recorded →
request sent. A memo hit sends nothing and records nothing; every request that is sent is
recorded, also when it fails. There are no retries.

Secrets: the URL with the key is built and used only inside `_transmit`, which never raises.
Errors are raised by the caller outside any `except` block, so they have no `__cause__` or
`__context__`, and no frame of their traceback holds the URL. The `Error` text of the API is only
classified (`responses.response_kind`), never copied.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from turn import http_call

from .auth import OmdbCredentials, authorize
from .calls import CallRecorder
from .errors import (
    OmdbApiError,
    OmdbAuthError,
    OmdbError,
    OmdbHttpError,
    OmdbNetworkError,
    OmdbQuotaExceeded,
    OmdbTimeout,
    OmdbTurnLimit,
)
from .responses import ERROR, KEY, QUOTA, response_kind
from .settings import BASE_URL, HTTP_TIMEOUT_SECONDS

# (url, headers, timeout) -> (status, response headers, body)
Transport = Callable[[str, Mapping[str, str], float], tuple[int, Mapping[str, str], bytes]]
MemoKey = tuple[tuple[str, str], ...]


def urllib_transport(url: str, headers: Mapping[str, str], timeout: float) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (https, fixed host)
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as exc:
        # The error body says what happened; the exception (whose URL has the key) is dropped.
        try:
            return exc.code, dict(exc.headers.items()) if exc.headers else {}, exc.read() or b""
        finally:
            exc.close()


@dataclass(kw_only=True)
class HttpSession:
    """State of one turn: dependencies, the call budget, and what was already asked."""

    credentials: OmdbCredentials
    transport: Transport
    max_calls: int
    recorder: CallRecorder = field(default_factory=CallRecorder)
    # Answers already obtained in this turn: never requested twice.
    memo: dict[MemoKey, dict[str, Any]] = field(default_factory=dict)
    # Requests sent in this turn that failed: never sent again (no retries).
    failures: dict[MemoKey, OmdbError] = field(default_factory=dict)


def memo_key(params: Mapping[str, str]) -> MemoKey:
    # Built before the key is added, so it never contains it.
    return tuple(sorted((key, str(value)) for key, value in params.items()))


def _is_timeout(exc: BaseException) -> bool:
    return isinstance(exc, TimeoutError) or (
        isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, TimeoutError)
    )


def _transmit(
    session: HttpSession,
    params: Mapping[str, str],
) -> tuple[int, Mapping[str, str], bytes] | OmdbError:
    """Send one request; transport failures are returned, never raised, so this frame
    (the only one holding the URL with the key) is never part of a traceback."""
    query, headers = authorize(session.credentials, params)
    url = f"{BASE_URL}?{urlencode(query)}"
    # Recorded where the URL is built, so what is shown is what is sent; the key is masked here.
    session.recorder.record(http_call("GET", url, [session.credentials.secret]))
    try:
        return session.transport(url, headers, HTTP_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 - any transport failure; its message may contain the URL
        if _is_timeout(exc):
            return OmdbTimeout("OMDb request timed out.")
        return OmdbNetworkError("OMDb request failed (network).")


def _decode(body: bytes) -> dict[str, Any] | None:
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _send(session: HttpSession, params: Mapping[str, str]) -> dict[str, Any]:
    if len(session.recorder.calls) >= session.max_calls:
        raise OmdbTurnLimit("OMDb call limit of this turn reached.")
    response = _transmit(session, params)
    if isinstance(response, OmdbError):
        raise response
    status, _, body = response
    payload = _decode(body)
    kind = response_kind(payload) if payload is not None else None
    if kind == QUOTA:
        raise OmdbQuotaExceeded("OMDb daily request limit reached.")
    if kind == KEY or status == 401:
        raise OmdbAuthError("OMDb rejected the API key.")
    if status != 200:
        raise OmdbHttpError(f"OMDb answered with HTTP {int(status)}.")
    if payload is None:
        raise OmdbHttpError("OMDb answered with an unexpected payload.")
    if kind == ERROR:
        raise OmdbApiError("OMDb refused the request.")
    return payload


def get_json(session: HttpSession, params: Mapping[str, str]) -> dict[str, Any]:
    """One request; "not found" and "too many results" answers are returned (the caller decides)."""
    key = memo_key(params)
    if key in session.memo:
        return session.memo[key]
    if key in session.failures:
        raise session.failures[key]
    sent = len(session.recorder.calls)
    try:
        payload = _send(session, params)
    except OmdbError as exc:
        if len(session.recorder.calls) > sent:  # it was sent: remember the failure
            session.failures[key] = exc
        raise
    session.memo[key] = payload
    return payload
