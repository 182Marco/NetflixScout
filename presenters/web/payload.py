"""Web output channel: the JSON-ready form of a `TurnResult` for the FastAPI response.

Same content as the terminal, in another format. Both read the same shared views
(`presenters/story_view.py`, `rag_view.py`, `db_view.py`, `api_view.py`, `youtube_view.py`, `wikipedia_view.py`, `omdb_view.py`, `tvmaze_view.py`),
so the story, the steps and their data are the same; the web has no emoji and no `═` titles,
the frontend picks icons from `story[].level`.

    {
        "answer": str, "blocked": bool, "language": str,   # ISO 639-1 code of the latest message
        "tool": str | None, "tools": [str],
        "story": [{"level": "progress" | "info" | "ok" | "warn", "text": str, "tool": str | None}],
        "steps": [{"kind": ..., ...}]   # tool steps only, in order (see STEP_SERIALIZERS)
    }

`story` tells the turn in a few plain sentences (what is searched and where, whether it was
found, how long it took, when the system went on with less than planned). The flow steps
(`classification`, `query_rewrite`, `tool_selection`, `tool_outcome`, `planning`) are told by
`story`, so they are not in `steps`; the `classification` verdict is internal, only the block
message of a blocked turn is shown. A step kind without a serializer is passed on as
`{"kind", "title", "data"}`, like the terminal's generic block.

Live progress: `presenters/web/observer.py:WebObserver` is the web `TurnObserver` (see `turn.py`):
pass it to `app.handle_query` and it reports status, story lines, tool steps and the answer text
as they happen. Conversation history stays out of the payload: the web caller keeps it.

Every `tmdb_calls` step must keep its `attributions` (JustWatch for streaming data)
visible next to the answer.

YouTube API Services Developer Policies (III.A, III.C.5, III.F): every `youtube_calls` step
must name YouTube as the source and show video titles, channels and URLs exactly as in the
step (only control characters may be removed for display, as `presenters/youtube_view.py`
does).

Wikipedia text is CC BY-SA: every `wikipedia_calls` step carries the page titles and links, the
`source` line and the licence with its link; the frontend must show them as received.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from turn import (
    STEP_DB_QUERY,
    STEP_RERANK,
    STEP_RETRIEVAL,
    STEP_TMDB_CALLS,
    STEP_WIKIPEDIA_CALLS,
    STEP_OMDB_CALLS,
    STEP_TVMAZE_CALLS,
    STEP_YOUTUBE_CALLS,
    TraceStep,
    TurnResult,
)

from ..story_view import STORY_STEP_KINDS, build_story
from .api import serialize_tmdb_calls_step
from .db import serialize_db_query_step
from .rag import serialize_rag_step
from .omdb import serialize_omdb_calls_step
from .tvmaze import serialize_tvmaze_calls_step
from .wikipedia import serialize_wikipedia_calls_step
from .youtube import serialize_youtube_calls_step

Serializer = Callable[[TraceStep, str | None], dict[str, Any]]

# Same kinds as the terminal's STEP_RENDERERS (checked by tests/test_presenter_parity.py).
STEP_SERIALIZERS: dict[str, Serializer] = {
    STEP_RETRIEVAL: serialize_rag_step,
    STEP_RERANK: serialize_rag_step,
    STEP_DB_QUERY: serialize_db_query_step,
    STEP_TMDB_CALLS: serialize_tmdb_calls_step,
    STEP_YOUTUBE_CALLS: serialize_youtube_calls_step,
    STEP_OMDB_CALLS: serialize_omdb_calls_step,
    STEP_TVMAZE_CALLS: serialize_tvmaze_calls_step,
    STEP_WIKIPEDIA_CALLS: serialize_wikipedia_calls_step,
}


def serialize_step(step: TraceStep, language: str) -> dict[str, Any]:
    """The web form of one tool step (also what the live `WebObserver` sends)."""
    serializer = STEP_SERIALIZERS.get(step.kind)
    if serializer is None:
        return {"kind": step.kind, "title": step.title, "data": step.data}
    return serializer(step, language)


def to_payload(turn: TurnResult) -> dict[str, Any]:
    return {
        "answer": turn.answer,
        "blocked": turn.blocked,
        "language": turn.language,
        "tool": turn.tool,
        "tools": list(turn.tools),
        # Rebuilt from the steps, like the terminal's replay: the same text for both channels.
        "story": [line.model_dump(mode="json") for line in build_story(turn.steps, turn.language)],
        "steps": [serialize_step(step, turn.language) for step in turn.steps if step.kind not in STORY_STEP_KINDS],
    }
