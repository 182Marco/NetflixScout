"""Web output channel (prepared, not implemented yet).

It will turn a `TurnResult` into a JSON-ready dict for the FastAPI response, built
to be mapped directly by the frontend. Intended shape:

    {
        "answer": str,
        "blocked": bool,
        "language": "it" | "en",
        "tool": str | None,
        "steps": [
            {"kind": "classification" | "query_rewrite" | "tool_selection" | "retrieval" | "rerank" | ...,
             "title": str,
             "data": {...}}   # typed per kind, e.g. retrieval/rerank -> {"chunks": [RagChunk]}
        ],
    }

It will be implemented when more tools than the RAG exist, so the step schema can
be designed across all of them. Conversation history stays out of the payload: the
web caller keeps it and sends it back on the next request.
"""
from __future__ import annotations

from typing import Any

from turn import TurnResult


def to_payload(turn: TurnResult) -> dict[str, Any]:
    raise NotImplementedError("Web output channel is not implemented yet.")
