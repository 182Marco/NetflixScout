from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from .item import Item


class WebList(BaseModel):
    list_id: str
    title: str
    kind: Literal["movies", "series", "videos", "mixed"]
    items: list[Item]
