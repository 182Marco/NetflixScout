"""The closing events of a turn, built from the finished `TurnResult` (pure functions)."""
from __future__ import annotations

from typing import Any

from presenters import OutputChannel, present
from turn import TurnResult
from web_lists import attach_lists

from ..schemas.events import EVENT_ANSWER_END, EVENT_DONE, EVENT_LISTS, AnswerEnd

EventPayload = tuple[str, dict[str, Any]]


def replacement(streamed: str, final: str) -> str | None:
    """What the frontend must show instead of the text it streamed, or None to keep it.

    Both texts are compared without their leading and trailing whitespace (`str.strip`); inner
    whitespace, line breaks and characters are never normalised. Equal: None (the frontend only
    trims the edges when it shows the text). Different: the whole final answer, stripped.
    """
    return None if streamed.strip() == final.strip() else final.strip()


def final_events(turn: TurnResult, streamed: str) -> list[EventPayload]:
    """`answer_end`, `lists` and `done`, in this order, for a turn whose text was streamed as `streamed`."""
    payload = present(turn, OutputChannel.web) or {}
    answer_end = AnswerEnd(
        blocked=payload["blocked"],
        language=payload["language"],
        tool=payload["tool"],
        tools=payload["tools"],
        history_compacted=turn.history_compacted,
        replace=replacement(streamed, turn.answer),
    )
    lists = attach_lists(payload, turn)["lists"]
    return [
        (EVENT_ANSWER_END, answer_end.model_dump(mode="json")),
        (EVENT_LISTS, {"lists": lists}),
        (EVENT_DONE, {}),
    ]
