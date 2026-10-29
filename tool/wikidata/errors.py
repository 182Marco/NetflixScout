"""Wikidata errors.

Messages are safe for the LLM prompt and the user: they never contain URLs, query strings (the
SPARQL text included) or values written by the user.
"""
from __future__ import annotations


class WikidataError(Exception):
    code = "wikidata_error"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.code)


class WikidataRateLimited(WikidataError):
    """HTTP 429, or the pause that follows it is still active: nothing is sent."""

    code = "rate_limited"


class WikidataTurnLimit(WikidataError):
    code = "turn_limit"


class WikidataTimeout(WikidataError):
    code = "timeout"


class WikidataNetworkError(WikidataError):
    code = "network_error"


class WikidataHttpError(WikidataError):
    code = "http_error"


class WikidataResponseTooLarge(WikidataError):
    code = "response_too_large"
