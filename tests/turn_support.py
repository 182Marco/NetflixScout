"""Fake orchestrators stream like the real one: `stream_decision` replays a canned decision."""
from __future__ import annotations

from typing import Any

from turn import (
    STEP_PLANNING,
    STEP_QUERY_REWRITE,
    STEP_TOOL_OUTCOME,
    STEP_TOOL_SELECTION,
    NullObserver,
    TraceStep,
)


def _answer_delta(observer: Any, text: str) -> None:
    delta = getattr(observer, "answer_delta", None)
    if delta and text:
        delta(text)


def stream_decision(observer: Any, query: str, decision: dict[str, Any]) -> None:
    """Emit the steps `LLMOrchestrator.run` would emit for `decision`, in the same order, then
    its answer as a delta (to an observer that has `answer_delta`)."""
    observer = observer or NullObserver()
    used = decision.get("standalone_query") or query
    observer.step(
        TraceStep(
            kind=STEP_QUERY_REWRITE,
            title="Query usata dai tool",
            data={"original": query, "used": used, "rewritten": used != query},
        )
    )
    if decision.get("clarification"):
        observer.step(
            TraceStep(kind=STEP_TOOL_SELECTION, title="Tool scelto", data={"tool": None, "clarification": True})
        )
        _answer_delta(observer, decision.get("final_answer", ""))
        return
    calls = decision.get("calls")
    if calls is None and decision.get("tool"):
        calls = [{"tool": decision["tool"], "arguments": {}, "result": decision["result"]}]
    for call in calls or []:
        observer.step(
            TraceStep(
                kind=STEP_TOOL_SELECTION,
                title="Tool scelto",
                data={"tool": call["tool"], "purpose": used, "arguments": call.get("arguments", {})},
            )
        )
        outcome = call["result"].get("outcome") or {"status": "ok", "reason": None}
        observer.step(
            TraceStep(
                kind=STEP_TOOL_OUTCOME,
                title="Esito",
                data={"tool": call["tool"], "elapsed_ms": 0, **outcome},
            )
        )
        for step in call["result"].get("trace", []):
            observer.step(TraceStep(**step))
    planning = decision.get("planning")
    if planning and (len(planning["tools"]) > 1 or planning["pending"] or planning.get("fallbacks")):
        observer.step(TraceStep(kind=STEP_PLANNING, title="Pianificazione", data=dict(planning)))
    _answer_delta(observer, decision.get("final_answer", ""))
