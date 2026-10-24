"""YouTube record + reason -> video item. Title, channel and URL are the step's, unchanged
(only control characters are removed, as the presenters do)."""
from __future__ import annotations

from typing import Any

from presenters.youtube_view import printable

from ..schema.payload.item import Item
from ..schema.payload.link import Link
from .item_key import item_key

THUMBNAIL_URL = "https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def youtube_item(record: dict[str, Any], reason: str) -> Item:
    video_id = record["id"]
    return Item(
        key=item_key("youtube", "video", video_id),
        id=video_id,
        media_type="video",
        title=printable(record["title"]),
        overview=printable(record.get("description_excerpt")),
        poster_path=None,
        poster_url=THUMBNAIL_URL.format(video_id=video_id),
        youtube_key=video_id,
        channel=printable(record.get("channel")),
        published_at=printable(record.get("published_at"))[:10] or None,
        reason=reason,
        links=[Link(label="YouTube", url=printable(record["url"]))],
        attribution=record.get("attribution"),
    )
