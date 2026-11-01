"""Render the RAG steps: chunks retrieved (K largo), the pool after the rerank, the chunks kept (K stretto)."""
from __future__ import annotations

from turn import TraceStep

from ...rag_view import rerank_view, retrieval_view, selection_view
from .blocks import (
    print_chunks,
    print_references,
    print_retrieval_compact,
    print_retrieval_params,
    print_retrieval_query,
)


def render_retrieval(step: TraceStep, language: str | None = None) -> None:
    language = language or "it"
    view = retrieval_view(step, language)
    print_retrieval_params(view.params, view.overridden, language)
    print_retrieval_query(view.embedded_text, view.genres, language)
    print_references(view, language)
    print_retrieval_compact(view, "📚", scores="similarity")


def render_rerank(step: TraceStep, language: str | None = None) -> None:
    print_retrieval_compact(rerank_view(step, language), "🧠", scores="rerank")


def render_selection(step: TraceStep, language: str | None = None) -> None:
    print_chunks(selection_view(step, language), "🏆", language or "it")
