"""TVmaze errors.

Messages are safe for the LLM prompt and the user: they never contain URLs, query strings or
values written by the user.
"""
from __future__ import annotations


class TvmazeError(Exception):
    code = "tvmaze_error"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.code)


class TvmazeRateLimited(TvmazeError):
    """HTTP 429, or the pause that follows it is still active: nothing is sent."""

    code = "rate_limited"


class TvmazeTurnLimit(TvmazeError):
    code = "turn_limit"


class TvmazeTimeout(TvmazeError):
    code = "timeout"


class TvmazeNetworkError(TvmazeError):
    code = "network_error"


class TvmazeHttpError(TvmazeError):
    code = "http_error"


class TvmazeResponseTooLarge(TvmazeError):
    code = "response_too_large"
