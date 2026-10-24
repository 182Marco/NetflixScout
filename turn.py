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
# Multi-tool turns only: the parts of the request, the tools that ran and why the loop stopped.
STEP_PLANNING = "planning"
STEP_RETRIEVAL = "retrieval"
STEP_RERANK = "rerank"
STEP_DB_QUERY = "db_query"
STEP_TMDB_CALLS = "tmdb_calls"
STEP_YOUTUBE_CALLS = "youtube_calls"

# Tool parameter set by `handle_query` with the turn language ("it" | "en") from the
# classifier. Tools that do not use it ignore it.
TOOL_PARAM_TURN_LANGUAGE = "turn_language"

# Tool parameter set by the orchestrator: identifies the turn. A turn can run several tools,
# so per-turn limits (TMDb calls, YouTube searches) are counted per `turn_id`, not per run.
TOOL_PARAM_TURN_ID = "turn_id"


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
    # Every tool run in the turn, in execution order (`tool` is the first one).
    tools: list[str] = Field(default_factory=list)
    steps: list[TraceStep] = Field(default_factory=list)
    history: list[dict[str, str]] = Field(default_factory=list)
    history_compacted: bool = False
