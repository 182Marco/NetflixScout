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

TMDb Terms of Use (§3): the web frontend must show the TMDb logo and the notice in
`presenters.api_view.TMDB_NOTICE` (About/Credits), and every `tmdb_calls` step must keep
its `attributions` (JustWatch for streaming data) visible next to the answer.

YouTube API Services Developer Policies (III.A, III.C.5, III.F): every `youtube_calls` step
must name YouTube as the source and show video titles, channels and URLs exactly as in the
step (only control characters may be removed for display, as `presenters/terminal/youtube/`
does), and the frontend must link the YouTube Terms of Service and the Google Privacy Policy.
"""
from __future__ import annotations

from typing import Any

from turn import TurnResult


def to_payload(turn: TurnResult) -> dict[str, Any]:
    raise NotImplementedError("Web output channel is not implemented yet.")
