"""Internal TMDb settings, deliberately kept out of `CONFIG`.

None of these limits HTTP calls: the only call limit is
`CONFIG["tmdb"]["max_calls_per_turn"]`, enforced by `tool/tmdb/budget.py`.
"""
from __future__ import annotations

HTTP_TIMEOUT_SECONDS = 8.0
CACHE_MAX_ENTRIES = 256

# After a 429 no request is sent until the pause expires (Retry-After, clamped).
RATE_LIMIT_COOLDOWN_SECONDS = 10.0
RATE_LIMIT_COOLDOWN_MAX_SECONDS = 120.0

# Country used for streaming providers, release dates and certifications when the
# request does not name one.
DEFAULT_REGION = "IT"

# Documented image base URL (https://developer.themoviedb.org/docs/image-basics):
# a constant instead of a `/configuration` call.
IMAGE_BASE_URL = "https://image.tmdb.org/t/p/"
IMAGE_SIZE = "w500"
TMDB_WEB_URL = "https://www.themoviedb.org"

# Turn language (from the classifier) → TMDb `language` parameter.
API_LANGUAGES = {"it": "it-IT", "en": "en-US", "de": "de-DE"}
DEFAULT_API_LANGUAGE = "en-US"
# Genre and provider names are matched in English, whatever the turn language.
REFERENCE_LANGUAGE = "en-US"
