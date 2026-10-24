"""Entry point: the web payload of a finished turn, plus `lists`.

The references come from the same call that wrote the answer (`TurnResult.item_refs`); this
module makes no LLM call, no network call and no search by title.
"""
from __future__ import annotations

from typing import Any

from turn import TurnResult

from .hydrate.hydrate_lists import hydrate_lists
from .hydrate.index_steps import index_steps
from .schema.llm.lists_output import ListsOutput
from .select.select_refs import select_refs


def _build_lists(turn: TurnResult) -> list[dict[str, Any]]:
    if turn.blocked or not turn.answer or not turn.item_refs:
        return []
    index = index_steps(turn.steps)
    if not index:
        return []
    refs = ListsOutput.model_validate({"lists": turn.item_refs}).lists
    return hydrate_lists(select_refs(refs, turn.answer, index), index)


def attach_lists(payload: dict[str, Any], turn: TurnResult) -> dict[str, Any]:
    """`payload` is not changed (the answer stays as it is); `lists` is `[]` on any failure."""
    try:
        lists = _build_lists(turn)
    except Exception:
        lists = []
    return {**payload, "lists": lists}
