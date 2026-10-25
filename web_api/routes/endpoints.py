"""The endpoints. Thin: they validate, call the store and the runner, and answer."""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse
from openai import OpenAI

from ..conversations.store import (
    ConversationStore,
    create_conversation,
    delete_conversation,
    get_conversation,
)
from ..schemas.requests import MessageRequest
from ..schemas.responses import ConversationCreated, ConversationInfo
from ..settings import WebApiSettings
from ..streaming.runner import launch_turn, stream_events
from ..streaming.sse import SSE_HEADERS
from .errors import MessageTooLong

router = APIRouter()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class WebApiState:
    """What the endpoints share; built by the server at startup and kept in `app.state`."""

    settings: WebApiSettings
    store: ConversationStore
    bot_app: dict[str, Any]
    client: OpenAI


def _state(request: Request) -> WebApiState:
    state: WebApiState = request.app.state.web_api
    return state


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/conversations", status_code=201)
def open_conversation(request: Request) -> ConversationCreated:
    conv = create_conversation(_state(request).store, time.monotonic(), now_iso())
    return ConversationCreated(conversation_id=conv.id, created_at=conv.created_at)


@router.get("/conversations/{conversation_id}")
def read_conversation(conversation_id: str, request: Request) -> ConversationInfo:
    conv = get_conversation(_state(request).store, conversation_id)
    return ConversationInfo(conversation_id=conv.id, busy=conv.busy, turns_completed=conv.turns_completed)


@router.delete("/conversations/{conversation_id}", status_code=204)
def close_conversation(conversation_id: str, request: Request) -> Response:
    delete_conversation(_state(request).store, conversation_id)
    return Response(status_code=204)


@router.post("/conversations/{conversation_id}/messages")
async def send_message(conversation_id: str, body: MessageRequest, request: Request) -> StreamingResponse:
    state = _state(request)
    if len(body.content) > state.settings.max_message_chars:
        raise MessageTooLong()
    conv = get_conversation(state.store, conversation_id)
    sub = launch_turn(state.store, conv, body.content, state.bot_app, state.client)
    return StreamingResponse(
        stream_events(sub, state.settings.heartbeat_seconds),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
