"""A hydrated item. Only the fields that apply are set (movie: `title`; series: `name`;
video: `poster_url`, `channel`), so the payload is built with `exclude_unset`."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .link import Link


class Item(BaseModel):
    key: str
    id: int | str
    media_type: Literal["movie", "tv", "video"]
    title: str | None = None
    name: str | None = None
    overview: str | None = None
    vote_average: float | None = None
    release_date: str | None = None
    original_language: str | None = None
    poster_path: str | None = None
    poster_url: str | None = None
    youtube_key: str | None = None
    channel: str | None = None
    published_at: str | None = None
    reason: str
    links: list[Link]
    attribution: str | None = None
