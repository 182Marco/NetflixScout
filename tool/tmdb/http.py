"""The only module that sends requests to TMDb.

Order for every request: turn memo (answers and failures) → TTL cache → 429 cooldown →
budget reservation → call recorded → request sent. A hit never consumes budget and is
never recorded; every attempt that is sent counts, also when it fails. There are no
retries: a request that failed is not sent again in the same turn.
Errors are re-raised `from None` with safe messages: the URL sent (which may carry the
API key) never reaches messages or tracebacks.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode

from turn import http_call

from .auth import authorize
from .cache import cache_key
from .context import TmdbContext
from .cooldown import retry_after_seconds
from .endpoints import Endpoint
from .errors import (
    TmdbAuthError,
    TmdbBudgetExhausted,
    TmdbError,
    TmdbHttpError,
    TmdbNetworkError,
    TmdbNotFound,
    TmdbRateLimited,
)
from .settings import HTTP_TIMEOUT_SECONDS


def urllib_transport(url: str, headers: Mapping[str, str], timeout: float) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (https only, allowlisted host)
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as exc:
        try:
            error_headers = dict(exc.headers.items()) if exc.headers else {}
        finally:
            exc.close()
        return exc.code, error_headers, b""


def _send(ctx: TmdbContext, endpoint: Endpoint) -> dict[str, Any]:
    if ctx.cooldown.active():
        raise TmdbRateLimited("TMDb rate limit: paused.")
    if not ctx.budget.try_reserve():
        raise TmdbBudgetExhausted("TMDb call limit for this turn reached.")

    params, headers = authorize(ctx.credentials, endpoint.params)
    url = f"{ctx.credentials.base_url}{endpoint.path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    ctx.recorder.record(http_call("GET", url, [ctx.credentials.secret]))

    try:
        status, response_headers, body = ctx.transport(url, headers, HTTP_TIMEOUT_SECONDS)
    except Exception:  # noqa: BLE001 - any transport failure; its message may contain the URL
        raise TmdbNetworkError("TMDb request failed (network).") from None

    if status == 429:
        ctx.cooldown.trip(retry_after_seconds(response_headers))
        raise TmdbRateLimited("TMDb rate limit reached.")
    if status == 401:
        raise TmdbAuthError("TMDb rejected the credentials.")
    if status == 404:
        raise TmdbNotFound("TMDb resource not found.")
    if status != 200:
        raise TmdbHttpError(f"TMDb answered with HTTP {int(status)}.")
    try:
        payload = json.loads(body)
    except ValueError:
        raise TmdbHttpError("TMDb answered with invalid JSON.") from None
    if not isinstance(payload, dict):
        raise TmdbHttpError("TMDb answered with an unexpected payload.")
    return payload


def get_json(ctx: TmdbContext, endpoint: Endpoint) -> dict[str, Any]:
    key = cache_key(endpoint.path, endpoint.params)
    if key in ctx.memo:
        return ctx.memo[key]
    if key in ctx.failures:
        raise ctx.failures[key]
    cached = ctx.cache.get(key)
    if cached is None:
        attempts = ctx.budget.used
        try:
            cached = _send(ctx, endpoint)
        except TmdbError as exc:
            if ctx.budget.used > attempts:  # it was sent: remember the failure
                ctx.failures[key] = exc
            raise
        ctx.cache.set(key, cached)
    ctx.memo[key] = cached
    return cached


def optional_json(ctx: TmdbContext, endpoint: Endpoint, *, skipped: list[str], label: str) -> dict[str, Any] | None:
    """Fetch data the answer can do without: skipped (and noted) when the budget is spent."""
    try:
        return get_json(ctx, endpoint)
    except TmdbBudgetExhausted:
        skipped.append(label)
    except TmdbError:
        pass
    return None
