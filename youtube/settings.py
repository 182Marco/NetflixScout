"""Internal YouTube settings, deliberately kept out of `CONFIG`.

None of these is a call limit: the only one is `CONFIG["you_tube"]["max_searches_per_turn"]`.
No `regionCode` or `relevanceLanguage` is sent: international interviews in English must
not be filtered out by country or pushed down by language.
"""
from __future__ import annotations

BASE_URL = "https://www.googleapis.com/youtube/v3"
# The API returns video IDs, not URLs: the only URL built by the tool.
WATCH_URL = "https://www.youtube.com/watch?v={}"

HTTP_TIMEOUT_SECONDS = 8.0

# Search results fetched per kind, before the relevance filter: max_results * factor, capped
# by the API maximum.
SEARCH_FETCH_FACTOR = 3
SEARCH_FETCH_MAX = 50

# Below this duration a video is a Short: dropped for every kind except trailers (teasers).
MIN_DURATION_SECONDS = 60

# Daily quotas reset at midnight Pacific Time (developers.google.com/youtube/v3/determine_quota_cost).
QUOTA_TIMEZONE = "America/Los_Angeles"
# Pause after `rateLimitExceeded` / HTTP 429: per-second limits, not the daily quota.
RATE_LIMIT_PAUSE_SECONDS = 10.0
