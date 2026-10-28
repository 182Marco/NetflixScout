"""OMDb credentials: the only module that reads the API key from the environment.

OMDb takes the key in the `apikey` query parameter. The base URL is the constant
`settings.BASE_URL`, never read from the environment, so the key cannot be sent to another host.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from dotenv import load_dotenv

from .errors import OmdbConfigError

API_KEY_ENV = "OMDB_API_KEY"


@dataclass(frozen=True, repr=False)
class OmdbCredentials:
    secret: str

    def __repr__(self) -> str:
        return "OmdbCredentials(secret=***)"

    __str__ = __repr__


def load_credentials(environ: Mapping[str, str] | None = None) -> OmdbCredentials:
    """Read the key from `environ`, or from the process environment completed by `.env`.

    `load_dotenv(override=False)`: a variable already set in the environment wins over `.env`.
    """
    if environ is None:
        load_dotenv(override=False)
        environ = os.environ
    secret = (environ.get(API_KEY_ENV) or "").strip()
    if not secret:
        raise OmdbConfigError(f"OMDb API key missing: set {API_KEY_ENV} in .env.")
    return OmdbCredentials(secret=secret)


def authorize(
    credentials: OmdbCredentials,
    params: Mapping[str, str],
) -> tuple[dict[str, str], dict[str, str]]:
    """Return (query parameters, headers) with the key added. Only `http.py` calls it."""
    query = dict(params)
    query["apikey"] = credentials.secret
    return query, {"Accept": "application/json"}
