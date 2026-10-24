"""TMDb record + reason -> item with the shape of the front's Card (as TMDb returns it)."""
from __future__ import annotations

from typing import Any

from ..schema.payload.item import Item
from ..schema.payload.link import Link
from .item_key import item_key

TMDB_WEB_URL = "https://www.themoviedb.org"


def tmdb_item(record: dict[str, Any], reason: str) -> Item:
    media_type, ident = record["media_type"], record["id"]
    # Series carry `name` instead of `title`; `release_date` holds the first air date.
    name_field = {"title": record["title"]} if media_type == "movie" else {"name": record["title"]}
    return Item(
        key=item_key("tmdb", media_type, ident),
        id=ident,
        media_type=media_type,
        **name_field,
        overview=record.get("overview"),
        vote_average=record.get("vote_average"),
        release_date=record.get("release_date"),
        original_language=record.get("original_language"),
        poster_path=record.get("poster_path"),
        reason=reason,
        youtube_key=None,
        links=[Link(label="TMDb", url=f"{TMDB_WEB_URL}/{media_type}/{ident}")],
        attribution=record.get("attribution"),
    )
