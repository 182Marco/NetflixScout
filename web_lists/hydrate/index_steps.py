"""Steps -> {item key: record} of what the tools returned in this turn.

TMDb records come from `tmdb_calls.data.items`; YouTube records from `youtube_calls.data.videos`
(the id is the one in the validated watch URL). Anything malformed is skipped. A record has
`source`, `media_type`, `id`, `title` plus the fields of its source and the `attribution` to show.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit

from turn import STEP_TMDB_CALLS, STEP_YOUTUBE_CALLS, TraceStep

from .item_key import item_key

TMDB_ATTRIBUTIONS = {"justwatch": "JustWatch"}
YOUTUBE_ATTRIBUTION = "YouTube"


def _rows(raw: Any) -> list[dict[str, Any]]:
    return [row for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []


def _tmdb_attribution(data: dict[str, Any]) -> str | None:
    names = [TMDB_ATTRIBUTIONS[key] for key in data.get("attributions") or [] if key in TMDB_ATTRIBUTIONS]
    return names[0] if names else None


def _tmdb_records(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    attribution = _tmdb_attribution(data)
    records = {}
    for row in _rows(data.get("items")):
        valid = isinstance(row.get("id"), int) and row.get("media_type") in ("movie", "tv")
        if valid and isinstance(row.get("title"), str):
            records[item_key("tmdb", row["media_type"], row["id"])] = {
                **row,
                "source": "tmdb",
                "attribution": attribution,
            }
    return records


def _video_id(url: Any) -> str | None:
    if not isinstance(url, str) or not url.startswith("https://"):
        return None
    ids = parse_qs(urlsplit(url).query).get("v")
    return ids[0] if ids else None


def _youtube_records(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records = {}
    for row in _rows(data.get("videos")):
        video_id = _video_id(row.get("url"))
        if video_id and isinstance(row.get("title"), str):
            records[item_key("youtube", "video", video_id)] = {
                **row,
                "source": "youtube",
                "media_type": "video",
                "id": video_id,
                "attribution": YOUTUBE_ATTRIBUTION,
            }
    return records


def index_steps(steps: list[TraceStep]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for step in steps:
        if step.kind == STEP_TMDB_CALLS:
            index.update({k: v for k, v in _tmdb_records(step.data).items() if k not in index})
        elif step.kind == STEP_YOUTUBE_CALLS:
            index.update({k: v for k, v in _youtube_records(step.data).items() if k not in index})
    return index
