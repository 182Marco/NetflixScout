"""Channel-neutral view of the RAG steps (`retrieval`, `rerank`), shared by the terminal and web.

Both channels show the same chunks (title, year, score, genres, cast, plot preview) and the
same query text; only the format differs. Chunks may be dicts or Pydantic models. Pure: no
printing, no import of the RAG package.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from turn import TraceStep, label_language

PREVIEW_CHARS = 200

RETRIEVAL_TITLE = {
    "it": "K LARGO — {n} CHUNK RECUPERATI",
    "en": "WIDE K — {n} CHUNKS RETRIEVED",
    "de": "WEITES K — {n} CHUNKS ABGERUFEN",
}
RERANK_TITLE = {
    "it": "RERANK ({engine}) — {n} CHUNK RIORDINATI",
    "en": "RERANK ({engine}) — {n} CHUNKS REORDERED",
    "de": "RERANK ({engine}) — {n} CHUNKS NEU GEORDNET",
}
SELECTION_TITLE = {
    "it": "K STRETTO — {n} CHUNK SELEZIONATI",
    "en": "NARROW K — {n} CHUNKS SELECTED",
    "de": "ENGES K — {n} CHUNKS AUSGEWÄHLT",
}
# Who ranked the pool, as shown in the title. A fallback says so: the LLM meant for "not like Y" failed.
ENGINE_LABEL = {
    "cohere": {"it": "Cohere", "en": "Cohere", "de": "Cohere"},
    "llm": {"it": "LLM", "en": "LLM", "de": "LLM"},
    "llm_request": {"it": "LLM", "en": "LLM", "de": "LLM"},
    "cohere_fallback": {
        "it": "Cohere, ripiego dopo l'errore dell'LLM",
        "en": "Cohere, fallback after the LLM failed",
        "de": "Cohere, Ersatz nach LLM-Fehler",
    },
}


class ChunkView(BaseModel):
    id: str | None = None
    # `score` is the number of the step's own stage (similarity at retrieval, the reranker's after it);
    # `similarity` is always the 0-1 retrieval similarity and `rank_before` the place in the wide K.
    score: float | None = None
    similarity: float | None = None
    rank_before: int | None = None
    source: str | None = None
    movie_id: str | None = None
    title: str | None = None
    year: str | None = None
    genres: str | None = None
    cast: str | None = None
    preview: str = ""


class ReferenceView(BaseModel):
    """One movie cited as a reference and what was done with it (never a vector)."""

    title: str
    year: int | None = None
    role: str
    status: str
    source: str | None = None
    matched: str | None = None
    tmdb_calls: int | None = None
    embedding_created: bool | None = None
    reason: str | None = None


class RagStepView(BaseModel):
    kind: str
    title: str
    # Rerank step only: who ranked the pool (`cohere`, `llm`, `llm_request`, `cohere_fallback`).
    engine: str | None = None
    embedded_text: str | None = None
    genres: list[str] = Field(default_factory=list)
    # Retrieval settings of the call and which ones the planner changed (retrieval step only).
    params: dict[str, Any] = Field(default_factory=dict)
    overridden: list[str] = Field(default_factory=list)
    chunks: list[ChunkView] = Field(default_factory=list)
    # Reference films of a "like X, not like Y" request (retrieval step only): steered search, strategy, per-film outcome.
    references: list[ReferenceView] = Field(default_factory=list)
    reference_steered: bool | None = None
    reference_strategy: str | None = None
    reference_note: str | None = None


def _text(value: Any) -> str | None:
    return None if value in (None, "") else str(value)


def _number(value: Any) -> float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _chunk_view(chunk: Any, *, retrieval: bool = False) -> ChunkView:
    if hasattr(chunk, "model_dump"):
        chunk = chunk.model_dump()
    testo = chunk.get("testo", "") or ""
    score = chunk.get("score")
    return ChunkView(
        id=_text(chunk.get("id")),
        score=_number(score),
        similarity=_number(score) if retrieval else _number(chunk.get("similarity")),
        rank_before=chunk.get("rank_before") if isinstance(chunk.get("rank_before"), int) else None,
        source=_text(chunk.get("source")),
        movie_id=_text(chunk.get("movie_id")),
        title=_text(chunk.get("title")),
        year=_text(chunk.get("release_year") or chunk.get("release_date")),
        genres=_text(chunk.get("genres")),
        cast=_text(chunk.get("cast")),
        preview=testo[:PREVIEW_CHARS] + "..." if testo else "",
    )


def _chunks(step: TraceStep, *, retrieval: bool = False) -> list[ChunkView]:
    return [_chunk_view(chunk, retrieval=retrieval) for chunk in step.data.get("chunks") or []]


def _reference_views(data: dict[str, Any]) -> list[ReferenceView]:
    views = []
    for entry in data.get("references") or []:
        detail = entry.get("detail") or {}
        views.append(ReferenceView(
            title=str(entry.get("title") or ""), year=entry.get("year"), role=str(entry.get("role") or ""),
            status=str(entry.get("status") or ""), source=_text(entry.get("source") or detail.get("origin")),
            matched=_text(entry.get("matched_title")), tmdb_calls=detail.get("tmdb_calls"),
            embedding_created=detail.get("embedding_created"), reason=_text(detail.get("reason"))))
    return views


def retrieval_view(step: TraceStep, language: str | None = None) -> RagStepView:
    chunks = _chunks(step, retrieval=True)
    signals = step.data.get("signals") or {}
    refs = step.data.get("references") or {}
    return RagStepView(
        kind=step.kind,
        title=RETRIEVAL_TITLE[label_language(language)].format(n=len(chunks)),
        embedded_text=step.data.get("embedded_text"),
        genres=list(signals.get("genres") or []),
        params=dict((step.data.get("retrieval_params") or {}).get("effective") or {}),
        overridden=list((step.data.get("retrieval_params") or {}).get("overridden") or []),
        chunks=chunks,
        references=_reference_views(refs),
        reference_steered=refs.get("steered") if refs else None,
        reference_strategy=_text(refs.get("strategy")) if refs.get("steered") else None,
        reference_note=_text(refs.get("skipped")),
    )


def rerank_view(step: TraceStep, language: str | None = None) -> RagStepView:
    chunks = _chunks(step)
    engine = _text(step.data.get("backend"))
    label = ENGINE_LABEL.get(engine or "", {}).get(label_language(language), engine or "?")
    return RagStepView(kind=step.kind, title=RERANK_TITLE[label_language(language)].format(n=len(chunks), engine=label),
                       engine=engine, chunks=chunks)


def selection_view(step: TraceStep, language: str | None = None) -> RagStepView:
    chunks = _chunks(step)
    return RagStepView(kind=step.kind, title=SELECTION_TITLE[label_language(language)].format(n=len(chunks)), chunks=chunks)
