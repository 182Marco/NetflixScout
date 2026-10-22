"""Render a `TurnResult` as the full step-by-step report on the terminal."""
from __future__ import annotations

from collections.abc import Callable

from tmdb.presenters.terminal import render_tmdb_calls
from turn import (
    STEP_CLASSIFICATION,
    STEP_DB_QUERY,
    STEP_QUERY_REWRITE,
    STEP_RERANK,
    STEP_RETRIEVAL,
    STEP_TMDB_CALLS,
    STEP_TOOL_SELECTION,
    TraceStep,
    TurnResult,
)

from .blocks import (
    _print_chunks,
    _print_retrieval_compact,
    print_classification,
    print_compact_notice,
    print_final_answer,
    print_generic_step,
    print_query_used,
    print_retrieval_query,
    print_tool_selection,
)
from .movie_db import render_db_query

# A renderer gets the step and the turn language ("it" | "en") for its labels.
StepRenderer = Callable[[TraceStep, str], None]


def _render_retrieval(step: TraceStep, language: str) -> None:
    signals = step.data.get("signals") or {}
    print_retrieval_query(step.data.get("embedded_text"), signals.get("genres") or [])
    chunks = step.data.get("chunks", [])
    _print_retrieval_compact(f"K LARGO — {len(chunks)} CHUNK RECUPERATI", chunks, "📚")


def _render_rerank(step: TraceStep, language: str) -> None:
    chunks = step.data.get("chunks", [])
    _print_chunks(f"RERANKING — {len(chunks)} CHUNK SELEZIONATI", chunks, "🏆")


def _render_query_rewrite(step: TraceStep, language: str) -> None:
    print_query_used(step.data.get("original", ""), step.data.get("used", ""), bool(step.data.get("rewritten")))


def _render_tool_selection(step: TraceStep, language: str) -> None:
    print_tool_selection(step.data.get("tool", "?"))


def _render_classification(step: TraceStep, language: str) -> None:
    print_classification(step.data.get("is_cinema"), step.data.get("is_italian"))


STEP_RENDERERS: dict[str, StepRenderer] = {
    STEP_CLASSIFICATION: _render_classification,
    STEP_QUERY_REWRITE: _render_query_rewrite,
    STEP_TOOL_SELECTION: _render_tool_selection,
    STEP_RETRIEVAL: _render_retrieval,
    STEP_RERANK: _render_rerank,
    STEP_DB_QUERY: render_db_query,
    STEP_TMDB_CALLS: render_tmdb_calls,
}


def _render_unknown(step: TraceStep, language: str) -> None:
    print_generic_step(step.title, step.data)


def render(turn: TurnResult) -> None:
    for step in turn.steps:
        STEP_RENDERERS.get(step.kind, _render_unknown)(step, turn.language)
    print_final_answer(turn.answer)
    if turn.history_compacted:
        print_compact_notice()
