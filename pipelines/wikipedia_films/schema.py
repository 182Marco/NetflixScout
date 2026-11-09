"""Explicit schema of a film record in films.jsonl (validated before writing)."""
from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

QID_RE = re.compile(r"^Q[1-9]\d*$")
IMDB_RE = re.compile(r"^tt\d{7,9}$")
ISO_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
FALLBACK_ID_RE = re.compile(r"^wp-\d+$")
MIN_YEAR, MAX_YEAR = 1850, 2100
MIN_DURATION, MAX_DURATION = 1, 2000


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Person(_Strict):
    name: str
    wikidata_id: str | None = None

    @field_validator("wikidata_id")
    @classmethod
    def _qid(cls, value: str | None) -> str | None:
        if value is not None and not QID_RE.match(value):
            raise ValueError(f"invalid QID: {value!r}")
        return value


class Actor(Person):
    character: str | None = None


class FilmRecord(_Strict):
    film_id: str
    wikidata_id: str | None
    wikipedia_page_id: int
    title: str
    original_title: str | None
    year: int | None
    director: list[Person]
    duration_minutes: int | None
    actors: list[Actor]
    genres: list[str]
    country: list[str]
    language: list[str]
    synopsis: str
    imdb_id: str | None
    wikipedia_url: str
    source_revision_id: str
    retrieved_at: str

    @field_validator("film_id")
    @classmethod
    def _film_id(cls, value: str) -> str:
        if not (QID_RE.match(value) or FALLBACK_ID_RE.match(value)):
            raise ValueError(f"film_id must be a QID or 'wp-<page id>': {value!r}")
        return value

    @field_validator("wikidata_id")
    @classmethod
    def _qid(cls, value: str | None) -> str | None:
        if value is not None and not QID_RE.match(value):
            raise ValueError(f"invalid QID: {value!r}")
        return value

    @field_validator("imdb_id")
    @classmethod
    def _imdb(cls, value: str | None) -> str | None:
        if value is not None and not IMDB_RE.match(value):
            raise ValueError(f"invalid IMDb id: {value!r}")
        return value

    @field_validator("retrieved_at")
    @classmethod
    def _date(cls, value: str) -> str:
        if not ISO_UTC_RE.match(value):
            raise ValueError("retrieved_at must be ISO-8601 UTC (YYYY-MM-DDTHH:MM:SSZ)")
        return value

    @field_validator("year")
    @classmethod
    def _year(cls, value: int | None) -> int | None:
        if value is not None and not MIN_YEAR <= value <= MAX_YEAR:
            raise ValueError(f"implausible year: {value}")
        return value

    @field_validator("duration_minutes")
    @classmethod
    def _duration(cls, value: int | None) -> int | None:
        if value is not None and not MIN_DURATION <= value <= MAX_DURATION:
            raise ValueError(f"implausible duration: {value}")
        return value

    @field_validator("synopsis")
    @classmethod
    def _synopsis(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("empty synopsis")
        return value


def dumps_record(record: FilmRecord | dict[str, Any]) -> str:
    """Canonical JSON line (sorted keys, no volatile data): identical bytes for identical input."""
    data = record.model_dump() if isinstance(record, FilmRecord) else record
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
