"""The only module that sends requests to Wikidata.

Order for every request: run memo (answers and failures) → rate-limit pause → turn budget → call
recorded → request sent. A memo hit sends nothing and records nothing; every request that is sent
is recorded, also when it fails. There are no retries: an HTTP 429 starts a short pause (shared by
the process) during which nothing is sent, and the caller reports the data as unavailable.

Wikidata needs no key. Errors are raised outside any `except` block, so they have no `__cause__` or
`__context__`, and carry neither the URL nor the text of the answer (the SPARQL text included).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode

from turn import http_call

from .errors import (
    WikidataError,
    WikidataHttpError,
    WikidataNetworkError,
    WikidataRateLimited,
    WikidataResponseTooLarge,
    WikidataTimeout,
    WikidataTurnLimit,
)
from .queries import Request
from .session import HttpSession, MemoKey
from .settings import API_URL, HTTP_TIMEOUT_SECONDS, MAX_RESPONSE_BYTES, SPARQL_URL, USER_AGENT

_ENDPOINTS = {"api": API_URL, "sparql": SPARQL_URL}
_HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}


def urllib_transport(url: str, headers: Mapping[str, str], timeout: float) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (https, fixed hosts)
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


def _transmit(session: HttpSession, url: str) -> tuple[int, Mapping[str, str], bytes] | WikidataError:
    """Send one request; transport failures are returned, never raised."""
    # Recorded where the URL is built, so what is shown is what is sent.
    session.calls.append(http_call("GET", url))
    try:
        return session.transport(url, _HEADERS, HTTP_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 - any transport failure; its message may contain the URL
        if _is_timeout(exc):
            return WikidataTimeout("Wikidata request timed out.")
        return WikidataNetworkError("Wikidata request failed (network).")


def _retry_after(headers: Mapping[str, str]) -> str | None:
    for name, value in headers.items():
        if name.lower() == "retry-after":
            return value
    return None


def _decode(body: bytes) -> dict[str, Any] | None:
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _send(session: HttpSession, url: str) -> dict[str, Any]:
    if session.pause.active():
        raise WikidataRateLimited("Wikidata asked to slow down: paused for a few seconds.")
    if len(session.calls) >= session.max_calls:
        raise WikidataTurnLimit("Wikidata call limit of this turn reached.")
    response = _transmit(session, url)
    if isinstance(response, WikidataError):
        raise response
    status, headers, body = response
    if status == 429:
        session.pause.trip(_retry_after(headers))
        raise WikidataRateLimited("Wikidata rate limit reached.")
    if len(body) > MAX_RESPONSE_BYTES:
        raise WikidataResponseTooLarge("Wikidata answer is too large.")
    if status != 200:
        # 500 and 504 of the Query Service are a query that ran too long; the text of the answer is not read.
        raise WikidataHttpError(f"Wikidata answered with HTTP {int(status)}.")
    payload = _decode(body)
    if payload is None or "error" in payload:
        raise WikidataHttpError("Wikidata answered with an unexpected payload.")
    return payload


def get_json(session: HttpSession, request: Request) -> dict[str, Any]:
    """One request. Anything wrong raises a WikidataError (a missing entity is an empty answer, not an error)."""
    endpoint, params = request
    base = _ENDPOINTS.get(endpoint)
    if base is None:
        raise WikidataHttpError("Wikidata endpoint is not allowed.")
    key: MemoKey = (endpoint, tuple(sorted(params)))
    if key in session.memo:
        return session.memo[key]
    if key in session.failures:
        raise session.failures[key]
    url = f"{base}?{urlencode(params)}"
    sent = len(session.calls)
    try:
        payload = _send(session, url)
    except WikidataError as exc:
        # Remembered only if it was sent and was not a rate limit (the pause already covers that).
        if len(session.calls) > sent and not isinstance(exc, WikidataRateLimited):
            session.failures[key] = exc
        raise
    session.memo[key] = payload
    return payload
