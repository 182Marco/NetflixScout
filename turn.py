"""Channel-neutral result of one chat turn.

The core (`app.handle_query`) produces a `TurnResult` and never prints. Each output
channel in `presenters/` decides how to show it (terminal text, web payload, ...).
"""
from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

# Known step kinds. Tools may add new ones: presenters must fall back gracefully.
STEP_CLASSIFICATION = "classification"
STEP_QUERY_REWRITE = "query_rewrite"
STEP_TOOL_SELECTION = "tool_selection"
# Multi-tool turns only: the parts of the request, the tools that ran and why the loop stopped.
STEP_PLANNING = "planning"
# One per tool run, after it: how long it took and whether it found something.
STEP_TOOL_OUTCOME = "tool_outcome"
STEP_RETRIEVAL = "retrieval"
STEP_RERANK = "rerank"
STEP_DB_QUERY = "db_query"
STEP_TMDB_CALLS = "tmdb_calls"
STEP_YOUTUBE_CALLS = "youtube_calls"
STEP_WIKIPEDIA_CALLS = "wikipedia_calls"

# Tool parameter set by `handle_query` with the turn language ("it" | "en") from the
# classifier. Tools that do not use it ignore it.
TOOL_PARAM_TURN_LANGUAGE = "turn_language"

# Tool parameter set by the orchestrator: identifies the turn. A turn can run several tools,
# so per-turn limits (TMDb calls, YouTube searches) are counted per `turn_id`, not per run.
TOOL_PARAM_TURN_ID = "turn_id"


# Result of one tool run, set by the tool in `result["outcome"]` (outside `metadata`, so it
# never reaches the LLM prompt). `reason` is a short code the presenters turn into a sentence.
OUTCOME_OK = "ok"
OUTCOME_EMPTY = "empty"
OUTCOME_ERROR = "error"

# Optional key of a tool result (outside `metadata`, so outside the final prompt): the tool says it
# has more to give and describes what it already gave, so the orchestrator asks the planner whether
# to go on (`{"available": bool, "reasons": [str], "summary": str}`). Tools without it are unaffected.
RESULT_FOLLOW_UP = "follow_up"


def tool_outcome(status: str, reason: str | None = None) -> dict[str, str | None]:
    return {"status": status, "reason": reason}


class TraceStep(BaseModel):
    """One step of the procedure, in execution order."""

    kind: str
    title: str
    data: dict[str, Any] = Field(default_factory=dict)


# Moments of a turn that have no step of their own, shown while the user waits.
STAGE_UNDERSTANDING = "understanding"
STAGE_ANSWERING = "answering"


class StoryLine(BaseModel):
    """One short, non-technical sentence of the turn story, the same for every channel.

    `level` is how to show it (the terminal picks an emoji, the web an icon): `progress`
    (work in progress), `info`, `ok`, `warn`.
    """

    level: Literal["progress", "info", "ok", "warn"]
    text: str
    tool: str | None = None


class TurnObserver(Protocol):
    """Receives the turn while it happens. The core never prints: a channel implements this.

    `step` gets every `TraceStep` as soon as it exists; `status` gets a passing stage
    (`STAGE_*`) that is not a step and is not kept in `TurnResult.steps`; `answer_delta` gets
    the text of the final answer as it is written. Implementations
    must be quick: they run inside the turn.
    """

    def step(self, step: TraceStep) -> None:
        ...

    def status(self, stage: str) -> None:
        ...

    def answer_delta(self, text: str) -> None:
        """A piece of the final answer, in order, while the model writes it. Every answer
        (also a block message, a clarification question or a fallback) arrives as one or more
        deltas; a channel does not wait for `TurnResult.answer` to show it."""
        ...


class NullObserver:
    def step(self, step: TraceStep) -> None:
        pass

    def status(self, stage: str) -> None:
        pass

    def answer_delta(self, text: str) -> None:
        pass


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
    # The same story the observer showed live (see `presenters/story_view.py`).
    story: list[StoryLine] = Field(default_factory=list)
    history: list[dict[str, str]] = Field(default_factory=list)
    history_compacted: bool = False
    # Web only: raw list references from the final answer call, checked by `web_lists`.
    item_refs: list[Any] = Field(default_factory=list)
