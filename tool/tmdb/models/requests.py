"""Tool input: a flat, compact model per request, validated against `RULES`.

Everything is checked before any HTTP call: unknown fields, enums, ranges, fields that
the chosen operation does not accept, unsupported facets and incompatible discover
filters. Error messages name fields and operations, never the values sent.
"""
from __future__ import annotations

import re
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from .enums import (
    ChartList,
    Department,
    DiscoverSort,
    ExternalSource,
    Facet,
    MediaType,
    Monetization,
    ReleaseType,
    SearchKind,
    TimeWindow,
    TmdbOperation,
    TvStatus,
    TvType,
)
from .operation_rules import (
    CHART_LISTS,
    EXTERNAL_ID_PATTERNS,
    MOVIE_ONLY_FILTERS,
    RULES,
    TV_ONLY_FILTERS,
)

# Operations the LLM may request in one run. Input shape only: HTTP calls are limited
# exclusively by `CONFIG["tmdb"]["max_calls_per_turn"]`.
MAX_REQUESTS_PER_RUN = 4
MAX_TMDB_ID = 2_147_483_647

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Country = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]


def _upper(value: object) -> object:
    return value.strip().upper() if isinstance(value, str) else value


def _collapse(value: object) -> object:
    if isinstance(value, str):
        return " ".join(value.split()) or None
    return value


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


class DiscoverFilters(BaseModel):
    """Filters of `discover_movies` / `discover_tv`. Names are resolved to TMDb IDs by the tool."""

    model_config = ConfigDict(extra="forbid")

    genres: list[Name] = Field(default_factory=list, max_length=5, description="English genre names.")
    year_from: int | None = Field(default=None, ge=1870, le=2100)
    year_to: int | None = Field(default=None, ge=1870, le=2100)
    people: list[Name] = Field(
        default_factory=list, max_length=5, description="Movies only; cast or crew, all must appear."
    )
    cast: list[Name] = Field(
        default_factory=list,
        max_length=5,
        description="Movies only; actors in the cast (not crew), all must appear. Use it for 'films with <actor>'.",
    )
    companies: list[Name] = Field(default_factory=list, max_length=5)
    keywords: list[Name] = Field(default_factory=list, max_length=5, description="English keywords.")
    min_rating: float | None = Field(default=None, ge=0, le=10)
    max_rating: float | None = Field(default=None, ge=0, le=10)
    min_votes: int | None = Field(default=None, ge=0, le=1_000_000)
    min_runtime: int | None = Field(default=None, ge=0, le=1000)
    max_runtime: int | None = Field(default=None, ge=0, le=1000)
    original_language: str | None = Field(default=None, pattern=r"^[a-z]{2}$")
    origin_country: Country | None = None
    watch_providers: list[Name] = Field(default_factory=list, max_length=5)
    watch_region: Country | None = None
    monetization: list[Monetization] = Field(default_factory=list, max_length=5)
    certification: str | None = Field(default=None, pattern=r"^[A-Za-z0-9+\-]{1,10}$")
    certification_country: Country | None = None
    release_types: list[ReleaseType] = Field(default_factory=list, max_length=6)
    region: Country | None = None
    tv_status: TvStatus | None = None
    tv_type: TvType | None = None
    sort: DiscoverSort | None = None

    @field_validator("origin_country", "watch_region", "certification_country", "region", mode="before")
    @classmethod
    def _upper_countries(cls, value: object) -> object:
        return _upper(value)

    @field_validator("original_language", mode="before")
    @classmethod
    def _lower(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _consistent(self) -> DiscoverFilters:
        _check(not (self.year_from and self.year_to) or self.year_from <= self.year_to, "year_from must be <= year_to.")
        _check(
            self.min_rating is None or self.max_rating is None or self.min_rating <= self.max_rating,
            "min_rating must be <= max_rating.",
        )
        _check(
            self.min_runtime is None or self.max_runtime is None or self.min_runtime <= self.max_runtime,
            "min_runtime must be <= max_runtime.",
        )
        _check(
            bool(self.certification) == bool(self.certification_country),
            "certification and certification_country must be given together.",
        )
        _check(not self.watch_providers or bool(self.watch_region), "watch_providers requires watch_region.")
        _check(not self.monetization or bool(self.watch_providers), "monetization requires watch_providers.")
        _check(not self.release_types or bool(self.region), "release_types requires region.")
        return self

    def provided(self) -> set[str]:
        return {name for name in type(self).model_fields if getattr(self, name) not in (None, [])}


class TmdbRequest(BaseModel):
    """One TMDb operation. Only the fields listed for the operation are accepted."""

    model_config = ConfigDict(extra="forbid")

    operation: TmdbOperation
    kind: SearchKind | None = None
    search_query: str | None = Field(default=None, min_length=1, max_length=200)
    title: str | None = Field(default=None, min_length=1, max_length=200, description="Movie or series title.")
    name: str | None = Field(default=None, min_length=1, max_length=200, description="Person, collection or company.")
    year: int | None = Field(default=None, ge=1870, le=2100)
    tmdb_id: int | None = Field(default=None, ge=1, le=MAX_TMDB_ID)
    external_id: str | None = Field(default=None, min_length=1, max_length=20)
    external_source: ExternalSource | None = None
    department: Department | None = None
    season: int | None = Field(default=None, ge=0, le=200)
    episode: int | None = Field(default=None, ge=1, le=5000)
    facets: list[Facet] = Field(default_factory=list, max_length=20)
    region: Country | None = Field(default=None, description="ISO 3166-1 country, e.g. IT.")
    media: MediaType | None = None
    window: TimeWindow | None = None
    chart: ChartList | None = None
    filters: DiscoverFilters | None = None
    limit: int | None = Field(default=None, ge=1, le=20)

    @field_validator("search_query", "title", "name", "external_id", mode="before")
    @classmethod
    def _collapse_text(cls, value: object) -> object:
        return _collapse(value)

    @field_validator("region", mode="before")
    @classmethod
    def _upper_region(cls, value: object) -> object:
        return _upper(value)

    @field_validator("facets")
    @classmethod
    def _unique_facets(cls, facets: list[Facet]) -> list[Facet]:
        return list(dict.fromkeys(facets))

    def provided(self) -> set[str]:
        return {
            name
            for name in type(self).model_fields
            if name != "operation" and getattr(self, name) not in (None, [])
        }

    @model_validator(mode="after")
    def _matches_operation(self) -> TmdbRequest:
        rule = RULES[self.operation]
        op = self.operation.value
        provided = self.provided()

        for field in sorted(provided - rule.allowed):
            raise ValueError(f"field '{field}' is not allowed for operation '{op}'.")
        for group in rule.required:
            _check(bool(provided & set(group)), f"operation '{op}' requires " + " or ".join(group) + ".")
        for facet in self.facets:
            _check(facet in rule.facets, f"facet '{facet.value}' is not supported by '{op}'.")
        if rule.media:
            _check(self.media in rule.media, f"media must be one of: {', '.join(m.value for m in rule.media)}.")

        _check(bool(self.external_id) == bool(self.external_source), "external_id and external_source go together.")
        if self.external_id and self.external_source:
            _check(
                re.match(EXTERNAL_ID_PATTERNS[self.external_source], self.external_id) is not None,
                f"external_id is not a valid {self.external_source.value} ID.",
            )
            if self.external_source is ExternalSource.imdb and op != "find_by_external_id":
                prefix = "nm" if op == "person_details" else "tt"
                _check(self.external_id.startswith(prefix), f"'{op}' needs an IMDb ID starting with {prefix}.")

        if self.operation is TmdbOperation.search and self.year is not None:
            _check(self.kind in (SearchKind.movie, SearchKind.tv), "year is only allowed when searching movie or tv.")
        if self.operation is TmdbOperation.chart:
            _check(self.chart in CHART_LISTS[self.media], f"chart is not available for media '{self.media.value}'.")
            _check(self.region is None or self.media is MediaType.movie, "region is only allowed for movie charts.")
        if self.filters is not None:
            used = self.filters.provided()
            if self.operation is TmdbOperation.discover_movies:
                for field in sorted(used & TV_ONLY_FILTERS):
                    raise ValueError(f"filter '{field}' is only allowed for discover_tv.")
            else:
                for field in sorted(used & MOVIE_ONLY_FILTERS):
                    raise ValueError(f"filter '{field}' is only allowed for discover_movies.")
                _check(self.filters.sort is not DiscoverSort.revenue_desc, "sort revenue_desc is movies only.")
        return self


class TmdbToolInput(BaseModel):
    """Query The Movie Database (TMDb): fill `requests` with 1 to 4 typed operations."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, description="The user's request; filled in by the system.")
    requests: list[TmdbRequest] = Field(min_length=1, max_length=MAX_REQUESTS_PER_RUN)

    @model_validator(mode="before")
    @classmethod
    def _single_request(cls, data: Any) -> Any:
        """Accept one flat request (`{"operation": ...}`) as a one-item `requests` list."""
        if isinstance(data, dict) and "requests" not in data and "operation" in data:
            data = dict(data)
            query = data.pop("query", None)
            return {"query": query, "requests": [data]}
        return data


_KNOWN_FIELDS = (
    set(TmdbToolInput.model_fields) | set(TmdbRequest.model_fields) | set(DiscoverFilters.model_fields) | {"filters"}
)
MAX_REPORTED_ERRORS = 20


def describe_validation_errors(exc: ValidationError) -> list[dict[str, Any]]:
    """Safe summary of a validation failure: request number, field, error type.

    Input values and context are excluded; a field name not in the schema (sent by the
    model as an extra key) is reported as `unknown_field`.
    """
    rows = []
    for error in exc.errors(include_url=False, include_input=False, include_context=False):
        loc = error.get("loc", ())
        request = loc[1] + 1 if len(loc) > 1 and loc[0] == "requests" and isinstance(loc[1], int) else None
        names = [part for part in loc if isinstance(part, str) and part != "requests"]
        field = names[-1] if names else None
        row: dict[str, Any] = {
            "request": request,
            "field": field if field is None or field in _KNOWN_FIELDS else "unknown_field",
            "error": error["type"],
        }
        if error["type"] == "value_error":
            # Our own messages: they name fields and operations, never values.
            row["detail"] = str(error["msg"]).removeprefix("Value error, ")
        rows.append({key: value for key, value in row.items() if value is not None})
    return rows[:MAX_REPORTED_ERRORS]
