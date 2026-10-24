"""Channel-neutral view of the RAG steps (`retrieval`, `rerank`), shared by the terminal and web.

Both channels show the same chunks (title, year, score, genres, cast, plot preview) and the
same query text; only the format differs. Chunks may be dicts or Pydantic models. Pure: no
printing, no import of the RAG package.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from turn import TraceStep

PREVIEW_CHARS = 200

RETRIEVAL_TITLE = "K LARGO — {n} CHUNK RECUPERATI"
RERANK_TITLE = "RERANKING — {n} CHUNK SELEZIONATI"


class ChunkView(BaseModel):
    id: str | None = None
    score: float | None = None
    source: str | None = None
    movie_id: str | None = None
    title: str | None = None
    year: str | None = None
    genres: str | None = None
    cast: str | None = None
    preview: str = ""


class RagStepView(BaseModel):
    kind: str
    title: str
    embedded_text: str | None = None
    genres: list[str] = Field(default_factory=list)
    chunks: list[ChunkView] = Field(default_factory=list)


def _text(value: Any) -> str | None:
    return None if value in (None, "") else str(value)


def _chunk_view(chunk: Any) -> ChunkView:
    if hasattr(chunk, "model_dump"):
        chunk = chunk.model_dump()
    testo = chunk.get("testo", "") or ""
    score = chunk.get("score")
    return ChunkView(
        id=_text(chunk.get("id")),
        score=score if isinstance(score, (int, float)) else None,
        source=_text(chunk.get("source")),
        movie_id=_text(chunk.get("movie_id")),
        title=_text(chunk.get("title")),
        year=_text(chunk.get("release_year") or chunk.get("release_date")),
        genres=_text(chunk.get("genres")),
        cast=_text(chunk.get("cast")),
        preview=testo[:PREVIEW_CHARS] + "..." if testo else "",
    )


def _chunks(step: TraceStep) -> list[ChunkView]:
    return [_chunk_view(chunk) for chunk in step.data.get("chunks") or []]


def retrieval_view(step: TraceStep) -> RagStepView:
    chunks = _chunks(step)
    signals = step.data.get("signals") or {}
    return RagStepView(
        kind=step.kind,
        title=RETRIEVAL_TITLE.format(n=len(chunks)),
        embedded_text=step.data.get("embedded_text"),
        genres=list(signals.get("genres") or []),
        chunks=chunks,
    )


def rerank_view(step: TraceStep) -> RagStepView:
    chunks = _chunks(step)
    return RagStepView(kind=step.kind, title=RERANK_TITLE.format(n=len(chunks)), chunks=chunks)
