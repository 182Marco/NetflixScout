"""The HTTP calls of a tool step, as every channel shows them: method and the full URL.

One place for all tools (`tmdb_calls`, `youtube_calls`, `wikipedia_calls`, `omdb_calls`, `tvmaze_calls`): each tool
records `{"method", "url"}` (`turn.http_call`) where it builds the URL it sends, and the views turn
that into `CallView`s. The URL is the one actually called, query included; only the value of a
credential is `***`. `mask_url` runs here once more (it is idempotent) so that a step built by a tool
that forgot to mask still cannot show a key. Imports nothing but `turn` and pydantic.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from turn import mask_url

_WHITESPACE_CONTROLS = {"\t", "\n", "\r", "\x0b", "\x0c", "\x85"}


def _printable(text: str) -> str:
    out = []
    for char in text:
        code = ord(char)
        if code < 0x20 or code == 0x7F or 0x80 <= code <= 0x9F:
            if char in _WHITESPACE_CONTROLS:
                out.append(" ")
            continue
        out.append(char)
    return "".join(out)


class CallView(BaseModel):
    method: str
    url: str

    def text(self) -> str:
        return f"{self.method} {self.url}" if self.method else self.url


def call_views(raw: Any) -> list[CallView]:
    """Every recorded call, in the order made. Only https URLs are shown (a plain URL string, the
    form older steps had, is accepted without a method: it is never given one)."""
    if not isinstance(raw, list):
        return []
    views = []
    for item in raw:
        method, url = ("", item) if isinstance(item, str) else (item.get("method"), item.get("url")) if isinstance(item, dict) else ("", None)
        if not isinstance(url, str) or not url.startswith("https://"):
            continue
        views.append(CallView(method=_printable(method) if isinstance(method, str) else "", url=_printable(mask_url(url))))
    return views
