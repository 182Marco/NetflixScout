"""Offline helpers for the YouTube tests: a fake transport that records calls, fake
credentials and Google-shaped error bodies. Nothing here reads `.env` or touches the network."""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from youtube.auth import YoutubeCredentials
from youtube.http import HttpSession
from youtube.quota import QuotaLatch

SECRET = "AIzaSyFAKE-test-key-0123456789abcdefghi"
BASE = "https://www.googleapis.com/youtube/v3"

Route = dict[str, Any] | tuple[int, dict[str, str], Any] | Exception | Callable[[dict[str, str]], Any]


class FakeTransport:
    """Routes by path (without `/youtube/v3`); unknown paths answer 404. Records every call."""

    def __init__(self, routes: dict[str, Route] | None = None) -> None:
        self.routes: dict[str, Route] = dict(routes or {})
        self.calls: list[tuple[str, dict[str, str], dict[str, str], str]] = []

    def __call__(self, url: str, headers: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
        parts = urlsplit(url)
        path = parts.path.removeprefix("/youtube/v3")
        params = dict(parse_qsl(parts.query))
        self.calls.append((path, params, dict(headers), url))
        route = self.routes.get(path)
        if callable(route) and not isinstance(route, Exception):
            route = route(params)
        if route is None:
            return 404, {}, b""
        if isinstance(route, Exception):
            raise route
        if isinstance(route, tuple):
            status, response_headers, body = route
            return status, response_headers, body if isinstance(body, bytes) else json.dumps(body).encode()
        return 200, {}, json.dumps(route).encode()

    @property
    def paths(self) -> list[str]:
        return [call[0] for call in self.calls]


def credentials() -> YoutubeCredentials:
    return YoutubeCredentials(secret=SECRET)


def make_session(
    routes: dict[str, Route] | None = None,
    *,
    latch: QuotaLatch | None = None,
) -> tuple[HttpSession, FakeTransport]:
    transport = FakeTransport(routes)
    session = HttpSession(credentials=credentials(), transport=transport, latch=latch or QuotaLatch())
    return session, transport


def error_body(
    status: int,
    reason: str | None = None,
    *,
    message: str = "Error message from Google.",
    details_reason: str | None = None,
) -> tuple[int, dict[str, str], dict[str, Any]]:
    """A Google API error answer: `error.errors[0].reason` and/or `error.details[].reason`."""
    error: dict[str, Any] = {"code": status, "message": message}
    if reason:
        error["errors"] = [{"message": message, "domain": "youtube.quota", "reason": reason}]
    if details_reason:
        error["details"] = [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": details_reason}]
    return status, {}, {"error": error}
