from __future__ import annotations

from pydantic import BaseModel


class ConversationCreated(BaseModel):
    conversation_id: str
    created_at: str


class ConversationInfo(BaseModel):
    """`busy`: a turn is still running (also when its client left); `turns_completed`: turns whose
    history is committed, which tells a client that lost its stream whether to send again."""

    conversation_id: str
    busy: bool
    turns_completed: int


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorBody(BaseModel):
    error: ErrorDetail
