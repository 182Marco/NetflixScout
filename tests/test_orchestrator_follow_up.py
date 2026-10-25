"""A tool can offer more (`turn.RESULT_FOLLOW_UP`): the orchestrator then asks the planner whether
to go on. Tools that offer nothing must cost exactly what they cost before."""
from __future__ import annotations

import json

import pytest

from orchestrator import LLMOrchestrator
from stream_support import reply
from turn import RESULT_FOLLOW_UP, TOOL_PARAM_TURN_ID

OFFER = {"available": True, "reasons": ["more_in_page"], "summary": "Letto: Introduzione. Non lette: Carriera (4100)."}
NO_OFFER = {"available": False, "reasons": [], "summary": "Letto tutto."}


class ScriptedClient:
    def __init__(self, texts: list[str]) -> None:
        self.texts = list(texts)
        self.calls: list[dict] = []
        self.responses = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return reply(self.texts.pop(0) if self.texts else "Risposta finale.", kwargs)


class OfferingTool:
    """Returns the next result of `results` on each run (the last one repeats)."""

    description = "fake"
    input_schema: dict = {}

    def __init__(self, name: str, results: list[dict]) -> None:
        self.name = name
        self.results = list(results)
        self.params: list[dict] = []

    def run(self, *, query, params=None, conversation_history=None):
        self.params.append(dict(params or {}))
        result = self.results.pop(0) if len(self.results) > 1 else self.results[0]
        return {"query": query, "chunks": [], "metadata": {"fake": {"n": len(self.params)}}, "trace": [], **result}


def _step(tool: str, more: bool = False, **arguments) -> str:
    return json.dumps({"standalone_query": "q", "tool_name": tool, "arguments": arguments, "confidence": 0.9, "more_steps": more})


def _orch(texts, results, **config):
    tool = OfferingTool("wikipedia_search", results)
    client = ScriptedClient(texts)
    orch = LLMOrchestrator(
        config={"orchestrator": {"fallback_tool": "wikipedia_search", **config}}, tools=[tool], client=client
    )
    return orch, tool, client


def test_an_offer_makes_the_planner_decide_even_without_more_steps() -> None:
    orch, tool, client = _orch(
        [_step("wikipedia_search", topic="X"), _step("wikipedia_search", page="X", sections=["Carriera"]), "ok"],
        [{RESULT_FOLLOW_UP: OFFER}, {RESULT_FOLLOW_UP: NO_OFFER}],
    )

    decision = orch.run(query="parlami di X", conversation_history=[])

    assert decision["tools"] == ["wikipedia_search", "wikipedia_search"]
    assert tool.params[1]["page"] == "X" and tool.params[1]["sections"] == ["Carriera"]
    assert tool.params[0][TOOL_PARAM_TURN_ID] == tool.params[1][TOOL_PARAM_TURN_ID]
    assert len(client.calls) == 3  # first plan, second plan, final answer
    second_plan = client.calls[1]["input"][-1]["content"]
    assert "può dare altro (more_in_page)" in second_plan and 'rispondi esattamente {"done": true}' in second_plan


def test_the_planner_sees_the_summary_of_the_tool_not_its_metadata() -> None:
    orch, _, client = _orch([_step("wikipedia_search", topic="X"), '{"done": true}', "ok"], [{RESULT_FOLLOW_UP: OFFER}])

    orch.run(query="parlami di X", conversation_history=[])

    content = client.calls[1]["input"][-1]["content"]
    assert OFFER["summary"] in content and "Metadata:" not in content


def test_the_planner_can_stop_with_done() -> None:
    orch, tool, client = _orch([_step("wikipedia_search", topic="X"), '{"done": true}', "ok"], [{RESULT_FOLLOW_UP: OFFER}])

    decision = orch.run(query="parlami di X", conversation_history=[])

    assert len(tool.params) == 1 and decision["planning"]["stop_reason"] == "done"
    assert len(client.calls) == 3


def test_the_same_step_twice_is_stopped() -> None:
    same = _step("wikipedia_search", topic="X")
    orch, tool, _ = _orch([same, same, "ok"], [{RESULT_FOLLOW_UP: OFFER}])

    decision = orch.run(query="parlami di X", conversation_history=[])

    assert len(tool.params) == 1 and decision["planning"]["stop_reason"] == "repeated_step"


def test_a_tool_that_always_offers_more_is_stopped_by_the_turn_ceiling() -> None:
    steps = [_step("wikipedia_search", topic="X", page=f"P{i}") for i in range(10)]
    orch, tool, _ = _orch(steps, [{RESULT_FOLLOW_UP: OFFER}], max_tool_calls_per_turn=3)

    decision = orch.run(query="parlami di X", conversation_history=[])

    assert len(tool.params) == 3 and decision["planning"]["stop_reason"] == "max_tool_calls"


def test_a_failing_next_planner_call_answers_with_what_there_is() -> None:
    orch, tool, _ = _orch([_step("wikipedia_search", topic="X"), "not json", "ok"], [{RESULT_FOLLOW_UP: OFFER}])

    decision = orch.run(query="parlami di X", conversation_history=[])

    assert len(tool.params) == 1 and decision["planning"]["stop_reason"] == "planner_failed"
    assert decision["final_answer"] == "ok"


def test_required_tools_still_mean_a_single_step() -> None:
    orch, tool, client = _orch(["ok"], [{RESULT_FOLLOW_UP: OFFER}], required_tools=["wikipedia_search"])

    decision = orch.run(query="parlami di X", conversation_history=[])

    assert len(tool.params) == 1 and decision["planning"]["stop_reason"] == "required_tools"
    assert len(client.calls) == 1


@pytest.mark.parametrize(
    "result",
    [
        {},  # a tool that knows nothing of follow-ups: unchanged
        {RESULT_FOLLOW_UP: NO_OFFER},
        {RESULT_FOLLOW_UP: {"available": "yes"}},
        {RESULT_FOLLOW_UP: "more"},
        {RESULT_FOLLOW_UP: None},
    ],
)
def test_without_an_offer_the_turn_costs_what_it_always_cost(result) -> None:
    orch, tool, client = _orch([_step("wikipedia_search", topic="X"), "ok"], [result])

    decision = orch.run(query="parlami di X", conversation_history=[])

    assert len(tool.params) == 1 and decision["tools"] == ["wikipedia_search"]
    assert len(client.calls) == 2  # one planner call, one final answer
    assert decision["planning"]["stop_reason"] == "complete"


def test_the_follow_up_key_never_reaches_the_final_prompt() -> None:
    orch, _, client = _orch([_step("wikipedia_search", topic="X"), "ok"], [{RESULT_FOLLOW_UP: NO_OFFER}])

    orch.run(query="parlami di X", conversation_history=[])

    final_prompt = client.calls[-1]["input"][-1]["content"]
    assert "Letto tutto." not in final_prompt and "follow_up" not in final_prompt


def test_without_a_summary_the_planner_sees_the_usual_result_lines() -> None:
    orch, _, client = _orch(
        [_step("wikipedia_search", topic="X", ), '{"done": true}', "ok"],
        [{RESULT_FOLLOW_UP: {"available": True, "reasons": ["empty"]}}],
    )

    orch.run(query="parlami di X", conversation_history=[])

    assert "Metadata:" in client.calls[1]["input"][-1]["content"]


def test_a_composite_turn_with_pending_parts_and_an_offer_plans_once_per_step() -> None:
    other = OfferingTool("tmdb_search", [{}])
    wiki = OfferingTool("wikipedia_search", [{RESULT_FOLLOW_UP: NO_OFFER}])
    plans = [
        json.dumps({
            "standalone_query": "q", "tool_name": "wikipedia_search", "arguments": {"topic": "X"}, "confidence": 0.9,
            "parts": [{"part": "biografia", "tool": "wikipedia_search"}, {"part": "film", "tool": "tmdb_search"}],
        }),
        _step("tmdb_search"),
        "ok",
    ]
    client = ScriptedClient(plans)
    orch = LLMOrchestrator(config={"orchestrator": {"fallback_tool": "tmdb_search"}}, tools=[wiki, other], client=client)

    decision = orch.run(query="x", conversation_history=[])

    assert decision["tools"] == ["wikipedia_search", "tmdb_search"] and len(client.calls) == 3


# --- the normal end of a turn is not an error ---------------------------------------------------------

END_WITHOUT_A_TOOL = [
    '{"done": true}',
    '{"done": "true"}',
    '{"done": "True"}',
    '{"tool_name": null, "confidence": 1}',
    '{"tool_name": ""}',
    '{"tool_name": "done"}',
    '{"tool_name": "none", "confidence": 0.9}',
    '{"standalone_query": "q", "tool_name": null, "arguments": {}, "confidence": 0.9, "parts": [], "more_steps": false}',
    "{}",
    '{"done": false, "tool_name": null}',
]


@pytest.mark.parametrize("planner_output", END_WITHOUT_A_TOOL)
def test_a_planner_that_names_no_tool_ends_the_turn_without_a_warning(planner_output) -> None:
    from presenters.story_view import build_story
    from turn import STEP_PLANNING, TraceStep

    orch, tool, _ = _orch([_step("wikipedia_search", topic="X"), planner_output, "ok"], [{RESULT_FOLLOW_UP: OFFER}])
    steps: list[TraceStep] = []

    class Observer:
        def step(self, step): steps.append(step)
        def status(self, stage): pass
        def answer_delta(self, text): pass

    decision = orch.run(query="parlami di X", conversation_history=[], observer=Observer())

    assert len(tool.params) == 1 and decision["planning"]["stop_reason"] == "done"
    assert decision["planning"]["fallbacks"] == []
    assert decision["final_answer"] == "ok"
    # (The fake tool has no chunks, so "no results" is told; no planning line is.)
    assert not [line for line in build_story(steps, "it") if "pianificare" in line.text or "Non ho cercato" in line.text]
    assert not any(step.kind == STEP_PLANNING and step.data.get("fallbacks") for step in steps)


@pytest.mark.parametrize(
    ("planner_output", "stop_reason"),
    [
        ('{"tool_name": "not_a_tool", "confidence": 0.9}', "unknown_tool_or_low_confidence"),
        ('{"tool_name": "wikipedia_search", "arguments": {"topic": "Y"}, "confidence": 0.1}', "unknown_tool_or_low_confidence"),
        ("not json", "planner_failed"),
        ('["done"]', "planner_failed"),
        ('"done"', "planner_failed"),
    ],
)
def test_a_real_planning_error_still_warns_and_still_answers(planner_output, stop_reason) -> None:
    from presenters.story_view import build_story
    from turn import TraceStep

    orch, tool, _ = _orch([_step("wikipedia_search", topic="X"), planner_output, "ok"], [{RESULT_FOLLOW_UP: OFFER}])
    steps: list[TraceStep] = []

    class Observer:
        def step(self, step): steps.append(step)
        def status(self, stage): pass
        def answer_delta(self, text): pass

    decision = orch.run(query="parlami di X", conversation_history=[], observer=Observer())

    assert len(tool.params) == 1 and decision["planning"]["stop_reason"] == stop_reason
    assert decision["planning"]["fallbacks"] == ["next_step_failed"] and decision["final_answer"] == "ok"
    assert any("Non ho potuto pianificare il passo successivo" in line.text for line in build_story(steps, "it"))


def test_a_named_tool_with_a_missing_confidence_is_followed() -> None:
    orch, tool, _ = _orch(
        [_step("wikipedia_search", topic="X"), '{"tool_name": "wikipedia_search", "arguments": {"topic": "Y"}}', "ok"],
        [{RESULT_FOLLOW_UP: OFFER}, {RESULT_FOLLOW_UP: NO_OFFER}],
    )

    decision = orch.run(query="parlami di X", conversation_history=[])

    assert len(tool.params) == 2 and tool.params[1]["topic"] == "Y" and decision["planning"]["fallbacks"] == []
