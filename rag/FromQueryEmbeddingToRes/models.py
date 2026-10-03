from __future__ import annotations

from enum import Enum

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


class RagResult(BaseModel):
    query: str
    search_mode: SearchMode
    rerank_backend: RerankBackend
    answer: str
    chunks: list[RagChunk]
    input_tokens: int | None = None
    output_tokens: int | None = None


class RagToolInput(BaseModel):
    """Run the NetflixScout RAG pipeline on a natural language query."""

    query: str = Field(min_length=1)


class QuerySignals(BaseModel):
    """Structured retrieval intent extracted from a user query."""

    positive_signals: list[str] = Field(default_factory=list)
    negative_signals: list[str] = Field(default_factory=list)
    hard_exclusions: list[str] = Field(default_factory=list)
