"""The only module that sends requests to the YouTube Data API.

Order for every request: run memo (answers and failures) → quota latch → call recorded →
request sent. A memo hit or an active latch sends nothing and records nothing; every
request that is sent is recorded, also when it fails. There are no retries.

Secrets: the URL with the key is built and used only inside `_transmit`, which never
raises. Errors are raised by the caller outside any `except` block, so they have no
`__cause__` or `__context__`, and no frame of their traceback holds the URL. Only the
`reason` of an API error is read, never its `message`.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from .auth import YoutubeCredentials, authorize
from .calls import CallRecorder, display_url
from .errors import (
    YoutubeApiNotEnabled,
    YoutubeAuthError,
    YoutubeError,
    YoutubeHttpError,
    YoutubeNetworkError,
    YoutubeQuotaExceeded,
    YoutubeRateLimited,
    YoutubeTimeout,
)
from .quota import QuotaBucket, QuotaLatch, bucket_for
from .settings import BASE_URL, HTTP_TIMEOUT_SECONDS, RATE_LIMIT_PAUSE_SECONDS

# (url, headers, timeout) -> (status, response headers, body)
Transport = Callable[[str, Mapping[str, str], float], tuple[int, Mapping[str, str], bytes]]
MemoKey = tuple[str, tuple[tuple[str, str], ...]]

# The only endpoints the tool calls.
ALLOWED_PATHS = frozenset({"/search", "/videos"})

QUOTA_REASONS = frozenset({"quotaExceeded", "dailyLimitExceeded"})
RATE_LIMIT_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded", "RATE_LIMIT_EXCEEDED"})
AUTH_REASONS = frozenset({"keyInvalid", "keyExpired", "ipRefererBlocked", "forbidden", "API_KEY_INVALID"})
NOT_ENABLED_REASONS = frozenset({"accessNotConfigured", "SERVICE_DISABLED"})


def urllib_transport(url: str, headers: Mapping[str, str], timeout: float) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (https, fixed host)
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as exc:
        # The error body carries the `reason`; the exception (whose URL has the key) is dropped.
        try:
            return exc.code, dict(exc.headers.items()) if exc.headers else {}, exc.read() or b""
        finally:
            exc.close()


@dataclass(kw_only=True)
class HttpSession:
    """Dependencies of one tool run. The latch outlives the run (one per tool)."""

    credentials: YoutubeCredentials
    transport: Transport
    latch: QuotaLatch
    recorder: CallRecorder = field(default_factory=CallRecorder)
    # Answers already obtained in this run: never requested twice.
    memo: dict[MemoKey, dict[str, Any]] = field(default_factory=dict)
    # Requests sent in this run that failed: never sent again (no retries).
    failures: dict[MemoKey, YoutubeError] = field(default_factory=dict)


def memo_key(path: str, params: Mapping[str, str]) -> MemoKey:
    # Built before the key is added, so it never contains it.
    return path, tuple(sorted((key, str(value)) for key, value in params.items()))


def _is_timeout(exc: BaseException) -> bool:
    return isinstance(exc, TimeoutError) or (
        isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, TimeoutError)
    )


def _transmit(
    session: HttpSession,
    path: str,
    params: Mapping[str, str],
) -> tuple[int, Mapping[str, str], bytes] | YoutubeError:
    """Send one request; transport failures are returned, never raised, so this frame
    (the only one holding the URL with the key) is never part of a traceback."""
    query, headers = authorize(session.credentials, params)
    url = f"{BASE_URL}{path}?{urlencode(query)}"
    try:
        return session.transport(url, headers, HTTP_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 - any transport failure; its message may contain the URL
        if _is_timeout(exc):
            return YoutubeTimeout("YouTube request timed out.")
        return YoutubeNetworkError("YouTube request failed (network).")


def error_reason(body: bytes) -> str | None:
    """`reason` of a Google API error body (`error.errors[0]` or `error.details[].reason`)."""
    try:
        error = json.loads(body).get("error")
    except (ValueError, AttributeError, UnicodeDecodeError):
        return None
    if not isinstance(error, dict):
        return None
    for item in [*(error.get("errors") or []), *(error.get("details") or [])]:
        if isinstance(item, dict) and isinstance(item.get("reason"), str):
            return item["reason"]
    return None


def _api_error(session: HttpSession, bucket: QuotaBucket, status: int, body: bytes) -> YoutubeError:
    reason = error_reason(body)
    if reason in QUOTA_REASONS:
        session.latch.trip_until_reset(bucket)
        return YoutubeQuotaExceeded("YouTube daily quota exceeded.")
    if reason in RATE_LIMIT_REASONS or status == 429:
        # A 429 without a quota reason is a short-term limit: pausing until midnight
        # would lose the day's searches on a guess.
        session.latch.pause(bucket, RATE_LIMIT_PAUSE_SECONDS)
        return YoutubeRateLimited("YouTube rate limit reached.")
    if reason in NOT_ENABLED_REASONS:
        return YoutubeApiNotEnabled("YouTube Data API is not enabled for this key.")
    if reason in AUTH_REASONS or status == 401:
        return YoutubeAuthError("YouTube rejected the API key.")
    return YoutubeHttpError(f"YouTube answered with HTTP {int(status)}.")


def _send(session: HttpSession, path: str, params: Mapping[str, str]) -> dict[str, Any]:
    bucket = bucket_for(path)
    blocked = session.latch.blocked(bucket)
    if blocked == YoutubeQuotaExceeded.code:
        raise YoutubeQuotaExceeded("YouTube daily quota exceeded: paused until the reset.")
    if blocked == YoutubeRateLimited.code:
        raise YoutubeRateLimited("YouTube rate limit: paused.")

    session.recorder.record(display_url(path))
    response = _transmit(session, path, params)
    if isinstance(response, YoutubeError):
        raise response
    status, _, body = response
    if status != 200:
        raise _api_error(session, bucket, status, body)

    payload = None
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        pass
    if not isinstance(payload, dict):
        # Raised here, not in the `except`: no `__context__`.
        raise YoutubeHttpError("YouTube answered with an unexpected payload.")
    return payload


def get_json(session: HttpSession, path: str, params: Mapping[str, str]) -> dict[str, Any]:
    if path not in ALLOWED_PATHS:
        raise ValueError(f"Unsupported YouTube endpoint: {path}")
    key = memo_key(path, params)
    if key in session.memo:
        return session.memo[key]
    if key in session.failures:
        raise session.failures[key]
    sent = len(session.recorder.calls)
    try:
        payload = _send(session, path, params)
    except YoutubeError as exc:
        if len(session.recorder.calls) > sent:  # it was sent: remember the failure
            session.failures[key] = exc
        raise
    session.memo[key] = payload
    return payload
