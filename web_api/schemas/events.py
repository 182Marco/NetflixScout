"""The events of the message stream: names, payload models and the queue item.

Order of a turn: `turn_start`, then `status`/`story`/`step`/`answer_delta` as they happen,
`answer_end`, `lists`, `done`; or `error` (and nothing after it) if the turn failed.
`status`, `story`, `step` and `answer_delta` come from `presenters/web/observer.py` and keep its
payloads; the others belong to this package.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict

EVENT_TURN_START: Final = "turn_start"
EVENT_ANSWER_END: Final = "answer_end"
EVENT_LISTS: Final = "lists"
EVENT_DONE: Final = "done"
EVENT_ERROR: Final = "error"

EventName = Literal["turn_start", "status", "story", "step", "answer_delta", "answer_end", "lists", "done", "error"]

ERROR_TURN_FAILED: Final = "turn_failed"
ERROR_INTERNAL: Final = "internal_error"


class TurnStart(BaseModel):
    """`preferences`: the settings applied to this turn (defaults filled in); `ignored_preferences`:
    names of the fields whose value was not valid and fell back to the default."""

    conversation_id: str
    turn: int
    preferences: dict[str, Any] | None = None
    ignored_preferences: list[str] = []


class Status(BaseModel):
    stage: str


class Story(BaseModel):
    level: Literal["progress", "info", "ok", "warn"]
    text: str
    tool: str | None


class Step(BaseModel):
    """A tool step: `kind` plus the fields of its serializer (`presenters/web/<tool>/`)."""

    model_config = ConfigDict(extra="allow")

    kind: str


class AnswerDelta(BaseModel):
    text: str


class AnswerEnd(BaseModel):
    """`replace`: null when the text streamed is the answer (the usual case); otherwise the whole
    answer, which replaces what was shown (see `streaming/events.py:replacement`)."""

    blocked: bool
    language: Literal["it", "en"]
    tool: str | None
    tools: list[str]
    history_compacted: bool
    replace: str | None


class Lists(BaseModel):
    lists: list[dict[str, Any]]


class Done(BaseModel):
    pass


class ErrorEvent(BaseModel):
    code: str
    message: str


# Event name -> payload model (what `chat_stream.md` documents and its test validates).
EVENT_MODELS: Final[dict[str, type[BaseModel]]] = {
    EVENT_TURN_START: TurnStart,
    "status": Status,
    "story": Story,
    "step": Step,
    "answer_delta": AnswerDelta,
    EVENT_ANSWER_END: AnswerEnd,
    EVENT_LISTS: Lists,
    EVENT_DONE: Done,
    EVENT_ERROR: ErrorEvent,
}


@dataclass(frozen=True)
class SseEvent:
    id: int
    name: str
    data: dict[str, Any]


class End:
    """Marks the end of the queue of a turn."""


END: Final = End()
