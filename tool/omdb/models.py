"""Typed input of the OMDb tool, filled by the planner LLM.

The field descriptions are part of the planning prompt (the orchestrator adds the tool's
`input_schema` to the catalog): they say what each value means and where it may come from.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

MAX_TITLE_CHARS = 200
MAX_REPORTED_ERRORS = 20
# `tt` + 7 or 8 digits (OMDb accepts eight-digit IDs since 2019).
IMDB_ID = re.compile(r"^tt\d{7,8}$")


class OmdbToolInput(BaseModel):
    """Critic and audience scores (IMDb, Metascore, Rotten Tomatoes) of one identified film or series."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, description="The user's request; filled in by the system.")
    imdb_id: str | None = Field(
        default=None,
        description=(
            "IMDb ID (tt followed by 7-8 digits) of the film or series. Fill it ONLY when the user "
            "wrote it, an earlier message of the conversation gave it, or a step already done in "
            "this turn returned it (for example tmdb_search details); never invent or recall one "
            "from memory. With an ID the title is not searched. Leave null otherwise."
        ),
    )
    title: str | None = Field(
        default=None,
        max_length=MAX_TITLE_CHARS,
        description=(
            "Title of the film or series as the user or the conversation gives it. Used only when "
            "`imdb_id` is null: the tool searches the title and returns the alternatives, not "
            "scores, when it is ambiguous."
        ),
    )
    year: int | None = Field(
        default=None,
        ge=1870,
        le=2100,
        description=(
            "Release year, only if it is in the user's request or in the conversation; never "
            "guessed. It tells apart works with the same title."
        ),
    )
    type: Literal["movie", "series"] | None = Field(
        default=None,
        description="movie or series, only if the request or the conversation says which; otherwise null.",
    )

    @field_validator("imdb_id", "title", mode="before")
    @classmethod
    def _clean(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = " ".join(value.split())
            return value or None
        return value

    @field_validator("imdb_id")
    @classmethod
    def _imdb_id_shape(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.lower()
        if not IMDB_ID.match(value):
            raise ValueError("imdb_id must be tt followed by 7 or 8 digits")
        return value

    @model_validator(mode="after")
    def _identifies_a_work(self) -> OmdbToolInput:
        if self.imdb_id is None and self.title is None:
            raise ValueError("imdb_id or title is required")
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
                "field": field if field is None or field in OmdbToolInput.model_fields else "unknown_field",
                "error": error["type"],
            }
        )
    return rows[:MAX_REPORTED_ERRORS]
