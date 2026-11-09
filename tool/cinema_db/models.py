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

from .constants import MAX_LIMIT, MAX_TEXT_CHARS, ML_GENRES, ML_MODES, ROLES

IMDB_TITLE = re.compile(r"^tt\d{7,9}$")
WIKIDATA_ID = re.compile(r"^Q[1-9]\d{0,11}$")
MAX_REPORTED_ERRORS = 20

Operation = Literal[
    "find_work", "work_card", "find_person", "filmography", "cast", "crew", "collaborations",
    "awards", "series", "companies", "franchise", "relations", "ratings", "movielens", "provenance", "sql",
]
Role = Enum("Role", {r: r for r in ROLES}, type=str)  # an Enum: the planner schema defines it once and references it twice

WORK_OPERATIONS = {"find_work", "work_card", "cast", "crew", "relations", "series"}
PERSON_OPERATIONS = {"find_person", "filmography", "collaborations"}


class CinemaSqlInput(BaseModel):
    """Local cinema database: identify a film, series or person and read their credits, awards, relations, companies and series structure."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    query: str = Field(min_length=1, description="Filled in by the system.")
    operation: Operation = Field(
        description=(
            "find_work/find_person: identify (ids, alternatives). work_card: facts of a work. filmography: works of `person`. cast/crew: of a work. "
            "collaborations: works shared by `person` and `person_b` (null: who `person` worked with most). awards: of a work, a person or an `award`. "
            "series: recorded seasons or episodes of `season` (counts, dates: tvmaze_search). companies: of a work or `company`. franchise: of a work or by name. relations: source and series order. "
            "ratings: audience ratings of a work (no work: best rated, with year_from/year_to/type/min_votes). movielens: MovieLens users' lists, see `ml_mode`. "
            "provenance: ids, identification level, alternative values. sql: one SELECT on the views in the tool description."
        )
    )
    title: str | None = Field(default=None, max_length=MAX_TEXT_CHARS, description="Title or alias.")
    year: int | None = Field(default=None, ge=1870, le=2100, description="Release year, only if given.")
    director: str | None = Field(default=None, max_length=MAX_TEXT_CHARS, description="Director, only if given.")
    type: Literal["film", "series"] | None = Field(default=None, description="film (also shorts, TV films) or series. For films only pass film (ratings, by_tag: else both).")
    work_id: int | None = Field(default=None, ge=1, description="Local work id from a step.")
    imdb_id: str | None = Field(default=None, description="IMDb title id, only if given or from an earlier step.")
    tmdb_id: int | None = Field(default=None, ge=1, description="TMDb id (needs `type`), if given.")
    wikidata_id: str | None = Field(default=None, description="Wikidata id, only if given.")
    person: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)
    person_id: int | None = Field(default=None, ge=1, description="Local person id from a step.")
    person_b: str | None = Field(default=None, max_length=MAX_TEXT_CHARS, description="Second person.")
    person_b_id: int | None = Field(default=None, ge=1, description="Local id of `person_b`.")
    birth_year: int | None = Field(default=None, ge=1000, le=2100, description="Birth year, only if given.")
    role: Role | None = Field(default=None, description="Role of `person`, or of the crew to list; null = every role (also when several roles are asked).")
    role_b: Role | None = Field(default=None, description="Role of `person_b` or of the collaborators.")
    year_from: int | None = Field(default=None, ge=1870, le=2100, description="First year.")
    year_to: int | None = Field(default=None, ge=1870, le=2100, description="Last year.")
    order: Literal["asc", "desc"] = Field(default="asc", description="desc = most recent first.")
    award: str | None = Field(default=None, max_length=MAX_TEXT_CHARS, description="Award or category name.")
    outcome: Literal["won", "nominated"] | None = Field(default=None, description="Only won or nominated.")
    season: int | None = Field(default=None, ge=0, le=500, description="Season number: lists its episodes.")
    company: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)
    franchise: str | None = Field(default=None, max_length=MAX_TEXT_CHARS)
    min_votes: int | None = Field(default=None, ge=1, le=10_000_000, description="Minimum votes (ratings 1000, movielens 50).")
    ml_mode: Literal["top_rated", "most_rated", "by_title", "by_tag", "genre_stats"] | None = Field(
        default=None, description="movielens: top_rated/most_rated (genre, years), by_title, by_tag, genre_stats.")
    genre: str | None = Field(default=None, description="MovieLens genre (Action, Sci-Fi, Film-Noir...).")
    tag: str | None = Field(default=None, max_length=100, description="by_tag: user tag.")
    limit: int | None = Field(default=None, ge=1, le=MAX_LIMIT, description="Rows (default 25).")
    sql: str | None = Field(default=None, max_length=2000, description="sql only: ONE SELECT with ? and a LIMIT.")
    params: list[str | int | float | None] | None = Field(default=None, max_length=16, description="sql only: values of the ?.")

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
            subjects = sum(bool(x) for x in (has_work, self.person or self.person_id))
            if subjects > 1 or (subjects == 0 and not self.award):
                raise ValueError("awards needs exactly one target: a work, a person, or an award name alone (an award name can also narrow the awards of a work or a person)")
        if op == "provenance":
            subjects = sum(bool(x) for x in (has_work, self.person or self.person_id))
            if subjects != 1:
                raise ValueError("provenance needs exactly one target: a work (title, work_id, imdb_id...) or a person (person, person_id)")
        if op not in {"ratings", "movielens"} and self.min_votes is not None:
            raise ValueError("min_votes is only for ratings and movielens")
        if op != "movielens" and any(x is not None for x in (self.ml_mode, self.genre, self.tag)):
            raise ValueError("ml_mode, genre and tag are only for movielens")
        if op == "movielens":
            if self.ml_mode is None:
                raise ValueError("movielens needs ml_mode (" + ", ".join(ML_MODES) + ")")
            if self.genre is not None:
                canonical = {g.casefold(): g for g in ML_GENRES}.get(self.genre.strip().casefold())
                if canonical is None:
                    raise ValueError("genre must be one of: " + ", ".join(ML_GENRES))
                self.genre = canonical
            if self.ml_mode == "by_title" and not self.title:
                raise ValueError("by_title needs title")
            if self.ml_mode == "by_tag" and not (self.tag and self.tag.strip()):
                raise ValueError("by_tag needs tag")
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
        item = {"field": ".".join(str(p) for p in e.get("loc", ())) or "request", "problem": str(e.get("type", "invalid"))}
        if e.get("type") == "value_error" and isinstance(e.get("msg"), str):  # the rule written in this file (never a value the user wrote)
            item["rule"] = e["msg"].removeprefix("Value error, ")
        out.append(item)
    return out


def as_arguments(model: CinemaSqlInput) -> dict[str, Any]:
    return model.model_dump(exclude_none=True, exclude={"query"})
