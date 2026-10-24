"""Stable key of an item, used by the front to dedupe: `tmdb:movie:157336`, `youtube:video:<id>`."""
from __future__ import annotations

from ..schema.llm.list_ref import ItemRef


def item_key(source: str, media_type: str, ident: int | str) -> str:
    return f"{source}:{media_type}:{ident}"


def ref_key(ref: ItemRef) -> str:
    if ref.source == "youtube":
        return item_key("youtube", "video", ref.video_id)
    return item_key("tmdb", ref.media_type, ref.id)
