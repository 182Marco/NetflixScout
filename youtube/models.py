"""Typed input of the YouTube tool, filled by the planner LLM.

The field descriptions are part of the planning prompt (the orchestrator adds the tool's
`input_schema` to the catalog): they say what each value means and where it may come from.
"""
from __future__ import annotations

import unicodedata
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

MAX_TITLE_CHARS = 200
MAX_NAME_CHARS = 100
MAX_ALTERNATIVE_TITLES = 3
MAX_KINDS = 3
MAX_REPORTED_ERRORS = 20


class VideoKind(str, Enum):
    trailer = "trailer"
    director_interview = "director_interview"
    making_of = "making_of"
    behind_the_scenes = "behind_the_scenes"
    author_commentary = "author_commentary"


def normalize_text(text: Any) -> str:
    """Casefolded, accent-free, punctuation-free form used to compare titles ("&" reads "and")."""
    if not isinstance(text, str):
        return ""
    decomposed = unicodedata.normalize("NFKD", text.casefold().replace("&", " and "))
    kept = "".join(char if char.isalnum() else " " for char in decomposed if not unicodedata.combining(char))
    return " ".join(kept.split())


def _clean(value: Any) -> Any:
    return " ".join(value.split()) if isinstance(value, str) else value


class YoutubeToolInput(BaseModel):
    """Search YouTube for videos about one identified film: interviews, making-of, behind the
    scenes, authors' commentary, and trailers only when the user explicitly asks for YouTube."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, description="The user's request; filled in by the system.")
    title: str = Field(
        min_length=1,
        max_length=MAX_TITLE_CHARS,
        description="Title of the film as the user or the conversation gives it.",
    )
    alternative_titles: list[str] = Field(
        default_factory=list,
        max_length=MAX_ALTERNATIVE_TITLES,
        description=(
            "Up to 3 other titles of the same film (original, Italian or English title) that appear "
            "verbatim in the conversation or in the user's request. Never invent or translate a title "
            "yourself; leave empty when the conversation has none."
        ),
    )
    year: int | None = Field(
        default=None,
        ge=1888,
        le=2100,
        description="Release year, only if the user or the conversation gives it.",
    )
    director: str | None = Field(
        default=None,
        max_length=MAX_NAME_CHARS,
        description="Director's name, only if the user or the conversation gives it.",
    )
    kinds: list[VideoKind] = Field(
        min_length=1,
        max_length=MAX_KINDS,
        description=(
            "Video categories, most important first: director_interview (interviews with the director "
            "or the cast), making_of, behind_the_scenes (backstage, featurettes), author_commentary "
            "(the authors explaining or commenting the film), trailer (only if the user explicitly "
            "asks for YouTube or accepts searching it there)."
        ),
    )

    @field_validator("title", "director", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return _clean(value) or None if isinstance(value, str) else value

    @field_validator("alternative_titles", mode="before")
    @classmethod
    def _strip_titles(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        return [_clean(item) for item in value if not isinstance(item, str) or _clean(item)]

    @field_validator("kinds", mode="before")
    @classmethod
    def _unique_kinds(cls, value: Any) -> Any:
        """Repeated kinds count once, in their first position (a repeat is not an error)."""
        if not isinstance(value, list):
            return value
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def _distinct_titles(self) -> YoutubeToolInput:
        """Alternative titles equal to the title or to each other (ignoring case, accents and
        punctuation) are dropped: they add nothing to the search."""
        seen = {normalize_text(self.title)}
        kept = []
        for title in self.alternative_titles:
            key = normalize_text(title)
            if key and key not in seen:
                seen.add(key)
                kept.append(title)
        self.alternative_titles = kept
        return self


class VideoHit(BaseModel):
    """One video kept for a kind. `title` and `channel` are the API values, unchanged
    (from `/videos`; from the search snippet with HTML entities decoded when `/videos`
    could not be read, noted `title_from_search`). `url` is the only value built by the
    tool, from a validated video ID."""

    video_id: str
    url: str
    title: str
    channel: str
    published_at: str | None = None
    description_excerpt: str | None = None
    duration_seconds: int | None = None
    matched_on: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class KindOutcome(BaseModel):
    """What happened to one requested kind.

    `status`: `searched` (then `result` is `ok`, `empty` or `error`) or `not_searched`
    (then `reason` is `turn_limit` or the error that stopped the run, e.g. `quota_exceeded`).
    """

    kind: VideoKind
    status: str
    result: str | None = None
    reason: str | None = None
    error: str | None = None
    returned: int = 0
    filtered_out: dict[str, int] = Field(default_factory=dict)
    hits: list[VideoHit] = Field(default_factory=list)


def describe_validation_errors(exc: ValidationError) -> list[dict[str, Any]]:
    """Safe summary of a validation failure: field and error type, never the input values.

    A field name not in the schema (sent by the model as an extra key) is `unknown_field`.
    """
    rows = []
    for error in exc.errors(include_url=False, include_input=False, include_context=False):
        names = [part for part in error.get("loc", ()) if isinstance(part, str)]
        field = names[0] if names else None
        rows.append(
            {
                "field": field if field is None or field in YoutubeToolInput.model_fields else "unknown_field",
                "error": error["type"],
            }
        )
    return rows[:MAX_REPORTED_ERRORS]
