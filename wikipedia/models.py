"""Typed input of the Wikipedia tool, filled by the planner LLM, and the rows the tool works with.

The field descriptions are part of the planning prompt (the orchestrator adds the tool's
`input_schema` to the catalog): they say what each value means and where it may come from.
"""
from __future__ import annotations

import unicodedata
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

MAX_TOPIC_CHARS = 200
MAX_PAGE_CHARS = 200
MAX_SECTION_CHARS = 120
MAX_SECTIONS = 10
MAX_REPORTED_ERRORS = 20

Language = Literal["it", "en"]


class Subject(str, Enum):
    person = "person"
    film = "film"
    topic = "topic"


class Depth(str, Enum):
    intro = "intro"
    sections = "sections"
    full = "full"


def normalize_text(text: Any) -> str:
    """Casefolded, accent-free, punctuation-free form used to compare titles ("&" reads "and")."""
    if not isinstance(text, str):
        return ""
    decomposed = unicodedata.normalize("NFKD", text.casefold().replace("&", " and "))
    kept = "".join(char if char.isalnum() else " " for char in decomposed if not unicodedata.combining(char))
    return " ".join(kept.split())


def _clean(value: Any) -> Any:
    return " ".join(value.split()) if isinstance(value, str) else value


class WikipediaToolInput(BaseModel):
    """Read Wikipedia for encyclopedic information about one person, film or cinema topic."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, description="The user's request; filled in by the system.")
    topic: str = Field(
        min_length=1,
        max_length=MAX_TOPIC_CHARS,
        description="The person, film or subject to look up, as the user or the conversation names it.",
    )
    kind: Subject = Field(
        default=Subject.topic,
        description="person (a director, actor...), film (a film or series), topic (a movement, genre, event).",
    )
    year: int | None = Field(
        default=None,
        ge=1888,
        le=2100,
        description="Release year of the film, only if the user or the conversation gives it.",
    )
    language: Language | None = Field(
        default=None,
        description=(
            "Wikipedia edition, only if the user asks for one or to reopen a page of an earlier "
            "result (copy its language); null = the language of the question, then the other one."
        ),
    )
    depth: Depth = Field(
        default=Depth.intro,
        description=(
            "intro: the lead of the best pages (simple facts). sections: some sections of ONE page. "
            "full: the whole article of ONE page, most relevant sections first. The tool says what "
            "it left out; ask again with `sections` or another `page` if the answer needs it."
        ),
    )
    page: str | None = Field(
        default=None,
        max_length=MAX_PAGE_CHARS,
        description=(
            "Exact title of the page to open, copied from an earlier result of this tool or from "
            "the conversation; never invented. null = the best page for `topic`."
        ),
    )
    sections: list[str] = Field(
        default_factory=list,
        max_length=MAX_SECTIONS,
        description=(
            "Titles of the sections to return, copied from the `outline` of an earlier result; "
            "empty = the tool picks the sections that match the question."
        ),
    )

    @field_validator("topic", "page", mode="before")
    @classmethod
    def _strip(cls, value: Any) -> Any:
        return _clean(value) or None if isinstance(value, str) else value

    @field_validator("sections", mode="before")
    @classmethod
    def _strip_sections(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        seen: dict[str, str] = {}
        for item in value:
            if isinstance(item, str) and _clean(item) and len(_clean(item)) <= MAX_SECTION_CHARS:
                seen.setdefault(normalize_text(item), _clean(item))
        return list(seen.values())


class PageHit(BaseModel):
    """One page of a search or of an opened article, as the API returned it."""

    pageid: int | None = None
    title: str
    language: str
    index: int = 0
    extract: str = ""
    disambiguation: bool = False
    touched: str | None = None


class PageResult(BaseModel):
    """What the tool handed out for one page, with a description of what it left out."""

    title: str
    language: str
    verification: str
    notes: list[str] = Field(default_factory=list)
    last_revised: str | None = None
    # None until the whole article has been read (a search gives only the lead).
    total_chars: int | None = None
    delivered_chars: int = 0
    sections: list[str] = Field(default_factory=list)
    outline: list[dict[str, Any]] | None = None
    omitted: list[dict[str, Any]] = Field(default_factory=list)
    unknown_sections: list[str] = Field(default_factory=list)
    truncated: bool = False
    text: list[dict[str, str]] = Field(default_factory=list)


class Section(BaseModel):
    """A slice of an article: the lead (level 1) or the text under one heading."""

    title: str
    level: int
    text: str

    @property
    def chars(self) -> int:
        return len(self.text)


def describe_validation_errors(exc: ValidationError) -> list[dict[str, Any]]:
    """Safe summary of a validation failure: field and error type, never the input values."""
    rows = []
    for error in exc.errors(include_url=False, include_input=False, include_context=False):
        names = [part for part in error.get("loc", ()) if isinstance(part, str)]
        field = names[0] if names else None
        rows.append(
            {
                "field": field if field is None or field in WikipediaToolInput.model_fields else "unknown_field",
                "error": error["type"],
            }
        )
    return rows[:MAX_REPORTED_ERRORS]
