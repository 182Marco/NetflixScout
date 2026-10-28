"""OMDb errors.

Messages are safe for the LLM prompt and the user: they never contain URLs, query strings,
credentials, the API's own `Error` text or values written by the user.
"""
from __future__ import annotations


class OmdbError(Exception):
    code = "omdb_error"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.code)


class OmdbConfigError(OmdbError):
    code = "not_configured"


class OmdbAuthError(OmdbError):
    code = "unauthorized"


class OmdbQuotaExceeded(OmdbError):
    """Daily limit of the key reached: by this app or by any other client of the same key."""

    code = "quota_exceeded"


class OmdbTurnLimit(OmdbError):
    code = "turn_limit"


class OmdbTimeout(OmdbError):
    code = "timeout"


class OmdbNetworkError(OmdbError):
    code = "network_error"


class OmdbHttpError(OmdbError):
    code = "http_error"


class OmdbApiError(OmdbError):
    """The API refused the request for a reason that is neither "not found" nor a key or limit."""

    code = "api_error"


class OmdbIdMismatch(OmdbError):
    """The record returned is not the one identified: no score is attributed to it."""

    code = "id_mismatch"
