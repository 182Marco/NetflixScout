from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SearchMode(str, Enum):
    semantic = "semantic"
    hybrid = "hybrid"
    bm25 = "bm25"


class RerankBackend(str, Enum):
    cohere = "cohere"
    llm = "llm"


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


class ReferenceTitle(BaseModel):
    """A movie the user cites as a model ("like X") or as a contrast ("not like Y")."""

    title: str
    # Release year, only when the parser is sure of it (it tells homonyms apart); null otherwise.
    year: int | None = None


class QuerySignals(BaseModel):
    """Structured retrieval intent extracted from a user query."""

    positive_signals: list[str] = Field(default_factory=list)
    negative_signals: list[str] = Field(default_factory=list)
    hard_exclusions: list[str] = Field(default_factory=list)
    # English sentence embedded for semantic search (the corpus is English plot summaries).
    semantic_query: str = ""
    # English sentence on the themes and tone the user wants to AVOID or be different from (the movie
    # cited as "not like Y", described in plain words). Filled only when `rag.signals.avoid_query` is on.
    avoid_query: str = ""
    # Movies cited as references of closeness / distance (filled only when `rag.signals.reference_titles` is on).
    like_titles: list[ReferenceTitle] = Field(default_factory=list)
    avoid_titles: list[ReferenceTitle] = Field(default_factory=list)
    # Requested genres, in the corpus vocabulary (e.g. "Science Fiction").
    genres: list[str] = Field(default_factory=list)
    # Genres the user rules out ("senza fantascienza"), same vocabulary: checked on the
    # chunk genres metadata, unlike `hard_exclusions`, which only filter titles.
    excluded_genres: list[str] = Field(default_factory=list)


class RagResult(BaseModel):
    query: str
    search_mode: SearchMode
    rerank_backend: RerankBackend
    answer: str | None = None
    chunks: list[RagChunk]
    candidates: list[RagChunk] = Field(default_factory=list)
    input_tokens: int | None = None
    output_tokens: int | None = None
    signals: QuerySignals | None = None
    embedded_text: str | None = None
    # Text sent to the reranker (`retrieval.compose_rerank_query`).
    rerank_query: str | None = None
    # Status of each extracted constraint on the final chunks (`constraints.constraint_report`).
    constraints: dict[str, Any] = Field(default_factory=dict)
    # Reference films ("like X, not like Y"): what was resolved, where each vector came from, whether the search was steered.
    references: dict[str, Any] = Field(default_factory=dict)


class RagToolInput(BaseModel):
    """Run the NetflixScout RAG pipeline on a natural language query.

    The planner chooses `k_finale` and, optionally, `search_mode` (`semantic` or `hybrid`); null
    means the configured default. Candidate pool sizes and genre boost stay fixed (A/B 2026-10-24:
    no measurable gain). Out-of-range or unknown values are clamped or ignored
    (`retrieval_params.resolve_retrieval`).
    """

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    k_finale: int | None = Field(
        default=None,
        description=(
            "How many films to return: the number the user asked for ('un film' = 1, 'dammi 5 film' = 5), "
            "null when no number is given."
        ),
    )
    search_mode: Literal["semantic", "hybrid"] | None = Field(
        default=None,
        description=(
            "null (default) for requests about themes, mood or plot. 'hybrid' adds keyword matching "
            "and helps when the request hinges on concrete words that must appear in the plot: a "
            "character name, a place, an object, a rare term or a quoted phrase."
        ),
    )
