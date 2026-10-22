"""Render the RAG steps: chunks retrieved (K largo) and chunks kept after the rerank."""
from __future__ import annotations

from turn import TraceStep

from .blocks import print_chunks, print_retrieval_compact, print_retrieval_query


def render_retrieval(step: TraceStep, language: str | None = None) -> None:
    signals = step.data.get("signals") or {}
    print_retrieval_query(step.data.get("embedded_text"), signals.get("genres") or [])
    chunks = step.data.get("chunks", [])
    print_retrieval_compact(f"K LARGO — {len(chunks)} CHUNK RECUPERATI", chunks, "📚")


def render_rerank(step: TraceStep, language: str | None = None) -> None:
    chunks = step.data.get("chunks", [])
    print_chunks(f"RERANKING — {len(chunks)} CHUNK SELEZIONATI", chunks, "🏆")
