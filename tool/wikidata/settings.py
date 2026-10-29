"""Internal Wikidata settings, deliberately kept out of `CONFIG`.

The only call limit is `CONFIG["wikidata"]["max_calls_per_turn"]`.

Two public endpoints, no key: the entity search of the MediaWiki API and the Wikidata Query Service
(SPARQL). The queries are constant fragments (`queries.py`); the model never writes SPARQL. The Query
Service kills a query that runs more than about a minute (seen: HTTP 504 after 65 s on a badly
written query), so the timeout here is much shorter and the requests are bound to given entities.
Wikimedia asks for a descriptive User-Agent. The data is CC0 (Wikidata:Licensing): no attribution is
required, the source is still named by the interface. Nothing is stored beyond the memory of one turn.
"""
from __future__ import annotations

SPARQL_URL = "https://query.wikidata.org/sparql"
API_URL = "https://www.wikidata.org/w/api.php"
ENTITY_URL = "https://www.wikidata.org/wiki/"

# Wikimedia policy: tool name, repository and contact.
USER_AGENT = "NetflixScout/1.0 (https://github.com/182Marco/NetflixScout; marcomilza@gmail.com) python-urllib"

HTTP_TIMEOUT_SECONDS = 15.0
MAX_RESPONSE_BYTES = 4_000_000

# Entities asked of the search, alternatives listed when a title is ambiguous or unverified.
SEARCH_LIMIT = 10
MAX_CANDIDATES = 5
# Rows a query may return (safety against a huge franchise); a full answer is reported as partial.
SPARQL_ROW_LIMIT = 500
# Franchises or series whose members are read (one request for all of them).
MAX_CONTAINERS = 2
# Works handed to the model for each group, the rest is only counted.
MAX_PER_GROUP = 12
MAX_MEMBERS = 20
MAX_DESCRIPTION_CHARS = 120
# Turns whose session (budget, memo) is remembered in memory.
TURNS_REMEMBERED = 16

# Pause after an HTTP 429: Retry-After when present, clamped; otherwise the default.
RATE_LIMIT_PAUSE_DEFAULT_SECONDS = 5.0
RATE_LIMIT_PAUSE_MIN_SECONDS = 1.0
RATE_LIMIT_PAUSE_MAX_SECONDS = 60.0

LICENSE_NAME = "CC0 1.0"
LICENSE_URL = "https://creativecommons.org/publicdomain/zero/1.0/"
