"""The public definition of the settings: exactly `fields.json`, nothing private."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

FIELDS_PATH = Path(__file__).with_name("fields.json")


@lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    return json.loads(FIELDS_PATH.read_text(encoding="utf-8"))


def public_schema() -> dict[str, Any]:
    """A fresh copy of the schema the client receives (the caller may not change the cached one)."""
    return json.loads(json.dumps(_load()))


def field_definitions() -> list[dict[str, Any]]:
    return _load()["fields"]
