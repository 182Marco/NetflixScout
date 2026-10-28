"""Reading the envelope of an OMDb answer. Pure.

OMDb answers `{"Response": "True", ...}` or `{"Response": "False", "Error": "..."}`. The `Error`
text is never shown or stored: it is only matched against fixed fragments to tell a missing title
from other refusals; an unknown text is `error`, never "not found".

Observed live (2026-10-28, `harness/live_smoke.py`): an unknown IMDb ID answers HTTP 200 with
"Error getting data.". The other fragments ("Movie not found!", "Too many results.", the request
limit and key messages) are NOT observed: they follow the usual OMDb texts and, if the real text
differs, the answer falls into `error` (an explicit failure), not into a wrong score.
"""
from __future__ import annotations

from typing import Any

OK = "ok"
NOT_FOUND = "not_found"
TOO_MANY = "too_many"
QUOTA = "quota"
KEY = "key"
ERROR = "error"

_NOT_FOUND = ("not found", "incorrect imdb id", "error getting data")
_TOO_MANY = ("too many results",)
_QUOTA = ("limit reached", "request limit")
_KEY = ("invalid api key", "no api key")


def response_kind(payload: Any) -> str:
    """`ok` | `not_found` | `too_many` | `quota` | `key` | `error` for a decoded answer."""
    if not isinstance(payload, dict):
        return ERROR
    flag = payload.get("Response")
    if flag is True or (isinstance(flag, str) and flag.lower() == "true"):
        return OK
    text = payload.get("Error")
    text = text.lower() if isinstance(text, str) else ""
    for kind, fragments in ((QUOTA, _QUOTA), (KEY, _KEY), (TOO_MANY, _TOO_MANY), (NOT_FOUND, _NOT_FOUND)):
        if any(fragment in text for fragment in fragments):
            return kind
    return ERROR
