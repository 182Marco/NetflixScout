"""Internal TVmaze settings, deliberately kept out of `CONFIG`.

The only call limit is `CONFIG["tvmaze"]["max_calls_per_turn"]`.

Documented by TVmaze (tvmaze.com/api): the API needs no key; calls are rate limited to allow at
least 20 every 10 seconds per IP address, an HTTP 429 means "back off for a few seconds"; the data
is licensed CC BY-SA and the attribution can be satisfied by linking back to TVmaze. Whether the
ShareAlike provision reaches a text generated from the data is NOT settled here (open question,
see AGENTS.md): nothing is stored beyond the memory of one turn.
"""
from __future__ import annotations

BASE_URL = "https://api.tvmaze.com"

# Wikimedia-style identification; TVmaze recommends a descriptive User-Agent.
USER_AGENT = "NetflixScout/1.0 (https://github.com/182Marco/NetflixScout; marcomilza@gmail.com) python-urllib"

HTTP_TIMEOUT_SECONDS = 8.0
# The episode list of a long series is the biggest answer; a larger body is an error, never cut JSON.
MAX_RESPONSE_BYTES = 8_000_000

# Alternatives listed when a title is ambiguous or unverified.
MAX_CANDIDATES = 5
# Rows handed to the model.
MAX_EPISODES = 60
MAX_CAST = 20
MAX_SUMMARY_CHARS = 500
# Turns whose session (budget, memo) is remembered in memory.
TURNS_REMEMBERED = 16

# Pause after an HTTP 429: Retry-After when present, clamped; otherwise the default.
RATE_LIMIT_PAUSE_DEFAULT_SECONDS = 5.0
RATE_LIMIT_PAUSE_MIN_SECONDS = 1.0
RATE_LIMIT_PAUSE_MAX_SECONDS = 60.0

LICENSE_NAME = "CC BY-SA 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"
