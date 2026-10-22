"""Render a `TurnResult` as the full step-by-step report on the terminal.

Glue only: the flow steps shared by every tool are rendered here, each tool step is
delegated to the renderer in its own folder (`rag/`, `db/`, `api/`) via `STEP_RENDERERS`.
"""
from __future__ import annotations

from collections.abc import Callable

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

from .api import render_tmdb_calls
from .blocks import (
    print_classification,
    print_compact_notice,
    print_final_answer,
    print_generic_step,
    print_query_used,
    print_tool_selection,
)
from .db import render_db_query
from .rag import render_rerank, render_retrieval

# A renderer gets the step and the turn language ("it" | "en") for its labels.
StepRenderer = Callable[[TraceStep, str], None]


def _render_query_rewrite(step: TraceStep, language: str) -> None:
    print_query_used(step.data.get("original", ""), step.data.get("used", ""), bool(step.data.get("rewritten")))


CLARIFICATION_LABELS = {
    "it": "nessuno: richiesta di chiarimento",
    "en": "none: asking for clarification",
}


def _render_tool_selection(step: TraceStep, language: str) -> None:
    if step.data.get("clarification"):
        print_tool_selection(CLARIFICATION_LABELS.get(language, CLARIFICATION_LABELS["en"]))
        return
    print_tool_selection(step.data.get("tool", "?"))


def _render_classification(step: TraceStep, language: str) -> None:
    print_classification(step.data.get("is_cinema"), step.data.get("is_italian"))


STEP_RENDERERS: dict[str, StepRenderer] = {
    STEP_CLASSIFICATION: _render_classification,
    STEP_QUERY_REWRITE: _render_query_rewrite,
    STEP_TOOL_SELECTION: _render_tool_selection,
    STEP_RETRIEVAL: render_retrieval,
    STEP_RERANK: render_rerank,
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
