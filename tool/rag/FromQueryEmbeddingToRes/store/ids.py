"""Deterministic ids and normalised fields shared by the migration and the runtime."""
from __future__ import annotations

import re
import unicodedata
import uuid

# Fixed forever: changing it would change every point id of an existing index.
NAMESPACE = uuid.UUID("6f1c2e1e-0c53-4b57-9d1a-4f5d3c1e7a10")

MIN_YEAR, MAX_YEAR = 1850, 2100


def point_uuid(legacy_id: str) -> str:
    """Qdrant accepts only integers or UUIDs: derive the UUID from the stable string id of the chunk."""
    return str(uuid.uuid5(NAMESPACE, legacy_id))


def norm_title(title: str | None) -> str:
    """Lowercase ASCII title without punctuation or leading article, for exact lookups."""
    text = unicodedata.normalize("NFKD", str(title or "")).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()
    text = re.sub(r"^(the|a|an) ", "", text)
    return re.sub(r"\s+", " ", text)


def year_int(value: str | int | None) -> int | None:
    """Explicit year conversion: only four digits in a plausible range, never guessed."""
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{4}", text):
        return None
    year = int(text)
    return year if MIN_YEAR <= year <= MAX_YEAR else None


def tmdb_legacy_id(tmdb_id: int) -> str:
    """Stable id of a catalog point; the same TMDb movie always maps to the same point."""
    return f"tmdb:movie:{int(tmdb_id)}"


def norm_name(name: str | None) -> str:
    """Person name without accents, punctuation and case, spaces collapsed (cast comparison)."""
    text = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", text.lower())).strip()
