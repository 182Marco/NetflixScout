"""The FastAPI application: CORS, error handlers, endpoints and the bot built at startup."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI

from app import build_ready_app

from .conversations.store import ConversationStore
from .routes.endpoints import WebApiState, router
from .routes.errors import register_error_handlers
from .settings import WebApiSettings, load_settings

# How long a stopping server waits for the turns still running before it exits.
SHUTDOWN_GRACE_SECONDS = 30


def create_app(
    settings: WebApiSettings | None = None,
    bot_app: dict[str, Any] | None = None,
    client: OpenAI | None = None,
) -> FastAPI:
    """`bot_app` and `client` are given by tests; otherwise they are built at startup, with the
    same checks as the terminal (the vector collection and the MovieLens database must exist)."""
    resolved = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        store = ConversationStore(
            ttl_seconds=resolved.conversation_ttl_seconds,
            max_conversations=resolved.max_conversations,
        )
        app.state.web_api = WebApiState(
            settings=resolved,
            store=store,
            bot_app=bot_app or build_ready_app(),
            client=client or OpenAI(),
        )
        yield
        if store.tasks:
            await asyncio.wait(set(store.tasks), timeout=SHUTDOWN_GRACE_SECONDS)

    app = FastAPI(title="NetflixScout", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved.cors_origins),
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )
    register_error_handlers(app)
    app.include_router(router)
    return app
