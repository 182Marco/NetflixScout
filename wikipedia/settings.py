"""Internal Wikipedia settings, deliberately kept out of `CONFIG`.

None of these is a call limit: the only one is `CONFIG["wikipedia"]["max_calls_per_turn"]`.
The sizes below protect memory and time; none of them caps how much of an article the
orchestrator can ask for (that is `context_chars_per_turn`, in `CONFIG`).

Wikimedia policy (mediawiki.org/wiki/API:Etiquette): a descriptive User-Agent with a contact
is required, reads are made in series, `maxlag` is sent by non-interactive clients. Text is
CC BY-SA 4.0: the presenters credit the pages and link the licence.
"""
from __future__ import annotations

# Hosts are chosen from this table, never from the model's input. The edition searched when the
# planner names none is `CONFIG["wikipedia"]["default_language"]`.
LANGUAGES = ("it", "en")
HOST = "{language}.wikipedia.org"
API_PATH = "/w/api.php"
PAGE_PATH = "/wiki/"

# `client/version (contact) framework`. Contact: the repository and the author's address.
USER_AGENT = "NetflixScout/1.0 (https://github.com/182Marco/NetflixScout; marcomilza@gmail.com) python-urllib"

# A search asks for more pages than it will show (`max_results * factor`, at most the max): pages
# that turn out unrelated are dropped after the search, and must not take the places of the others.
SEARCH_FETCH_FACTOR = 2
SEARCH_FETCH_MAX = 10

HTTP_TIMEOUT_SECONDS = 10.0
# Replication lag (seconds) above which the server asks clients to wait.
MAXLAG_SECONDS = 5
# Largest answer read (an article as plain text is far smaller); bigger = error, never cut JSON.
MAX_RESPONSE_BYTES = 4_000_000
CACHE_MAX_ENTRIES = 64
# Pause after a rate limit or lag error: `Retry-After` when sent, else the default, never above the max.
RATE_LIMIT_PAUSE_SECONDS = 5.0
RATE_LIMIT_PAUSE_MAX_SECONDS = 60.0
# Turns remembered at the same time (budget and sections delivered), oldest forgotten first.
MAX_TURN_STATES = 64

# Context left below which a further step is not offered (not enough room for a section).
MIN_FOLLOW_UP_CHARS = 1_000
# Sections listed in the outline given to the planner and in the metadata.
MAX_OUTLINE_SECTIONS = 40
# Characters of the planner summary (the orchestrator shows the planner at most 2,500 per step).
PLANNER_SUMMARY_CHARS = 1_800

LICENSE_NAME = "CC BY-SA 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"

# Sections that are lists, links or notes, not prose: never delivered unless asked by name.
NON_PROSE_SECTIONS = frozenset(
    {
        "note", "bibliografia", "collegamenti esterni", "voci correlate", "altri progetti",
        "riferimenti", "fonti", "annotazioni", "approfondimenti",
        "references", "external links", "see also", "further reading", "notes", "sources",
        "footnotes", "citations", "bibliography",
    }
)
