"""ASGI entry point: `uvicorn web_api.main:app` from the repository root, with ONE worker
(conversations live in this process's memory).

The bot is built here, at import, so that an unreachable Qdrant server stops the start with one clear line."""
from __future__ import annotations

from app import build_ready_app_or_exit

from .server import create_app

app = create_app(bot_app=build_ready_app_or_exit())
