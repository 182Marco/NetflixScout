from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class MessageRequest(BaseModel):
    """Body of `POST /conversations/{id}/messages`. The maximum length is a setting, checked by the route.

    `preferences` is deliberately untyped here: its fields are validated one by one by
    `preferences.resolve_preferences`, so a wrong value never turns the request into a 422.
    """

    model_config = ConfigDict(extra="forbid")

    content: str
    preferences: Any = None

    @field_validator("content")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be blank")
        return value
