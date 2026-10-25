from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator


class MessageRequest(BaseModel):
    """Body of `POST /conversations/{id}/messages`. The maximum length is a setting, checked by the route."""

    model_config = ConfigDict(extra="forbid")

    content: str

    @field_validator("content")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be blank")
        return value
