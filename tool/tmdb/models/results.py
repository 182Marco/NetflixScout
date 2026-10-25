"""Normalized TMDb results, before they are packed into the LLM context."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Entity(BaseModel):
    """A movie, series, season, episode, person, collection, company or keyword.

    Identity (P0) is always kept; `essentials` (P1) are kept for detail entities;
    `facets` (P2) are already capped per list and packed only while space remains.
    """

    kind: str
    tmdb_id: int
    title: str
    original_title: str | None = None
    original_language: str | None = None
    year: int | None = None
    imdb_id: str | None = None
    summary: str | None = None
    genres: list[str] = Field(default_factory=list)
    score: float | None = None
    # Raw TMDb values for the web cards (`tool/tmdb/trace.py`); not part of the LLM context.
    release_date: str | None = None
    poster_path: str | None = None
    essentials: dict[str, Any] = Field(default_factory=dict)
    facets: dict[str, list[Any]] = Field(default_factory=dict)
    # Items TMDb returned per facet, before the per-list cap.
    facet_totals: dict[str, int] = Field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.tmdb_id}"


class RequestOutcome(BaseModel):
    """Result of one requested operation; failures are data, not exceptions."""

    index: int = 0
    operation: str
    status: Literal["ok", "partial", "error"] = "ok"
    error: str | None = None
    entities: list[Entity] = Field(default_factory=list)
    items: list[Entity] = Field(default_factory=list)
    total_results: int | None = None
    reference: list[dict[str, Any]] = Field(default_factory=list)
    reference_total: int | None = None
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    skipped_for_budget: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    # Filters a discover really applied (resolved names and IDs, sort, rating range): the answer
    # must be able to say what the list is a list of.
    applied_filters: dict[str, Any] = Field(default_factory=dict)
    # Data source that must be credited when this outcome reaches the user.
    attribution: str | None = None
