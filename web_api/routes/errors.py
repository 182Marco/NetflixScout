"""One error shape for every non-streaming failure: `{"error": {"code", "message"}}`."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ..conversations.store import ConversationNotFound, TurnInProgress
from ..schemas.responses import ErrorBody, ErrorDetail

CODE_NOT_FOUND = "conversation_not_found"
CODE_IN_PROGRESS = "turn_in_progress"
CODE_INVALID = "invalid_request"
CODE_TOO_LONG = "message_too_long"


class MessageTooLong(Exception):
    pass


def error_response(status: int, code: str, message: str) -> JSONResponse:
    body = ErrorBody(error=ErrorDetail(code=code, message=message))
    return JSONResponse(status_code=status, content=body.model_dump())


async def _not_found(request: Request, exc: Exception) -> JSONResponse:
    return error_response(404, CODE_NOT_FOUND, "Conversation not found.")


async def _in_progress(request: Request, exc: Exception) -> JSONResponse:
    return error_response(409, CODE_IN_PROGRESS, "A message of this conversation is still being answered.")


async def _too_long(request: Request, exc: Exception) -> JSONResponse:
    return error_response(422, CODE_TOO_LONG, "The message is too long.")


async def _invalid(request: Request, exc: Exception) -> JSONResponse:
    return error_response(422, CODE_INVALID, "The request body is not valid.")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ConversationNotFound, _not_found)
    app.add_exception_handler(TurnInProgress, _in_progress)
    app.add_exception_handler(MessageTooLong, _too_long)
    app.add_exception_handler(RequestValidationError, _invalid)
