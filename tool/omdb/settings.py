"""Internal OMDb settings, deliberately kept out of `CONFIG`.

The only call limit is `CONFIG["omdb"]["max_calls_per_turn"]`. The free key of OMDb allows
1,000 requests a day (omdbapi.com/apikey.aspx); the API answer is the only authority on it, so
nothing here counts the day's requests.

Terms of use (omdbapi.com, legal page): personal use only and no commercial endeavours; no
copies, indexes or redistribution of the data. Hence no cache outside one turn and nothing
written to disk.
"""
from __future__ import annotations

# The key is sent only to this host: the constant is never read from the environment.
BASE_URL = "https://www.omdbapi.com/"

HTTP_TIMEOUT_SECONDS = 8.0

# Alternatives listed when a title is ambiguous or unverified.
MAX_CANDIDATES = 5
# Turns whose answers are remembered in memory (the memo of one turn is dropped after that).
TURNS_REMEMBERED = 16
