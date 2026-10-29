"""TVmaze JSON → the small dicts handed to the model and the presenters. Pure: no I/O.

Fields are copied as TVmaze gives them (names, dates, numbers); nothing is estimated. The HTML of
the summary is reduced to text. Episode summaries are not read (spoilers), images are not used.
"""
from __future__ import annotations

import html
import re
from typing import Any

from .settings import MAX_CAST, MAX_EPISODES, MAX_SUMMARY_CHARS

_TAGS = re.compile(r"<[^>]+>")


def _text(value: Any) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _number(value: Any) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def plain_text(value: Any, limit: int = MAX_SUMMARY_CHARS) -> str | None:
    text = _text(value)
    if text is None:
        return None
    text = " ".join(html.unescape(_TAGS.sub(" ", text)).split())
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _name(value: Any) -> str | None:
    return _text(value.get("name")) if isinstance(value, dict) else None


def show_info(show: dict[str, Any]) -> dict[str, Any]:
    network, web = show.get("network"), show.get("webChannel")
    externals = show.get("externals") if isinstance(show.get("externals"), dict) else {}
    runtime = _number(show.get("runtime")) or _number(show.get("averageRuntime"))
    return {
        "name": _text(show.get("name")),
        "type": _text(show.get("type")),
        "language": _text(show.get("language")),
        "genres": [g for g in show.get("genres", []) if isinstance(g, str)] if isinstance(show.get("genres"), list) else [],
        "status": _text(show.get("status")),
        "premiered": _text(show.get("premiered")),
        "ended": _text(show.get("ended")),
        "runtime_minutes": runtime,
        "network": _name(network),
        "network_country": _name(network.get("country")) if isinstance(network, dict) else None,
        "web_channel": _name(web),
        "imdb_id": _text(externals.get("imdb")),
        "summary": plain_text(show.get("summary")),
    }


def show_url(show: dict[str, Any]) -> str | None:
    """Public page of the series, only if it is on tvmaze.com (it is shown as the source link)."""
    url = _text(show.get("url"))
    return url if url and url.startswith("https://www.tvmaze.com/") else None


def cast_rows(embedded: Any) -> list[dict[str, str | None]]:
    rows = []
    for row in embedded if isinstance(embedded, list) else []:
        if not isinstance(row, dict):
            continue
        person, character = _name(row.get("person")), _name(row.get("character"))
        if person:
            rows.append({"person": person, "character": character})
    return rows[:MAX_CAST]


def season_rows(payload: Any) -> list[dict[str, Any]]:
    rows = []
    for row in payload if isinstance(payload, list) else []:
        if isinstance(row, dict) and isinstance(row.get("number"), int):
            rows.append(
                {
                    "season": row["number"],
                    "episodes": _number(row.get("episodeOrder")),
                    "premiered": _text(row.get("premiereDate")),
                    "ended": _text(row.get("endDate")),
                }
            )
    return rows


def episode_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "season": row.get("season") if isinstance(row.get("season"), int) else None,
        "number": row.get("number") if isinstance(row.get("number"), int) else None,
        "name": _text(row.get("name")),
        "airdate": _text(row.get("airdate")),
        "airstamp": _text(row.get("airstamp")),
        "runtime_minutes": _number(row.get("runtime")),
        "type": _text(row.get("type")),
    }


def episode_rows(payload: Any, *, season: int, episode: int | None) -> tuple[list[dict[str, Any]], int]:
    """Episodes of one season (optionally one episode) and how many the season has before the cut."""
    rows = []
    for row in payload if isinstance(payload, list) else []:
        if isinstance(row, dict) and row.get("season") == season:
            rows.append(episode_row(row))
    if episode is not None:
        rows = [row for row in rows if row["number"] == episode]
    return rows[:MAX_EPISODES], len(rows)


def next_episode_row(embedded: Any) -> dict[str, Any] | None:
    return episode_row(embedded) if isinstance(embedded, dict) else None
