"""JSON-ready form of the RAG steps. Same content as the terminal (shared `rag_view`)."""
from __future__ import annotations

from typing import Any

from turn import STEP_RERANK, TraceStep

from ...rag_view import rerank_view, retrieval_view


def serialize_rag_step(step: TraceStep, language: str | None = None) -> dict[str, Any]:
    view = rerank_view(step, language) if step.kind == STEP_RERANK else retrieval_view(step, language)
    return view.model_dump(mode="json")
