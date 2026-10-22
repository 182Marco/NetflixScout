"""YouTube errors.

Messages are safe for the LLM prompt and the user: they never contain URLs, query
strings, credentials, the API's own `error.message` or values written by the user.
"""
from __future__ import annotations


class YoutubeError(Exception):
    code = "youtube_error"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.code)


class YoutubeConfigError(YoutubeError):
    code = "not_configured"


class YoutubeAuthError(YoutubeError):
    code = "unauthorized"


class YoutubeApiNotEnabled(YoutubeError):
    code = "api_not_enabled"


class YoutubeQuotaExceeded(YoutubeError):
    """Daily quota of the Google Cloud project spent: by this app or by any other client."""

    code = "quota_exceeded"


class YoutubeRateLimited(YoutubeError):
    code = "rate_limited"


class YoutubeTimeout(YoutubeError):
    code = "timeout"


class YoutubeNetworkError(YoutubeError):
    code = "network_error"


class YoutubeHttpError(YoutubeError):
    code = "http_error"
