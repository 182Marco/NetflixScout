from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from .public import field_definitions


@dataclass(frozen=True)
class Preferences:
    """One valid value per field id of `fields.json` (booleans for `boolean`, strings for `choice`)."""

    values: Mapping[str, Any]

    def __getitem__(self, field_id: str) -> Any:
        return self.values[field_id]

    def __iter__(self) -> Iterator[str]:
        return iter(self.values)

    def as_dict(self) -> dict[str, Any]:
        return dict(self.values)


def defaults() -> Preferences:
    return Preferences({field["id"]: field["default"] for field in field_definitions()})
