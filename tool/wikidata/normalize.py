"""SPARQL result bindings → the small dicts the decision code, the model and the presenters read. Pure: no I/O.

A work is kept only when it is a film, a series, a literary work, a comic or a video game, has a label
in English (an unlabelled item is shown by Wikidata as its own id) and is not an announced project or a
work whose earliest known date is after today. Several dates, directors or ids of one item arrive as
several rows: they are merged by item id, so an item is never listed twice.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .queries import QID
from .settings import ENTITY_URL, MAX_DESCRIPTION_CHARS, MAX_MEMBERS, MAX_PER_GROUP

KIND_RANK = {"film": 0, "series": 1, "literary": 2, "comics": 3, "game": 4}
GROUPS = ("source", "derived", "previous", "next")
_UNLABELLED = re.compile(r"^Q\d+$")
_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def entity_id(uri: Any) -> str | None:
    """`http://www.wikidata.org/entity/Q172975` → `Q172975`; anything else is None."""
    if not isinstance(uri, str):
        return None
    tail = uri.rsplit("/", 1)[-1]
    return tail if QID.match(tail) else None


def entity_url(qid: str) -> str:
    return f"{ENTITY_URL}{qid}"


def parse_date(value: Any) -> date | None:
    """The date of a Wikidata time literal; a month or day written as 00 (a year only) reads as 1."""
    match = _DATE.match(value) if isinstance(value, str) else None
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    try:
        return date(year, max(month, 1), max(day, 1))
    except ValueError:
        return None


def _text(binding: dict[str, Any], key: str) -> str | None:
    cell = binding.get(key)
    value = cell.get("value") if isinstance(cell, dict) else None
    return value if isinstance(value, str) and value else None


def _true(binding: dict[str, Any], key: str) -> bool:
    return _text(binding, key) == "true"


def _bindings(payload: Any) -> list[dict[str, Any]]:
    results = payload.get("results") if isinstance(payload, dict) else None
    rows = results.get("bindings") if isinstance(results, dict) else None
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def row_count(payload: Any) -> int:
    return len(_bindings(payload))


@dataclass
class Item:
    """One Wikidata item with everything its rows said, merged."""

    id: str
    label: str | None = None
    description: str | None = None
    flags: set[str] = field(default_factory=set)
    dates: set[date] = field(default_factory=set)
    directors: set[str] = field(default_factory=set)
    imdb: set[str] = field(default_factory=set)
    tmdb_movie: set[str] = field(default_factory=set)
    tmdb_tv: set[str] = field(default_factory=set)
    rels: set[str] = field(default_factory=set)

    @property
    def kind(self) -> str | None:
        for name in ("series", "film", "literary", "comics", "game"):
            if name in self.flags:
                return name
        return None

    @property
    def earliest(self) -> date | None:
        return min(self.dates) if self.dates else None

    @property
    def year(self) -> int | None:
        return self.earliest.year if self.earliest else None

    @property
    def labelled(self) -> bool:
        return bool(self.label) and not _UNLABELLED.match(self.label or "")

    def unreleased(self, today: date) -> bool:
        return "project" in self.flags or (self.earliest is not None and self.earliest > today)


def _read(rows: list[dict[str, Any]], subject_key: str) -> dict[str, Item]:
    items: dict[str, Item] = {}
    for row in rows:
        qid = entity_id(_text(row, subject_key))
        if qid is None:
            continue
        item = items.setdefault(qid, Item(id=qid))
        item.label = item.label or _text(row, f"{subject_key}Label")
        item.description = item.description or _text(row, f"{subject_key}Description")
        for name in ("film", "series", "project", "literary", "game", "comics"):
            if _true(row, name):
                item.flags.add(name)
        for key in ("pub", "start"):
            parsed = parse_date(_text(row, key))
            if parsed:
                item.dates.add(parsed)
        director = _text(row, "dirLabel")
        if director and not _UNLABELLED.match(director):  # a director without an English label shows as its own id
            item.directors.add(director)
        for key, target in (("imdb", item.imdb), ("tmdbMovie", item.tmdb_movie), ("tmdbTv", item.tmdb_tv)):
            value = _text(row, key)
            if value:
                target.add(value)
        rel = _text(row, "rel")
        if rel:
            item.rels.add(rel)
    return items


def parse_candidates(payload: Any) -> dict[str, Item]:
    """Items of a details query (`?w`), by id."""
    return _read(_bindings(payload), "w")


def _short(text: str | None) -> str | None:
    if not text:
        return None
    return text if len(text) <= MAX_DESCRIPTION_CHARS else text[: MAX_DESCRIPTION_CHARS - 1].rstrip() + "…"


def work_view(item: Item) -> dict[str, Any]:
    """The public form of a work: what the model and the presenters read. No ids of other services but IMDb and TMDb."""
    tmdb = sorted(item.tmdb_tv if item.kind == "series" else item.tmdb_movie)
    return {
        "id": item.id,
        "title": item.label,
        "year": item.year,
        "kind": item.kind,
        "directors": sorted(item.directors)[:2],
        "imdb_id": sorted(item.imdb)[0] if item.imdb else None,
        "tmdb_id": int(tmdb[0]) if tmdb and tmdb[0].isdigit() else None,
        "description": _short(item.description),
    }


def related_view(item: Item) -> dict[str, Any]:
    return {"id": item.id, "title": item.label, "year": item.year, "kind": item.kind, "description": _short(item.description)}


def _order(item: Item) -> tuple[int, int, str]:
    return (KIND_RANK.get(item.kind or "", 9), item.year if item.year is not None else 9999, item.label or "")


def _is_work(item: Item, today: date) -> str | None:
    """None when the item is a usable work, else why it is dropped."""
    if item.kind is None:
        return "other"
    if not item.labelled:
        return "unlabelled"
    if item.unreleased(today):
        return "unreleased"
    return None


def parse_relations(payload: Any, *, subject: str, today: date) -> dict[str, Any]:
    """Groups of works related to the subject, the franchises or series it belongs to, and what was left out."""
    items = _read(_bindings(payload), "o")
    items.pop(subject, None)
    containers = [
        {"id": item.id, "title": item.label}
        for item in sorted(items.values(), key=lambda it: it.label or "")
        if "container" in item.rels and item.labelled
    ]
    groups: dict[str, list[Item]] = {name: [] for name in GROUPS}
    dropped = {"other": 0, "unlabelled": 0, "unreleased": 0}
    for item in items.values():
        wanted = [name for name in GROUPS if name in item.rels]
        if not wanted:
            continue
        reason = _is_work(item, today)
        if reason:
            dropped[reason] += 1
            continue
        for name in wanted:
            groups[name].append(item)
    shown: dict[str, list[dict[str, Any]]] = {}
    omitted: dict[str, int] = {}
    for name, members in groups.items():
        ordered = sorted(members, key=_order)
        shown[name] = [related_view(item) for item in ordered[:MAX_PER_GROUP]]
        if len(ordered) > MAX_PER_GROUP:
            omitted[name] = len(ordered) - MAX_PER_GROUP
    return {
        "sources": shown["source"],
        "derived": shown["derived"],
        "previous": shown["previous"],
        "next": shown["next"],
        "containers": containers,
        "omitted": omitted,
        "excluded_unreleased": dropped["unreleased"],
    }


def parse_members(payload: Any, *, containers: list[dict[str, str]], today: date) -> list[dict[str, Any]]:
    """The works that declare themselves part of each container, oldest first; the rest is counted."""
    rows = _bindings(payload)
    by_container: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        container = entity_id(_text(row, "f"))
        if container is not None:
            by_container.setdefault(container, []).append(row)
    out = []
    for container in containers:
        items = _read(by_container.get(container["id"], []), "o")
        works = sorted((it for it in items.values() if _is_work(it, today) is None), key=_year_first)
        out.append(
            {
                "id": container["id"],
                "title": container["title"],
                "members": [related_view(item) for item in works[:MAX_MEMBERS]],
                "omitted": max(len(works) - MAX_MEMBERS, 0),
                "excluded_unreleased": sum(1 for it in items.values() if _is_work_kind(it) and it.unreleased(today)),
            }
        )
    return out


def _is_work_kind(item: Item) -> bool:
    return item.kind is not None and item.labelled


def _year_first(item: Item) -> tuple[int, int, str]:
    return (item.year if item.year is not None else 9999, KIND_RANK.get(item.kind or "", 9), item.label or "")
