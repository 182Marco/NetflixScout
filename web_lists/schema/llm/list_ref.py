"""What the model emits: references only, never posters, votes or plots."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

MAX_REASON_CHARS = 140
MAX_ITEMS = 12


class TmdbRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["tmdb"]
    media_type: Literal["movie", "tv"]
    id: int
    quote: str
    reason: str

    @field_validator("reason", mode="before")
    @classmethod
    def _cut(cls, value: object) -> object:
        return value[:MAX_REASON_CHARS] if isinstance(value, str) else value


class YoutubeRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["youtube"]
    video_id: str
    quote: str
    reason: str

    @field_validator("reason", mode="before")
    @classmethod
    def _cut(cls, value: object) -> object:
        return value[:MAX_REASON_CHARS] if isinstance(value, str) else value


ItemRef = TmdbRef | YoutubeRef


class ListRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    list_id: str
    title: str
    kind: Literal["movies", "series", "videos", "mixed"]
    items: list[ItemRef]

    @field_validator("list_id", mode="before")
    @classmethod
    def _slug(cls, value: object) -> object:
        return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") if isinstance(value, str) else value

    @field_validator("items", mode="before")
    @classmethod
    def _cap(cls, value: object) -> object:
        return value[:MAX_ITEMS] if isinstance(value, list) else value
