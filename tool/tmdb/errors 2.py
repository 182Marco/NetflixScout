"""TMDb errors.

Messages are safe for the LLM prompt and the user: they never contain URLs, query
strings, credentials or values written by the user.
"""
from __future__ import annotations


class TmdbError(Exception):
    code = "tmdb_error"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.code)


class TmdbConfigError(TmdbError):
    code = "not_configured"


class TmdbBudgetExhausted(TmdbError):
    code = "call_limit_reached"


class TmdbRateLimited(TmdbError):
    code = "rate_limited"


class TmdbAuthError(TmdbError):
    code = "unauthorized"


class TmdbNotFound(TmdbError):
    code = "not_found"


class TmdbHttpError(TmdbError):
    code = "http_error"


class TmdbNetworkError(TmdbError):
    code = "network_error"


class TmdbUnresolvedFilter(TmdbError):
    code = "unresolved_filter"


class TmdbUnverifiedMatch(TmdbNotFound):
    """Search results exist but none is verifiably the requested movie or series.

    `reason` is `title_mismatch`, `year_mismatch` or `ambiguous`; `candidates` are the
    closest results (ID, title, year), reported as unverified alternatives only.
    """

    code = "unverified_match"

    def __init__(self, reason: str, candidates: tuple[dict, ...] = ()) -> None:
        super().__init__(f"No verified match ({reason}).")
        self.reason = reason
        self.candidates = candidates
