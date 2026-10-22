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
# IDs per `/videos` call (API maximum): one call per run, the rest keeps search data only.
VIDEO_IDS_MAX = 50
# Description excerpt passed to the LLM (the full description is never needed).
DESCRIPTION_EXCERPT_CHARS = 300
# Country named in the `blocked_in:<code>` note from `regionRestriction`: a note only,
# no search is restricted by country.
NOTE_REGION = "IT"

# The API has no "is a Short" field and duration alone does not identify one (Shorts last
# up to 3 minutes; teasers and short interviews can last under a minute). Duration never
# drops a video: under MIN_DURATION_SECONDS it only gets the note `very_short`. A video is
# dropped as a Short only when it declares itself one (#shorts) and is not longer than
# SHORTS_MAX_SECONDS, and never for trailers (see `relevance.py`).
MIN_DURATION_SECONDS = 60
SHORTS_MAX_SECONDS = 180

# Daily quotas reset at midnight Pacific Time (developers.google.com/youtube/v3/determine_quota_cost).
QUOTA_TIMEZONE = "America/Los_Angeles"
# Pause after `rateLimitExceeded` / HTTP 429: per-second limits, not the daily quota.
RATE_LIMIT_PAUSE_SECONDS = 10.0
