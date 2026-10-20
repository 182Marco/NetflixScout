"""Channel-neutral result of one chat turn.

The core (`app.handle_query`) produces a `TurnResult` and never prints. Each output
channel in `presenters/` decides how to show it (terminal text, web payload, ...).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# Known step kinds. Tools may add new ones: presenters must fall back gracefully.
STEP_CLASSIFICATION = "classification"
STEP_QUERY_REWRITE = "query_rewrite"
STEP_TOOL_SELECTION = "tool_selection"
STEP_RETRIEVAL = "retrieval"
STEP_RERANK = "rerank"
STEP_DB_QUERY = "db_query"


class TraceStep(BaseModel):
    """One step of the procedure, in execution order."""

    kind: str
    title: str
    data: dict[str, Any] = Field(default_factory=dict)


class TurnResult(BaseModel):
    """Everything that happened while answering one user query."""

    query: str
    language: Literal["it", "en"]
    blocked: bool
    answer: str
    tool: str | None = None
    steps: list[TraceStep] = Field(default_factory=list)
    history: list[dict[str, str]] = Field(default_factory=list)
    history_compacted: bool = False
