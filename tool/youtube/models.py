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
MAX_CAST = 5
MAX_KINDS = 3
MAX_REPORTED_ERRORS = 20


class VideoKind(str, Enum):
    trailer = "trailer"
    director_interview = "director_interview"
    cast_interview = "cast_interview"
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


# Articles ignored when deciding whether a title is a single, generic word.
ARTICLES = frozenset({"the", "a", "an", "il", "lo", "la", "i", "gli", "le", "l", "un", "uno", "una"})
# A surname alone identifies a person only from this length ("Lee" is too common).
MIN_SURNAME_CHARS = 4


def is_one_word_title(title: str) -> bool:
    """"Her", "Arrival", "The Heat": one significant word, so the title alone is ambiguous."""
    return len([word for word in normalize_text(title).split() if word not in ARTICLES]) <= 1


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
            "Up to 3 other titles of the same film (original-language, Italian or English title), "
            "copied verbatim from the user's request or from earlier messages of the conversation: "
            "a title the user wrote in parentheses, or one given in a previous answer. Never invent "
            "or translate a title yourself and never deduce one from your own knowledge, not even a "
            "well-known original title. If the user gives only a localized title and no other title "
            "is written in the conversation, leave this empty: the search uses `title` as given."
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
    cast: list[str] = Field(
        default_factory=list,
        max_length=MAX_CAST,
        description=(
            "Up to 5 names of cast members that appear verbatim in the user's request or in the "
            "conversation. Never add a name yourself, even a well-known one; leave empty when the "
            "conversation names nobody."
        ),
    )
    kinds: list[VideoKind] = Field(
        min_length=1,
        max_length=MAX_KINDS,
        description=(
            "Video categories, most important first: director_interview (interviews with the "
            "director), cast_interview (interviews with the actors or the cast), making_of, "
            "behind_the_scenes (backstage, featurettes), author_commentary (the authors explaining "
            "or commenting the film), trailer (only if the user explicitly asks for YouTube or "
            "accepts searching it there)."
        ),
    )

    @field_validator("title", "director", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return _clean(value) or None if isinstance(value, str) else value

    @field_validator("alternative_titles", "cast", mode="before")
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
        # The same person written twice, or the director repeated among the cast, counts once.
        people = {normalize_text(self.director)} if self.director else set()
        cast = []
        for name in self.cast:
            key = normalize_text(name)
            if key and key not in people:
                people.add(key)
                cast.append(name)
        self.cast = cast
        return self

    @property
    def people(self) -> list[str]:
        """Every known person of the film: the director first, then the cast."""
        return [*([self.director] if self.director else []), *self.cast]


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
    # `confirmed` | `to_verify` (`relevance.verification`, from the notes): a label for the
    # answer and the presenters, not a score; the API order is kept within each group.
    verification: str = "confirmed"


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
