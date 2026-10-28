"""Scores of an OMDb record, normalised without inventing anything. Pure: no I/O.

Three sources, always all listed, each with an explicit status:
- `available`: parsed and inside the scale of the source;
- `not_available`: the field is missing, empty or `N/A` (the title has no such score);
- `unparsed`: a value is there but does not have the expected form or is out of range; it is not shown.

Nothing is averaged, converted, estimated or deduced from another source. `kind` says what the
score measures: `audience` (IMDb users) or `critics` (aggregate of professional reviews: Metacritic's
Metascore, Rotten Tomatoes' Tomatometer). Only scores: there is no review text.
"""
from __future__ import annotations

import re
from typing import Any

AVAILABLE = "available"
NOT_AVAILABLE = "not_available"
UNPARSED = "unparsed"

IMDB = "imdb"
METASCORE = "metascore"
ROTTEN_TOMATOES = "rotten_tomatoes"
SOURCES = (IMDB, METASCORE, ROTTEN_TOMATOES)

KIND = {IMDB: "audience", METASCORE: "critics", ROTTEN_TOMATOES: "critics"}
SCALE = {IMDB: "0-10", METASCORE: "0-100", ROTTEN_TOMATOES: "0-100%"}
_MAX = {IMDB: 10.0, METASCORE: 100.0, ROTTEN_TOMATOES: 100.0}
# `Source` names in the `Ratings` array.
_ARRAY_SOURCE = {
    IMDB: "Internet Movie Database",
    METASCORE: "Metacritic",
    ROTTEN_TOMATOES: "Rotten Tomatoes",
}
_NUMBER = r"(\d+(?:\.\d+)?)"
_FORMS = {
    IMDB: re.compile(rf"^{_NUMBER}(?:/10)?$"),
    METASCORE: re.compile(rf"^{_NUMBER}(?:/100)?$"),
    ROTTEN_TOMATOES: re.compile(rf"^{_NUMBER}%$"),
}
_VOTES = re.compile(r"^\d{1,3}(?:,\d{3})*$|^\d+$")


def _missing(raw: Any) -> bool:
    return raw is None or (isinstance(raw, str) and raw.strip().upper() in ("", "N/A"))


def _parse(source: str, raw: Any) -> float | None:
    match = _FORMS[source].match(raw.strip()) if isinstance(raw, str) else None
    if match is None:
        return None
    value = float(match.group(1))
    return value if 0 <= value <= _MAX[source] else None


def _array_value(record: dict[str, Any], source: str) -> Any:
    for row in record.get("Ratings") or []:
        if isinstance(row, dict) and row.get("Source") == _ARRAY_SOURCE[source]:
            return row.get("Value")
    return None


def _raw(record: dict[str, Any], source: str) -> Any:
    top = {IMDB: "imdbRating", METASCORE: "Metascore"}.get(source)
    value = record.get(top) if top else None
    # The top-level field wins; the `Ratings` array fills in when the field says nothing.
    return _array_value(record, source) if _missing(value) else value


def _votes(record: dict[str, Any]) -> int | None:
    raw = record.get("imdbVotes")
    return int(raw.replace(",", "")) if isinstance(raw, str) and _VOTES.match(raw.strip()) else None


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def display(source: str, value: float) -> str:
    """The score as it is written on its own scale: `9.3/10`, `82/100`, and `93%` for Rotten Tomatoes,
    which is a percentage and never "x/100"."""
    number = _number(value)
    return {IMDB: f"{number}/10", METASCORE: f"{number}/100", ROTTEN_TOMATOES: f"{number}%"}[source]


def extract_ratings(record: Any) -> list[dict[str, Any]]:
    """One entry per source, in a fixed order: IMDb, Metascore, Rotten Tomatoes."""
    record = record if isinstance(record, dict) else {}
    rows = []
    for source in SOURCES:
        raw = _raw(record, source)
        row: dict[str, Any] = {
            "source": source,
            "kind": KIND[source],
            "scale": SCALE[source],
            "status": NOT_AVAILABLE,
            "value": None,
        }
        if not _missing(raw):
            value = _parse(source, raw)
            row["status"] = AVAILABLE if value is not None else UNPARSED
            row["value"] = value
            if value is not None:
                row["display"] = display(source, value)
        if source == IMDB and row["status"] == AVAILABLE:
            row["votes"] = _votes(record)
        rows.append(row)
    return rows


def any_available(ratings: list[dict[str, Any]]) -> bool:
    return any(row.get("status") == AVAILABLE for row in ratings)
