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

# Explicit conclusions, as the contract of the next-step answer defines them (`orchestrator.NEXT_STEP_FORMAT`).
EXPLICIT_CONCLUSIONS = [
    '{"done": true}',
    '{"done": true, "more_steps": false}',
    '{"tool_name": null}',
    '{"tool_name": null, "confidence": 1}',
    '{"tool_name": ""}',
    '{"tool_name": "done"}',
    '{"tool_name": "STOP"}',
    '{"tool_name": "none", "confidence": 0.9}',
    '{"standalone_query": "q", "tool_name": null, "arguments": {}, "confidence": 0.9, "parts": [], "more_steps": false}',
    '{"done": null, "tool_name": null}',
]

# Answers that conclude nothing: empty, partial, contradictory or not in the contract's form.
INCOMPLETE_ANSWERS = [
    "{}",
    '{"confidence": 0.9}',
    '{"more_steps": false}',
    '{"arguments": {}}',
    '{"standalone_query": "q"}',
    '{"done": false}',
    '{"done": false, "tool_name": null}',
    '{"done": false, "tool_name": "done"}',
    '{"tool_name": null, "more_steps": true}',
    '{"tool_name": "done", "more_steps": true}',
    '{"done": "true"}',
    '{"done": "True"}',
    '{"done": 1}',
    '{"tool_name": 5}',
    '{"tool_name": ["wikipedia_search"]}',
]


class _Recorder:
    def __init__(self) -> None:
        self.steps: list = []

    def step(self, step): self.steps.append(step)
    def status(self, stage): pass
    def answer_delta(self, text): pass


def _warnings(steps) -> list[str]:
    from presenters.story_view import build_story

    return [line.text for line in build_story(steps, "it") if "pianificare" in line.text]


@pytest.mark.parametrize("planner_output", EXPLICIT_CONCLUSIONS)
def test_an_explicit_conclusion_ends_the_turn_without_a_warning(planner_output) -> None:
    from turn import STEP_PLANNING

    orch, tool, _ = _orch([_step("wikipedia_search", topic="X"), planner_output, "ok"], [{RESULT_FOLLOW_UP: OFFER}])
    observer = _Recorder()

    decision = orch.run(query="parlami di X", conversation_history=[], observer=observer)

    assert len(tool.params) == 1 and decision["planning"]["stop_reason"] == "done"
    assert decision["planning"]["fallbacks"] == [] and decision["final_answer"] == "ok"
    assert not _warnings(observer.steps)
    assert not any(step.kind == STEP_PLANNING and step.data.get("fallbacks") for step in observer.steps)


@pytest.mark.parametrize("planner_output", INCOMPLETE_ANSWERS)
def test_an_incomplete_or_contradictory_answer_is_not_a_conclusion(planner_output) -> None:
    orch, tool, _ = _orch([_step("wikipedia_search", topic="X"), planner_output, "ok"], [{RESULT_FOLLOW_UP: OFFER}])
    observer = _Recorder()

    decision = orch.run(query="parlami di X", conversation_history=[], observer=observer)

    assert len(tool.params) == 1 and decision["planning"]["stop_reason"] == "planner_incomplete"
    assert decision["planning"]["fallbacks"] == ["next_step_failed"] and decision["final_answer"] == "ok"
    assert len(_warnings(observer.steps)) == 1  # the existing warning, told once


@pytest.mark.parametrize("planner_output", EXPLICIT_CONCLUSIONS)
def test_every_explicit_conclusion_is_classified_done(planner_output) -> None:
    from orchestrator import NEXT_DONE, _classify_next_step

    assert _classify_next_step(json.loads(planner_output)) == (NEXT_DONE, None)


@pytest.mark.parametrize("planner_output", INCOMPLETE_ANSWERS)
def test_every_incomplete_answer_is_classified_incomplete(planner_output) -> None:
    from orchestrator import NEXT_INCOMPLETE, _classify_next_step

    assert _classify_next_step(json.loads(planner_output)) == (NEXT_INCOMPLETE, None)


def test_a_named_tool_is_a_step_even_when_the_planner_also_says_not_done() -> None:
    from orchestrator import NEXT_STEP, _classify_next_step

    assert _classify_next_step({"tool_name": "wikipedia_search", "done": False}) == (NEXT_STEP, "wikipedia_search")
    assert _classify_next_step({"tool": "tmdb_search", "more_steps": True}) == (NEXT_STEP, "tmdb_search")
    assert _classify_next_step({"tool_name": None, "tool": "tmdb_search"}) == (NEXT_STEP, "tmdb_search")


def test_the_contract_is_stated_to_the_planner_of_the_next_step_only() -> None:
    from orchestrator import NEXT_STEP_FORMAT

    orch, _, client = _orch([_step("wikipedia_search", topic="X"), '{"done": true}', "ok"], [{RESULT_FOLLOW_UP: OFFER}])

    orch.run(query="parlami di X", conversation_history=[])

    first, second = client.calls[0]["instructions"], client.calls[1]["instructions"]
    assert NEXT_STEP_FORMAT not in first and second.endswith(NEXT_STEP_FORMAT)
    assert 'per concludere rispondi {"done": true}' in second and "more_steps non sia true" in second
    for word in ('"done"', '"none"', '"stop"'):
        assert word in NEXT_STEP_FORMAT


def test_the_planner_output_is_recorded_without_free_text_or_arguments() -> None:
    secret = "TESTO-LIBERO-SEGRETO"
    hostile = json.dumps(
        {
            "tool_name": "wikipedia_search",
            "arguments": {"topic": secret, "keywords": [secret]},
            "confidence": 0.1,
            "more_steps": False,
            "note": secret,
            secret: "x",
            "done": secret,
        }
    )
    orch, _, _ = _orch([_step("wikipedia_search", topic="X"), hostile, "ok"], [{RESULT_FOLLOW_UP: OFFER}])
    observer = _Recorder()

    decision = orch.run(query="parlami di X", conversation_history=[], observer=observer)

    detail = decision["planning"]["planner_output"]
    assert secret not in json.dumps(decision["planning"]) and all(secret not in json.dumps(s.data) for s in observer.steps)
    assert detail["tool_name"] == "wikipedia_search" and detail["confidence"] == 0.1 and detail["more_steps"] is False
    assert detail["done"] == "<str>" and detail["keys"].count("<key>") == 2 and "arguments" in detail["keys"]
    assert set(detail) == {"keys", "done", "confidence", "more_steps", "tool_name"}  # no arguments, no note


def test_a_tool_name_outside_the_app_is_not_echoed() -> None:
    orch, _, _ = _orch([_step("wikipedia_search", topic="X"), '{"tool_name": "frase-libera-senza-spazi", "confidence": 0.9}', "ok"], [{RESULT_FOLLOW_UP: OFFER}])

    decision = orch.run(query="parlami di X", conversation_history=[])

    assert decision["planning"]["planner_output"]["tool_name"] == "<str>"
    assert decision["planning"]["stop_reason"] == "unknown_tool_or_low_confidence"


def test_the_recorded_output_shows_what_a_real_conclusion_looked_like() -> None:
    orch, _, _ = _orch([_step("wikipedia_search", topic="X"), '{"tool_name": null, "more_steps": false}', "ok"], [{RESULT_FOLLOW_UP: OFFER}])

    decision = orch.run(query="parlami di X", conversation_history=[])

    assert decision["planning"]["planner_output"] == {"keys": ["tool_name", "more_steps"], "tool_name": None, "more_steps": False}


def test_a_planner_that_does_not_answer_with_an_object_leaves_only_its_type() -> None:
    orch, _, _ = _orch([_step("wikipedia_search", topic="X"), '["done", "TESTO-LIBERO"]', "ok"], [{RESULT_FOLLOW_UP: OFFER}])

    decision = orch.run(query="parlami di X", conversation_history=[])

    assert decision["planning"]["planner_output"] == {"type": "list"} and decision["planning"]["stop_reason"] == "planner_failed"


def test_turns_without_a_next_step_planning_call_have_no_planner_output() -> None:
    orch, _, _ = _orch([_step("wikipedia_search", topic="X"), "ok"], [{RESULT_FOLLOW_UP: NO_OFFER}])

    decision = orch.run(query="parlami di X", conversation_history=[])

    assert "planner_output" not in decision["planning"]


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
