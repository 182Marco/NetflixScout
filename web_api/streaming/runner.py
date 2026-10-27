"""Runs one turn in a worker thread and turns what happens into the events of a subscription.

The turn belongs to the server, not to the client: it runs to the end and commits its history
even if the stream is closed, and the conversation stays busy until then. A closed subscription
only stops collecting events.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

from app import handle_query
from preferences import Resolution, resolve_preferences
from presenters.web import WebObserver
from presenters.web.observer import EVENT_ANSWER_DELTA, Emit
from turn import TurnResult
from web_lists import final_output

from ..conversations.store import Conversation, ConversationStore, begin_turn, finish_turn
from ..schemas.events import (
    END,
    ERROR_INTERNAL,
    ERROR_TURN_FAILED,
    EVENT_ERROR,
    EVENT_TURN_START,
    End,
    ErrorEvent,
    SseEvent,
    TurnStart,
)
from .events import EventPayload, final_events
from .sse import drain


@dataclass
class Subscription:
    """The events of one turn for the one client reading them. Used only in the loop thread,
    except `closed`, which the worker also reads to skip work nobody will see."""

    queue: asyncio.Queue[SseEvent | End] = field(default_factory=asyncio.Queue)
    closed: bool = False
    last_id: int = 0


def deliver(sub: Subscription, name: str, data: dict[str, Any]) -> None:
    """Queue an event; a closed subscription drops it, so the queue never grows for a gone client."""
    if sub.closed:
        return
    sub.last_id += 1
    sub.queue.put_nowait(SseEvent(sub.last_id, name, data))


def deliver_end(sub: Subscription) -> None:
    if not sub.closed:
        sub.queue.put_nowait(END)


def close_subscription(sub: Subscription) -> None:
    """The client is gone: empty the queue and ignore everything that comes next."""
    sub.closed = True
    while not sub.queue.empty():
        sub.queue.get_nowait()


def thread_emitter(loop: asyncio.AbstractEventLoop, sub: Subscription, streamed: list[str]) -> Emit:
    """The `emit` of the `WebObserver`, called from the worker thread."""

    def emit(name: str, data: dict[str, Any]) -> None:
        if name == EVENT_ANSWER_DELTA:
            streamed.append(data["text"])
        if not sub.closed:
            loop.call_soon_threadsafe(deliver, sub, name, data)

    return emit


async def _run_turn(
    sub: Subscription,
    store: ConversationStore,
    conv: Conversation,
    turn_number: int,
    content: str,
    bot_app: dict[str, Any],
    client: OpenAI,
    resolution: Resolution,
) -> None:
    streamed: list[str] = []
    turn: TurnResult | None = None
    failure: EventPayload | None = None
    try:
        start = TurnStart(
            conversation_id=conv.id,
            turn=turn_number,
            preferences=resolution.preferences.as_dict(),
            ignored_preferences=resolution.ignored,
        )
        deliver(sub, EVENT_TURN_START, start.model_dump())
        observer = WebObserver(thread_emitter(asyncio.get_running_loop(), sub, streamed))
        turn = await asyncio.to_thread(
            handle_query, bot_app, content, conv.history, client, observer, final_output(), resolution.preferences
        )
    except asyncio.CancelledError:
        failure = (EVENT_ERROR, ErrorEvent(code=ERROR_INTERNAL, message="The server is stopping.").model_dump())
        raise
    except Exception:
        failure = (EVENT_ERROR, ErrorEvent(code=ERROR_TURN_FAILED, message="The turn failed; try again.").model_dump())
    finally:
        # The one end of the turn: commit what the bot finished, free the conversation.
        finish_turn(conv, turn.history if turn else None, time.monotonic())
        _close_stream(sub, turn, failure, "".join(streamed))


def _close_stream(sub: Subscription, turn: TurnResult | None, failure: EventPayload | None, streamed: str) -> None:
    try:
        events = final_events(turn, streamed) if turn else [failure or (EVENT_ERROR, {"code": ERROR_INTERNAL, "message": ""})]
    except Exception:
        events = [(EVENT_ERROR, ErrorEvent(code=ERROR_INTERNAL, message="The answer could not be sent.").model_dump())]
    for name, data in events:
        deliver(sub, name, data)
    deliver_end(sub)


def launch_turn(
    store: ConversationStore,
    conv: Conversation,
    content: str,
    bot_app: dict[str, Any],
    client: OpenAI,
    resolution: Resolution | None = None,
) -> Subscription:
    """Start the turn and return its events. Raises `TurnInProgress` if the conversation is busy.
    `resolution` holds the settings of this turn; without it every default applies."""
    turn_number = begin_turn(conv, time.monotonic())
    sub = Subscription()
    task = asyncio.get_running_loop().create_task(
        _run_turn(sub, store, conv, turn_number, content, bot_app, client, resolution or resolve_preferences(None))
    )
    store.tasks.add(task)
    task.add_done_callback(store.tasks.discard)
    return sub


async def stream_events(sub: Subscription, heartbeat_seconds: float) -> AsyncIterator[str]:
    """The wire text of a turn. When the client leaves (the generator is closed or cancelled) the
    subscription is closed; the turn itself goes on."""
    try:
        async for text in drain(sub.queue, heartbeat_seconds):
            yield text
    finally:
        close_subscription(sub)
