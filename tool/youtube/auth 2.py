"""YouTube credentials: the only module that reads the API key from the environment.

The YouTube Data API v3 takes a plain API key in the `key` query parameter. The base URL is
the constant `settings.BASE_URL`, never read from the environment, so the key cannot be
sent to another host.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from dotenv import load_dotenv

from .errors import YoutubeConfigError

API_KEY_ENV = "YOUTUBE_API_KEY"


@dataclass(frozen=True, repr=False)
class YoutubeCredentials:
    secret: str

    def __repr__(self) -> str:
        return "YoutubeCredentials(secret=***)"

    __str__ = __repr__


def load_credentials(environ: Mapping[str, str] | None = None) -> YoutubeCredentials:
    """Read the key from `environ`, or from the process environment completed by `.env`.

    `load_dotenv(override=False)`: a variable already set in the environment wins over `.env`.
    """
    if environ is None:
        load_dotenv(override=False)
        environ = os.environ
    secret = (environ.get(API_KEY_ENV) or "").strip()
    if not secret:
        raise YoutubeConfigError(f"YouTube API key missing: set {API_KEY_ENV} in .env.")
    return YoutubeCredentials(secret=secret)


def authorize(
    credentials: YoutubeCredentials,
    params: Mapping[str, str],
) -> tuple[dict[str, str], dict[str, str]]:
    """Return (query parameters, headers) with the key added. Only `http.py` calls it."""
    query = dict(params)
    query["key"] = credentials.secret
    return query, {"Accept": "application/json"}
