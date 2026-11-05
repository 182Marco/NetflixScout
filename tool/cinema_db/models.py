"""Typed input of the `cinema_sql` tool, filled by the planner LLM.

The field descriptions are part of the planning prompt: they say what each value means and where it may come from. Identifiers are
accepted ONLY when the user, the conversation or a step already done in the turn gave them (the tool returns them in every result so the next step
can reuse them); the planner never writes one from memory.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .constants import MAX_LIMIT, MAX_TEXT_CHARS, ROLES

IMDB_TITLE = re.compile(r"^tt\d{7,9}$")
WIKIDATA_ID = re.compile(r"^Q[1-9]\d{0,11}$")
MAX_REPORTED_ERRORS = 20

Operation = Literal[
    "find_work", "work_card", "find_person", "filmography", "cast", "crew", "collaborations",
    "awards", "series", "companies", "franchise", "relations", "sql",
]
Role = Enum("Role", {r: r for r in ROLES}, type=str)  # an Enum: the planner schema defines it once and references it twice

WORK_OPERATIONS = {"find_work", "work_card", "cast", "crew", "relations", "series"}
PERSON_OPERATIONS = {"find_person", "filmography", "collaborations"}


class CinemaSqlInput(BaseModel):
    """Local cinema database: identify a film, series or person and read their credits, awards, relations, companies and series structure."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    query: str = Field(min_length=1, description="The user's request; filled in by the system.")
    operation: Operation = Field(
        description=(
            "find_work/find_person: identify (ids, alternatives). work_card: facts of a work. filmography: works of `person`. cast/crew: of a work. "
            "collaborations: works shared by `person` and `person_b`; person_b null = people `person` worked with most. awards: of a work, a person or "
            "an `award`. series: seasons, or episodes of `season`. companies: of a work or of `company`. franchise: of a work or by name. "
            "relations: source and series order. sql: one SELECT on the views in the tool description."
        )
    )
    title: str | None = Field(default=None, max_length=MAX_TEXT_CHARS, description="Title or alias, as the user gives it.")
    year: int | None = Field(default=None, ge=1870, le=2100, description="Release year, only if given; tells apart same-title works.")
    director: str | None = Field(default=None, max_length=MAX_TEXT_CHARS, description="Director, only if given; tells apart same-title works.")
    type: Literal["film", "series"] | None = Field(default=None, description="film (also shorts, TV films) or series (also miniseries); null = any.")
    work_id: int | None = Field(default=None, ge=1, description="Local work id from an earlier step; skips the search.")
    imdb_id: str | None = Field(default=None, description="IMDb title id, only if given by the user, the conversation or an earlier step; never from memory.")
    tmdb_id: int | None = Field(default=None, ge=1, description="TMDb id of the work (needs `type`), only if given.")
    wikidata_id: str | None = Field(default=None, description="Wikidata id of the work or person, only if given.")
    person: str | None = Field(default=None, max_length=MAX_TEXT_CHARS, description="Person name.")
    person_id: int | None = Field(default=None, ge=1, description="Local person id from an earlier step.")
    person_b: str | None = Field(default=None, max_length=MAX_TEXT_CHARS, description="Second person (collaborations).")
    person_b_id: int | None = Field(default=None, ge=1, description="Local id of the second person.")
    birth_year: int | None = Field(default=None, ge=1000, le=2100, description="Birth year, only if given; tells apart namesakes.")
    role: Role | None = Field(default=None, description="Role of `person`; null = any.")
    role_b: Role | None = Field(default=None, description="Role of the second person or collaborators.")
    year_from: int | None = Field(default=None, ge=1870, le=2100, description="First year of a list.")
    year_to: int | None = Field(default=None, ge=1870, le=2100, description="Last year of a list.")
    order: Literal["asc", "desc"] = Field(default="asc", description="asc, or desc for the most recent first.")
    award: str | None = Field(default=None, max_length=MAX_TEXT_CHARS, description="Award or category name, mostly Italian ('Oscar al miglior film').")
    outcome: Literal["won", "nominated"] | None = Field(default=None, description="Only won or only nominated.")
    season: int | None = Field(default=None, ge=0, le=500, description="Season number: lists its episodes.")
    company: str | None = Field(default=None, max_length=MAX_TEXT_CHARS, description="Company name.")
    franchise: str | None = Field(default=None, max_length=MAX_TEXT_CHARS, description="Franchise or saga name.")
    limit: int | None = Field(default=None, ge=1, le=MAX_LIMIT, description="Rows to list (default 25, max 50).")
    sql: str | None = Field(default=None, max_length=2000, description="sql only: ONE SELECT, ? placeholders, a LIMIT.")
    params: list[str | int | float | None] | None = Field(default=None, max_length=16, description="sql only: values of the ? placeholders.")

    @model_validator(mode="after")
    def _check(self) -> CinemaSqlInput:
        if self.imdb_id is not None and not IMDB_TITLE.match(self.imdb_id):
            raise ValueError("imdb_id must be tt followed by 7-9 digits")
        if self.wikidata_id is not None and not WIKIDATA_ID.match(self.wikidata_id):
            raise ValueError("wikidata_id must be Q followed by digits")
        if self.tmdb_id is not None and self.type is None:
            raise ValueError("tmdb_id needs type (film or series): film and series ids overlap")
        if self.year_from and self.year_to and self.year_from > self.year_to:
            raise ValueError("year_from is after year_to")
        op = self.operation
        has_work = any((self.title, self.work_id, self.imdb_id, self.tmdb_id)) or (self.wikidata_id and op in WORK_OPERATIONS)
        has_person = any((self.person, self.person_id)) or (self.wikidata_id and op in PERSON_OPERATIONS)
        if op in WORK_OPERATIONS and not has_work:
            raise ValueError(f"{op} needs title, work_id, imdb_id, tmdb_id or wikidata_id")
        if op in PERSON_OPERATIONS and not has_person:
            raise ValueError(f"{op} needs person, person_id or wikidata_id")
        if op == "awards":
            targets = sum(bool(x) for x in (has_work, self.person or self.person_id, self.award))
            if targets != 1:
                raise ValueError("awards needs exactly one of: a work, a person, an award name")
        if op == "companies" and not (has_work or self.company):
            raise ValueError("companies needs a work or a company name")
        if op == "franchise" and not (has_work or self.franchise):
            raise ValueError("franchise needs a work or a franchise name")
        if op == "sql":
            if not self.sql:
                raise ValueError("operation sql needs sql")
        elif self.sql is not None or self.params is not None:
            raise ValueError("sql and params are only for operation sql")
        return self


def describe_validation_errors(exc: ValidationError) -> list[dict[str, str]]:
    """Field and rule of each problem, never the values (they are the user's words)."""
    out = []
    for e in exc.errors()[:MAX_REPORTED_ERRORS]:
        out.append({"field": ".".join(str(p) for p in e.get("loc", ())) or "request", "problem": str(e.get("type", "invalid"))})
    return out


def as_arguments(model: CinemaSqlInput) -> dict[str, Any]:
    return model.model_dump(exclude_none=True, exclude={"query"})
