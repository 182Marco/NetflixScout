from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


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


class QuerySignals(BaseModel):
    """Structured retrieval intent extracted from a user query."""

    positive_signals: list[str] = Field(default_factory=list)
    negative_signals: list[str] = Field(default_factory=list)
    hard_exclusions: list[str] = Field(default_factory=list)
    # English sentence embedded for semantic search (the corpus is English plot summaries).
    semantic_query: str = ""
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
    # Status of each extracted constraint on the final chunks (`constraints.constraint_report`).
    constraints: dict[str, Any] = Field(default_factory=dict)


class RagToolInput(BaseModel):
    """Run the NetflixScout RAG pipeline on a natural language query."""

    query: str = Field(min_length=1)
