"""Root of the strict schema of the list call."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator

from .list_ref import ListRef

MAX_LISTS = 4


class ListsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lists: list[ListRef]

    @field_validator("lists", mode="before")
    @classmethod
    def _cap(cls, value: object) -> object:
        return value[:MAX_LISTS] if isinstance(value, list) else value
