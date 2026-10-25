"""Render a turn on the terminal, step by step, as it happens or replayed afterwards.

Glue only. The turn story (what is searched, where, how it went) comes from the shared
`presenters/story_view.py`; each tool step is delegated to the renderer in its own folder
(`rag/`, `db/`, `api/`, `youtube/`, `wikipedia/`) via `STEP_RENDERERS`.
"""
from __future__ import annotations

from collections.abc import Callable

from turn import (
    STEP_DB_QUERY,
    STEP_RERANK,
    STEP_RETRIEVAL,
    STEP_TMDB_CALLS,
    STEP_WIKIPEDIA_CALLS,
    STEP_YOUTUBE_CALLS,
    StoryLine,
    TraceStep,
    TurnResult,
)

from ..story_view import STORY_STEP_KINDS, StoryBuilder
from .api import render_tmdb_calls
from .blocks import (
    print_answer_end,
    print_answer_header,
    print_answer_text,
    print_compact_notice,
    print_final_answer,
    print_generic_step,
    print_story_line,
)
from .db import render_db_query
from .rag import render_rerank, render_retrieval
from .wikipedia import render_wikipedia_calls
from .youtube import render_youtube_calls

# A renderer gets the step and the turn language ("it" | "en") for its labels.
StepRenderer = Callable[[TraceStep, str], None]

# Tool steps only: the flow steps (classification, query used, tool chosen and its outcome,
# planning) are told by the story lines, in `story_view`.
STEP_RENDERERS: dict[str, StepRenderer] = {
    STEP_RETRIEVAL: render_retrieval,
    STEP_RERANK: render_rerank,
    STEP_DB_QUERY: render_db_query,
    STEP_TMDB_CALLS: render_tmdb_calls,
    STEP_YOUTUBE_CALLS: render_youtube_calls,
    STEP_WIKIPEDIA_CALLS: render_wikipedia_calls,
}


def _render_unknown(step: TraceStep, language: str) -> None:
    print_generic_step(step.title, step.data)


class TerminalObserver:
    """Prints the turn while it happens: story lines and the block of each tool step."""

    def __init__(self, language: str = "it") -> None:
        # Live, the language is learned from the `classification` step.
        self._story = StoryBuilder(language)
        # The answer is printed as it arrives: the header comes with the first visible text.
        self._answer_started = False

    def _show(self, lines: list[StoryLine]) -> None:
        for line in lines:
            print_story_line(line)

    def status(self, stage: str) -> None:
        self._show(self._story.status(stage))

    def step(self, step: TraceStep) -> None:
        self._show(self._story.step(step))
        if step.kind not in STORY_STEP_KINDS:
            STEP_RENDERERS.get(step.kind, _render_unknown)(step, self._story.language)

    def answer_delta(self, text: str) -> None:
        if not self._answer_started:
            text = text.lstrip()  # no empty lines between the header and the answer
            if not text:
                return
            print_answer_header()
            self._answer_started = True
        print_answer_text(text)


def render(turn: TurnResult, *, streamed: bool = False) -> None:
    """Print the end of a turn. `streamed`: a `TerminalObserver` already printed the steps and
    the answer as they came, so only the end of the answer is left."""
    if streamed:
        print_answer_end()
    else:
        observer = TerminalObserver(turn.language)
        for step in turn.steps:
            observer.step(step)
        print_final_answer(turn.answer)
    if turn.history_compacted:
        print_compact_notice()
