"""What the film retriever hands to the tool: the structured evidence (`RagResult`), never an answer."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RagChunk(BaseModel):
    id: str
    testo: str
    score: float
    source: str | None = None
    movie_id: str | None = None
    title: str | None = None
    release_date: str | None = None
    release_year: str | None = None
    genres: str | None = None
    cast: str | None = None
    original_title: str | None = None
    directors: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    duration_minutes: int | None = None
    imdb_id: str | None = None
    wikipedia_url: str | None = None
    work_format: str | None = None
    unverified: bool = False


class ReferenceTitle(BaseModel):
    """A film the user cites as a model ("like X") or as a contrast ("not like Y")."""

    title: str
    year: int | None = None  # only when the parser is sure of it (it tells homonyms apart)


class QuerySignals(BaseModel):
    """The retrieval intent as the presenters show it (the parser's `Signals`, reduced to what the trace reports)."""

    positive_signals: list[str] = Field(default_factory=list)
    negative_signals: list[str] = Field(default_factory=list)
    hard_exclusions: list[str] = Field(default_factory=list)
    semantic_query: str = ""
    avoid_query: str = ""
    like_titles: list[ReferenceTitle] = Field(default_factory=list)
    avoid_titles: list[ReferenceTitle] = Field(default_factory=list)
    genres: list[str] = Field(default_factory=list)
    excluded_genres: list[str] = Field(default_factory=list)
    # Diagnostic only (FASE 19K): the filters the parser actually produced (year_from, year_to, countries, directors, actors, rare_terms), non-empty ones only.
    # Never read by the retrieval or by the presenters; it exists so that a trace shows what the parser decided.
    filters: dict[str, Any] = Field(default_factory=dict)


class RagResult(BaseModel):
    query: str
    chunks: list[RagChunk]
    candidates: list[RagChunk] = Field(default_factory=list)  # the pool shown, before the cut
    reranked: list[RagChunk] = Field(default_factory=list)  # the pool in the reorder's order
    rerank_engine: str | None = None  # who ranked it: `llm` or `penalty_after_error`
    signals: QuerySignals | None = None
    embedded_text: str | None = None
    rerank_query: str | None = None
    references: dict[str, Any] = Field(default_factory=dict)  # films cited as "like X, not like Y": what was resolved
    films: list[dict[str, Any]] = Field(default_factory=list)  # what the answer needs per film (no URLs)
    notes: dict[str, Any] = Field(default_factory=dict)  # parser failure, filters dropped, contradiction
