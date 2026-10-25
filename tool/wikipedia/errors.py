"""Wikipedia errors.

Messages are safe for the LLM prompt and the user: they never contain URLs, query strings,
the User-Agent, the API's own error text or values written by the user.
"""
from __future__ import annotations


class WikipediaError(Exception):
    code = "wikipedia_error"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.code)


class WikipediaRateLimited(WikipediaError):
    """HTTP 429, `ratelimited`, or `maxlag` (which the API answers with HTTP 200)."""

    code = "rate_limited"


class WikipediaTimeout(WikipediaError):
    code = "timeout"


class WikipediaNetworkError(WikipediaError):
    code = "network_error"


class WikipediaHttpError(WikipediaError):
    code = "http_error"


class WikipediaResponseTooLarge(WikipediaError):
    code = "response_too_large"


class WikipediaBudgetExhausted(WikipediaError):
    """The turn's HTTP call limit was reached (nothing was sent)."""

    code = "turn_limit"
