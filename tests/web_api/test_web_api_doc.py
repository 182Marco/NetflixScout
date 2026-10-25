"""`web_api/FRONTEND_API.md` describes what the code does: events, routes and example payloads."""
from __future__ import annotations

import json
import re
from pathlib import Path

from web_api.routes.endpoints import router
from web_api.routes.errors import CODE_IN_PROGRESS, CODE_INVALID, CODE_NOT_FOUND, CODE_TOO_LONG
from web_api.schemas.events import EVENT_MODELS
from web_api.settings import (
    ENV_CONVERSATION_TTL,
    ENV_CORS_ORIGINS,
    ENV_HEARTBEAT,
    ENV_MAX_CONVERSATIONS,
    ENV_MAX_MESSAGE_CHARS,
)

DOC = (Path(__file__).resolve().parents[2] / "web_api" / "FRONTEND_API.md").read_text(encoding="utf-8")
EXAMPLE = re.compile(r"```json event=(\w+)\n(.*?)\n```", re.S)


def test_every_event_is_documented_with_a_valid_example() -> None:
    examples = {name: json.loads(body) for name, body in EXAMPLE.findall(DOC)}

    assert set(examples) == set(EVENT_MODELS)
    for name, payload in examples.items():
        EVENT_MODELS[name].model_validate(payload)


def test_every_route_and_error_code_is_documented() -> None:
    for route in router.routes:
        method = sorted(route.methods - {"HEAD", "OPTIONS"})[0]
        assert f"{method} {route.path.replace('{conversation_id}', '{id}')}" in DOC, route.path
    for code in (CODE_NOT_FOUND, CODE_IN_PROGRESS, CODE_INVALID, CODE_TOO_LONG):
        assert f"`{code}`" in DOC


def test_every_setting_is_documented() -> None:
    for name in (ENV_CORS_ORIGINS, ENV_CONVERSATION_TTL, ENV_MAX_CONVERSATIONS, ENV_MAX_MESSAGE_CHARS, ENV_HEARTBEAT):
        assert f"`{name}`" in DOC
