"""Typed input of the Wikidata tool, filled by the planner LLM.

The field descriptions are part of the planning prompt (the orchestrator adds the tool's
`input_schema` to the catalog): they say what each value means and where it may come from. Every
value that reaches a request is validated here; the SPARQL text is built by `queries.py` from
constants and from values that match a strict pattern.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

MAX_TITLE_CHARS = 200
MAX_REPORTED_ERRORS = 20

Operation = Literal["resolve", "relations"]
MediaType = Literal["movie", "tv"]
SearchLanguage = Literal["en", "it", "de", "fr", "es"]

IMDB_TITLE_ID = re.compile(r"^tt\d{7,9}$")


class WikidataToolInput(BaseModel):
    """Identify ONE film or series among homonyms, or read its declared relations to other works."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, description="The user's request; filled in by the system.")
    operation: Operation = Field(
        description=(
            "resolve: tell the works that share a title apart (year, director, IMDb and TMDb ids). "
            "relations: identify the work, then read the works it is based on (literary or film "
            "source), the works based on it (remakes, adaptations, inspired works), the previous and "
            "next work in its series and the other works of its franchise."
        ),
    )
    title: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_TITLE_CHARS,
        description=(
            "Title of the film or series as the user or the conversation gives it, in `language`. "
            "Needed unless imdb_id or tmdb_id is given."
        ),
    )
    language: SearchLanguage = Field(
        default="en",
        description="Language of `title` (the original or English title works best); en unless the title is in another one.",
    )
    year: int | None = Field(
        default=None,
        ge=1880,
        le=2100,
        description=(
            "Year of release (or of the first airing), only if it is in the request, in the conversation or "
            "in an earlier step of this turn; never guessed."
        ),
    )
    director: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_TITLE_CHARS,
        description="Director, only if it is in the request, in the conversation or in an earlier step of this turn; never guessed.",
    )
    type: MediaType | None = Field(
        default=None,
        description="movie or tv, only when the request or the conversation says it; null looks at both.",
    )
    imdb_id: str | None = Field(
        default=None,
        description=(
            "IMDb title id (tt plus digits), only if it is in the request, in the conversation or in an earlier "
            "step of this turn; never written from memory."
        ),
    )
    tmdb_id: int | None = Field(
        default=None,
        ge=1,
        le=100_000_000,
        description="TMDb id, only if an earlier step or the conversation gives it; it needs `type`.",
    )

    @field_validator("title", "director", mode="before")
    @classmethod
    def _clean(cls, value: Any) -> Any:
        return " ".join(value.split()) if isinstance(value, str) else value

    @field_validator("imdb_id")
    @classmethod
    def _imdb(cls, value: str | None) -> str | None:
        if value is not None and not IMDB_TITLE_ID.match(value):
            raise ValueError("imdb_id must look like tt1234567")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> WikidataToolInput:
        if self.title is None and self.imdb_id is None and self.tmdb_id is None:
            raise ValueError("title, imdb_id or tmdb_id is required")
        if self.tmdb_id is not None and self.type is None:
            raise ValueError("type is required with tmdb_id")
        return self


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
                "field": field if field is None or field in WikidataToolInput.model_fields else "unknown_field",
                "error": error["type"],
            }
        )
    return rows[:MAX_REPORTED_ERRORS]
