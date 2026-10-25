"""ASGI entry point: `uvicorn web_api.main:app` from the repository root, with ONE worker
(conversations live in this process's memory)."""
from __future__ import annotations

from .server import create_app

app = create_app()
