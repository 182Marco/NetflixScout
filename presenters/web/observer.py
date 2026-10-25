"""Live web channel: the turn as it happens, as named JSON events.

`WebObserver` is the web twin of `presenters/terminal/renderer.py:TerminalObserver`: same
story (`StoryBuilder`), same tool steps (`serialize_step`, like `to_payload`), same answer text,
but each piece goes to `emit(name, data)` instead of the screen. It knows nothing of HTTP: the
transport (`web_api/`) decides what `emit` does.

Events: `status {stage}`, `story {level, text, tool}`, `step {kind, ...}`, `answer_delta {text}`.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from turn import TraceStep

from ..story_view import STORY_STEP_KINDS, StoryBuilder
from .payload import serialize_step

EVENT_STATUS = "status"
EVENT_STORY = "story"
EVENT_STEP = "step"
EVENT_ANSWER_DELTA = "answer_delta"

Emit = Callable[[str, dict[str, Any]], None]


class WebObserver:
    def __init__(self, emit: Emit, language: str = "it") -> None:
        self._emit = emit
        # Live, the language is learned from the `classification` step.
        self._story = StoryBuilder(language)

    def _story_events(self, lines: list[Any]) -> None:
        for line in lines:
            self._emit(EVENT_STORY, line.model_dump(mode="json"))

    def status(self, stage: str) -> None:
        self._emit(EVENT_STATUS, {"stage": stage})
        self._story_events(self._story.status(stage))

    def step(self, step: TraceStep) -> None:
        self._story_events(self._story.step(step))
        if step.kind not in STORY_STEP_KINDS:
            self._emit(EVENT_STEP, serialize_step(step, self._story.language))

    def answer_delta(self, text: str) -> None:
        if text:
            self._emit(EVENT_ANSWER_DELTA, {"text": text})
