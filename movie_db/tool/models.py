from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from movie_db.schema import GENRES

_GENRES_BY_KEY = {genre.casefold(): genre for genre in GENRES}

SqlParam = str | int | float | None


class MovieDbOperation(str, Enum):
    """Closed set of operations: each one maps to SQL written in `sql/queries.py`."""

    top_rated = "top_rated"
    most_rated = "most_rated"
    by_title = "by_title"
    by_genre_year = "by_genre_year"
    by_tag = "by_tag"
    stats_by_genre = "stats_by_genre"


class MovieDbQuery(BaseModel):
    """Validated request produced by the parser. Never contains SQL."""

    model_config = ConfigDict(extra="forbid")

    operation: MovieDbOperation
    title: str | None = Field(default=None, min_length=1, max_length=200)
    genre: str | None = None
    tag: str | None = Field(default=None, min_length=1, max_length=100)
    year_from: int | None = Field(default=None, ge=1870, le=2100)
    year_to: int | None = Field(default=None, ge=1870, le=2100)
    # Clamped to `query.max_limit` by the repository.
    limit: int | None = Field(default=None, ge=1)

    @field_validator("title", "tag", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            value = " ".join(value.split())
            return value or None
        return value

    @field_validator("genre", mode="before")
    @classmethod
    def _canonical_genre(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        if not isinstance(value, str) or value.strip().casefold() not in _GENRES_BY_KEY:
            raise ValueError(f"Unknown genre: {value!r}. Allowed: {', '.join(GENRES)}.")
        return _GENRES_BY_KEY[value.strip().casefold()]

    @model_validator(mode="after")
    def _required_arguments(self) -> MovieDbQuery:
        if self.year_from and self.year_to and self.year_from > self.year_to:
            raise ValueError("year_from must be <= year_to.")
        if self.operation is MovieDbOperation.by_title and not self.title:
            raise ValueError("by_title requires a title.")
        if self.operation is MovieDbOperation.by_tag and not self.tag:
            raise ValueError("by_tag requires a tag.")
        if self.operation is MovieDbOperation.by_genre_year and not (
            self.genre or self.year_from or self.year_to
        ):
            raise ValueError("by_genre_year requires a genre or a year range.")
        return self


class ExecutedQuery(BaseModel):
    """One SQL statement run by the repository: the only content of the trace."""

    sql: str
    params: list[SqlParam] = Field(default_factory=list)


class MovieDbToolInput(BaseModel):
    """Query the local MovieLens database (ratings, genres, years, tags) in natural language."""

    query: str = Field(min_length=1)
