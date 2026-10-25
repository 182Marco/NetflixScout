"""Server settings from the environment. Bot behaviour stays in `app.CONFIG`; this is only the
HTTP side: who may call (CORS), how long conversations live and how big a message can be."""
from __future__ import annotations

import os
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field

ENV_CORS_ORIGINS = "WEB_API_CORS_ORIGINS"
ENV_CONVERSATION_TTL = "WEB_API_CONVERSATION_TTL_SECONDS"
ENV_MAX_CONVERSATIONS = "WEB_API_MAX_CONVERSATIONS"
ENV_MAX_MESSAGE_CHARS = "WEB_API_MAX_MESSAGE_CHARS"
ENV_HEARTBEAT = "WEB_API_HEARTBEAT_SECONDS"

# The dev servers of a Vue frontend (Vue CLI, Vite).
DEFAULT_CORS_ORIGINS = ("http://localhost:8080", "http://localhost:5173")


class WebApiSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS
    conversation_ttl_seconds: float = Field(default=3600, gt=0)
    max_conversations: int = Field(default=200, ge=1)
    max_message_chars: int = Field(default=2000, ge=1)
    heartbeat_seconds: float = Field(default=15, gt=0)


def _origins(raw: str) -> tuple[str, ...]:
    return tuple(origin.strip() for origin in raw.split(",") if origin.strip())


def load_settings(env: Mapping[str, str] | None = None) -> WebApiSettings:
    """Settings from `env` (default: the process environment); unset or empty means default."""
    source = os.environ if env is None else env
    raw = {
        "cors_origins": _origins(source.get(ENV_CORS_ORIGINS, "")) or None,
        "conversation_ttl_seconds": source.get(ENV_CONVERSATION_TTL) or None,
        "max_conversations": source.get(ENV_MAX_CONVERSATIONS) or None,
        "max_message_chars": source.get(ENV_MAX_MESSAGE_CHARS) or None,
        "heartbeat_seconds": source.get(ENV_HEARTBEAT) or None,
    }
    return WebApiSettings(**{name: value for name, value in raw.items() if value is not None})
