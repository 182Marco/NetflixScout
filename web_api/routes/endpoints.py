"""The endpoints. Thin: they validate, call the store and the runner, and answer."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse
from openai import OpenAI
from preferences import Resolution, public_schema, resolve_preferences

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
logger = logging.getLogger("web_api.preferences")


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


@router.get("/settings")
def read_settings() -> dict[str, Any]:
    """The public definition of the user settings (fields, options, defaults), nothing else."""
    return public_schema()


def _log_preference_issues(conversation_id: str, resolution: Resolution) -> None:
    """A preference problem never fails the request: it is logged and the default is used."""
    for issue in resolution.issues:
        logger.warning(
            "preference ignored: field=%s code=%s value=%s conversation=%s",
            issue.field,
            issue.code,
            issue.value,
            conversation_id,
        )


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
    resolution = resolve_preferences(body.preferences)
    _log_preference_issues(conversation_id, resolution)
    sub = launch_turn(state.store, conv, body.content, state.bot_app, state.client, resolution)
    return StreamingResponse(
        stream_events(sub, state.settings.heartbeat_seconds),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
