"""Format rules for the identifiers of a work or person, and the correction of the ones that break them (FASE 21).

A value that does not have the shape of its scheme is not an identifier of that scheme: `nm1627110` (an IMDb PERSON id) was stored as the IMDb TITLE id of the series
*Tumbling* because the Wikidata property it came from held a name id. Rules:
- the shape is checked per scheme (`PATTERNS`); schemes without a pattern (page titles, EIDR) are not checked;
- a value with the wrong shape is never kept as an identifier. If `id_overrides.json` has a verified correction for exactly that source record it is applied, otherwise the
  identifier stays absent; the rejected value is kept as an `entity_claim` (field `<scheme>_rejected`) so nothing is lost silently.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

OVERRIDES_PATH = Path(__file__).with_name("id_overrides.json")

PATTERNS: dict[str, re.Pattern[str]] = {
    "imdb_title": re.compile(r"^tt\d{7,9}$"),
    "imdb_name": re.compile(r"^nm\d{7,9}$"),
    "wikidata": re.compile(r"^Q[1-9]\d*$"),
    "tmdb_movie": re.compile(r"^[1-9]\d*$"),
    "tmdb_tv": re.compile(r"^[1-9]\d*$"),
    "tmdb_person": re.compile(r"^[1-9]\d*$"),
    "tvdb_series": re.compile(r"^[1-9]\d*$"),
    "tvmaze_show": re.compile(r"^[1-9]\d*$"),
}


def has_valid_shape(scheme: str, value: str) -> bool:
    pattern = PATTERNS.get(scheme)
    return True if pattern is None else bool(pattern.match(str(value)))


def violations(conn: sqlite3.Connection) -> list[tuple[int, str, str]]:
    """(entity_id, scheme, value) of every stored identifier whose shape is wrong, in a stable order."""
    out = [(e, s, v) for e, s, v in conn.execute("SELECT entity_id, scheme, value FROM external_id ORDER BY scheme, entity_id, value") if not has_valid_shape(s, v)]
    return out


def load_overrides(path: Path | None = None) -> dict[tuple[str, str, str], dict[str, Any]]:
    """Verified corrections keyed by (scheme, rejected value, source_ref of the record that supplied it). Every entry must say what it replaces, with which value or `drop`,
    and the evidence; a malformed file is an error (a correction nobody can audit is not applied)."""
    data = json.loads((path or OVERRIDES_PATH).read_text(encoding="utf-8"))
    out: dict[tuple[str, str, str], dict[str, Any]] = {}
    for entry in data.get("overrides", []):
        for key in ("id", "scheme", "rejected", "source_ref", "action", "evidence"):
            if not entry.get(key):
                raise ValueError(f"id override {entry.get('id')!r} lacks {key!r}")
        if entry["action"] not in ("replace", "drop"):
            raise ValueError(f"id override {entry['id']!r}: action must be replace or drop")
        if entry["action"] == "replace":
            if not entry.get("value") or not has_valid_shape(entry["scheme"], entry["value"]):
                raise ValueError(f"id override {entry['id']!r}: the replacement must be a valid {entry['scheme']}")
        key = (entry["scheme"], entry["rejected"], entry["source_ref"])
        if key in out:
            raise ValueError(f"duplicate id override for {key}")
        out[key] = entry
    return out
