"""TMDb credentials: the only module that reads the API key from the environment.

TMDb accepts the same access with a v3 API key (`api_key` query parameter) or a v4 API
Read Access Token (`Authorization: Bearer`); the mode is detected from the value.
"""
from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlsplit

from .errors import TmdbConfigError

API_KEY_ENV = "VUE_APP_TMDB_API_KEY"
BASE_URL_ENV = "VUE_APP_TMDB_BASE_URL"
DEFAULT_BASE_URL = "https://api.themoviedb.org/3"

_ALLOWED_HOST = "api.themoviedb.org"
_ALLOWED_PATH = "/3"
# v4 read access tokens are JWTs; v3 API keys are plain hex strings.
_JWT = re.compile(r"^eyJ[\w-]+\.[\w-]+\.[\w-]+$")


class AuthMode(str, Enum):
    query = "query"
    bearer = "bearer"


@dataclass(frozen=True, repr=False)
class TmdbCredentials:
    secret: str
    base_url: str
    mode: AuthMode

    def __repr__(self) -> str:
        return f"TmdbCredentials(mode={self.mode.value}, base_url={self.base_url}, secret=***)"

    __str__ = __repr__


def validate_base_url(url: str) -> str:
    """Accept only the official API host, so a tampered `.env` cannot send the key elsewhere."""
    try:
        parts = urlsplit(url.strip())
        valid = (
            parts.scheme == "https"
            and parts.hostname == _ALLOWED_HOST
            and parts.port is None
            and not parts.username
            and not parts.password
            and parts.path.rstrip("/") == _ALLOWED_PATH
            and not parts.query
            and not parts.fragment
        )
    except ValueError:
        valid = False
    if not valid:
        raise TmdbConfigError(f"{BASE_URL_ENV} must be {DEFAULT_BASE_URL}.")
    return DEFAULT_BASE_URL


def detect_mode(secret: str) -> AuthMode:
    return AuthMode.bearer if _JWT.match(secret) else AuthMode.query


def load_credentials(environ: Mapping[str, str] | None = None) -> TmdbCredentials:
    if environ is None:
        from dotenv import load_dotenv

        load_dotenv(override=False)
        environ = os.environ
    secret = (environ.get(API_KEY_ENV) or "").strip()
    if not secret:
        raise TmdbConfigError(f"TMDb API key missing: set {API_KEY_ENV} in .env.")
    base_url = validate_base_url(environ.get(BASE_URL_ENV) or DEFAULT_BASE_URL)
    return TmdbCredentials(secret=secret, base_url=base_url, mode=detect_mode(secret))


def authorize(
    credentials: TmdbCredentials,
    params: Mapping[str, str],
) -> tuple[dict[str, str], dict[str, str]]:
    """Return (query parameters, headers) with the credential added. Only `http.py` calls it."""
    query = dict(params)
    headers = {"Accept": "application/json"}
    if credentials.mode is AuthMode.bearer:
        headers["Authorization"] = f"Bearer {credentials.secret}"
    else:
        query["api_key"] = credentials.secret
    return query, headers
