"""Typed input of the TVmaze tool, filled by the planner LLM.

The field descriptions are part of the planning prompt (the orchestrator adds the tool's
`input_schema` to the catalog): they say what each value means and where it may come from.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

MAX_TITLE_CHARS = 200
MAX_REPORTED_ERRORS = 20

Facet = Literal["info", "cast", "seasons", "episodes", "next"]


class TvmazeToolInput(BaseModel):
    """Structured data of one identified TV series: status, network, dates, cast, seasons, episodes, next episode."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, description="The user's request; filled in by the system.")
    title: str = Field(
        min_length=1,
        max_length=MAX_TITLE_CHARS,
        description=(
            "Title of the series as the user or the conversation gives it (TVmaze mostly knows "
            "original or English titles). The tool returns the alternatives, not data, when the "
            "title is ambiguous."
        ),
    )
    year: int | None = Field(
        default=None,
        ge=1900,
        le=2100,
        description=(
            "Year the series premiered, only if it is in the user's request or in the conversation; "
            "never guessed. It tells apart series with the same title."
        ),
    )
    facets: list[Facet] = Field(
        default_factory=lambda: ["info"],
        min_length=1,
        max_length=5,
        description=(
            "What to read. info: status, network, premiere/end dates, runtime, language, genres, "
            "short summary (always included). cast: actors and characters. seasons: each season's "
            "number, episode count and dates. episodes: the episodes of ONE season (needs `season`) "
            "with number and air date. next: the upcoming episode if TVmaze lists one."
        ),
    )
    season: int | None = Field(
        default=None,
        ge=0,
        le=200,
        description="Season number for `episodes` (0 = specials). Only if the request or the conversation gives it.",
    )
    episode: int | None = Field(
        default=None,
        ge=1,
        le=2000,
        description="Episode number inside `season`, to read a single episode. Only if the request gives it.",
    )

    @field_validator("title", mode="before")
    @classmethod
    def _clean(cls, value: Any) -> Any:
        return " ".join(value.split()) if isinstance(value, str) else value

    @model_validator(mode="after")
    def _consistent(self) -> TvmazeToolInput:
        if "episodes" in self.facets and self.season is None:
            raise ValueError("season is required for the episodes facet")
        if self.episode is not None and self.season is None:
            raise ValueError("season is required with episode")
        self.facets = list(dict.fromkeys(self.facets))
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
                "field": field if field is None or field in TvmazeToolInput.model_fields else "unknown_field",
                "error": error["type"],
            }
        )
    return rows[:MAX_REPORTED_ERRORS]
