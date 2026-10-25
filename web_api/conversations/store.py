"""Conversations in memory: the history of each and whether a turn is running.

Every function here runs in the event loop thread and never awaits, so a check followed by a
change (`begin_turn`) cannot be interleaved with another request. The turn worker thread never
touches the store: it gets a history and returns the new one, and the loop commits it.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field

History = list[dict[str, str]]


class ConversationNotFound(Exception):
    pass


class TurnInProgress(Exception):
    pass


@dataclass
class Conversation:
    id: str
    created_at: str
    last_used: float
    history: History = field(default_factory=list)
    busy: bool = False
    turns_completed: int = 0


@dataclass
class ConversationStore:
    ttl_seconds: float
    max_conversations: int
    conversations: dict[str, Conversation] = field(default_factory=dict)
    # Strong references to the running turn tasks (the loop keeps only weak ones).
    tasks: set[asyncio.Task[None]] = field(default_factory=set)


def evict(store: ConversationStore, now: float) -> None:
    """Drop idle conversations unused for the TTL, then the least recently used idle ones while the
    store is over its size. A conversation with a running turn is never dropped."""
    idle = [c for c in store.conversations.values() if not c.busy]
    for conv in idle:
        if now - conv.last_used > store.ttl_seconds:
            del store.conversations[conv.id]
    idle = sorted((c for c in store.conversations.values() if not c.busy), key=lambda c: c.last_used)
    while len(store.conversations) >= store.max_conversations and idle:
        del store.conversations[idle.pop(0).id]


def create_conversation(store: ConversationStore, now: float, created_at: str) -> Conversation:
    evict(store, now)
    conv = Conversation(id=uuid.uuid4().hex, created_at=created_at, last_used=now)
    store.conversations[conv.id] = conv
    return conv


def get_conversation(store: ConversationStore, conversation_id: str) -> Conversation:
    conv = store.conversations.get(conversation_id)
    if conv is None:
        raise ConversationNotFound(conversation_id)
    return conv


def begin_turn(conv: Conversation, now: float) -> int:
    """Mark the conversation busy and return the number of the turn (1-based)."""
    if conv.busy:
        raise TurnInProgress(conv.id)
    conv.busy = True
    conv.last_used = now
    return conv.turns_completed + 1


def finish_turn(conv: Conversation, history: History | None, now: float) -> None:
    """The one place that ends a turn: commit `history` (None: leave it as it was) and free the
    conversation. Called when the work is really over, whether or not a client is still listening."""
    if history is not None:
        conv.history = history
        conv.turns_completed += 1
    conv.busy = False
    conv.last_used = now


def delete_conversation(store: ConversationStore, conversation_id: str) -> None:
    conv = get_conversation(store, conversation_id)
    if conv.busy:
        raise TurnInProgress(conv.id)
    del store.conversations[conversation_id]
