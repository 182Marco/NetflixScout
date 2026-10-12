"""Render a `TurnResult` as the full step-by-step report on the terminal."""
from __future__ import annotations

from collections.abc import Callable

from turn import (
    STEP_CLASSIFICATION,
    STEP_QUERY_REWRITE,
    STEP_RERANK,
    STEP_RETRIEVAL,
    STEP_TOOL_SELECTION,
    TraceStep,
    TurnResult,
)

from .blocks import (
    _print_chunks,
    _print_retrieval_compact,
    print_compact_notice,
    print_final_answer,
    print_generic_step,
    print_query_used,
    print_retrieval_query,
    print_tool_selection,
)


def _render_retrieval(step: TraceStep) -> None:
    signals = step.data.get("signals") or {}
    print_retrieval_query(step.data.get("embedded_text"), signals.get("genres") or [])
    chunks = step.data.get("chunks", [])
    _print_retrieval_compact(f"K LARGO — {len(chunks)} CHUNK RECUPERATI", chunks, "📚")


def _render_rerank(step: TraceStep) -> None:
    chunks = step.data.get("chunks", [])
    _print_chunks(f"RERANKING — {len(chunks)} CHUNK SELEZIONATI", chunks, "🏆")


def _render_query_rewrite(step: TraceStep) -> None:
    print_query_used(step.data.get("original", ""), step.data.get("used", ""), bool(step.data.get("rewritten")))


def _render_tool_selection(step: TraceStep) -> None:
    print_tool_selection(step.data.get("tool", "?"))


def _render_silently(step: TraceStep) -> None:
    """Steps kept in the data but not shown on the terminal (as before the refactor)."""


STEP_RENDERERS: dict[str, Callable[[TraceStep], None]] = {
    STEP_CLASSIFICATION: _render_silently,
    STEP_QUERY_REWRITE: _render_query_rewrite,
    STEP_TOOL_SELECTION: _render_tool_selection,
    STEP_RETRIEVAL: _render_retrieval,
    STEP_RERANK: _render_rerank,
}


def _render_unknown(step: TraceStep) -> None:
    print_generic_step(step.title, step.data)


def render(turn: TurnResult) -> None:
    for step in turn.steps:
        STEP_RENDERERS.get(step.kind, _render_unknown)(step)
    print_final_answer(turn.answer)
    if turn.history_compacted:
        print_compact_notice()
