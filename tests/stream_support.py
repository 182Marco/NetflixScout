"""Streams of the Responses API for the offline tests, built with the SDK's own event classes
(`openai==3.21.0`): a change of names or fields in the pinned SDK breaks these helpers."""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from openai.types.responses import (
    ResponseCompletedEvent,
    ResponseErrorEvent,
    ResponseFailedEvent,
    ResponseIncompleteEvent,
    ResponseRefusalDeltaEvent,
    ResponseRefusalDoneEvent,
    ResponseTextDeltaEvent,
    ResponseTextDoneEvent,
)

# Event types the orchestrator reads, with the SDK class that carries each one.
HANDLED_EVENT_CLASSES = {
    "response.output_text.delta": ResponseTextDeltaEvent,
    "response.refusal.delta": ResponseRefusalDeltaEvent,
    "response.refusal.done": ResponseRefusalDoneEvent,
    "response.completed": ResponseCompletedEvent,
    "response.incomplete": ResponseIncompleteEvent,
    "response.failed": ResponseFailedEvent,
    "error": ResponseErrorEvent,
}


def delta(text: str, n: int = 0) -> ResponseTextDeltaEvent:
    return ResponseTextDeltaEvent(
        content_index=0, delta=text, item_id="msg_1", logprobs=[], output_index=0,
        sequence_number=n, type="response.output_text.delta",
    )


def text_done(text: str, n: int = 0) -> ResponseTextDoneEvent:
    return ResponseTextDoneEvent(
        content_index=0, item_id="msg_1", logprobs=[], output_index=0, sequence_number=n,
        text=text, type="response.output_text.done",
    )


def refusal_delta(text: str, n: int = 0) -> ResponseRefusalDeltaEvent:
    return ResponseRefusalDeltaEvent(
        content_index=0, delta=text, item_id="msg_1", output_index=0, sequence_number=n,
        type="response.refusal.delta",
    )


def refusal_done(text: str, n: int = 0) -> ResponseRefusalDoneEvent:
    return ResponseRefusalDoneEvent(
        content_index=0, item_id="msg_1", output_index=0, refusal=text, sequence_number=n,
        type="response.refusal.done",
    )


# The nested `Response` is not read by the orchestrator: these three skip its validation.
def completed(n: int = 0) -> ResponseCompletedEvent:
    return ResponseCompletedEvent.model_construct(type="response.completed", response=None, sequence_number=n)


def incomplete(n: int = 0) -> ResponseIncompleteEvent:
    return ResponseIncompleteEvent.model_construct(type="response.incomplete", response=None, sequence_number=n)


def failed(n: int = 0) -> ResponseFailedEvent:
    return ResponseFailedEvent.model_construct(type="response.failed", response=None, sequence_number=n)


def error_event(message: str = "boom", n: int = 0) -> ResponseErrorEvent:
    return ResponseErrorEvent(message=message, sequence_number=n, type="error")


def chunks(text: str, size: int = 7) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]


def text_events(text: str, size: int = 7, *, end: Any = None) -> list[Any]:
    """Deltas of `text` followed by `end` (default: the `completed` event)."""
    events: list[Any] = [delta(piece, n) for n, piece in enumerate(chunks(text, size))]
    events.append(text_done(text, len(events)))
    events.append(completed(len(events)) if end is None else end)
    return events


class Stream:
    """An iterator of events that can raise after them, like a dropped connection."""

    def __init__(self, events: list[Any], then: Exception | None = None) -> None:
        self.events = list(events)
        self.then = then
        self.closed = False

    def __iter__(self) -> Iterator[Any]:
        yield from self.events
        if self.then is not None:
            raise self.then

    def close(self) -> None:
        self.closed = True


def reply(text: str, kwargs: dict[str, Any]) -> Any:
    """What a fake `responses.create` returns: a stream of `text` for the streamed final answer,
    a plain response (`output_text`) for the other calls."""
    if kwargs.get("stream"):
        return Stream(text_events(text))
    return type("Response", (), {"output_text": text})()
