from __future__ import annotations

import json

from movie_db.harness.evaluation.routing_cases import DB, RAG, ROUTING_CASES, RoutingCase
from movie_db.harness.evaluation.run_routing_eval import RecordingClient, run_routing_cases
from orchestrator import LLMOrchestrator


class FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = "fake"
        self.input_schema = {}

    def run(self, *, query, params=None, conversation_history=None):
        raise AssertionError("routing eval must not run tools")


class ScriptedClient:
    def __init__(self, outputs: list[str | Exception]) -> None:
        self.outputs = outputs
        self.responses = self

    def create(self, **kwargs):
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return type("Response", (), {"output_text": output})()


def _run(cases, outputs):
    config = {"orchestrator": {"fallback_tool": RAG, "tool_confidence_threshold": 0.6, "allowed_tools": [RAG, DB]}}
    orchestrator = LLMOrchestrator(
        config=config,
        tools=[FakeTool(RAG), FakeTool(DB)],
        client=RecordingClient(ScriptedClient(outputs)),
    )
    return run_routing_cases(
        cases,
        orchestrator=orchestrator,
        classify=lambda q, history=None: {"is_cinema": True, "is_italian": True},
        context_size=2,
    )


def _plan(tool: str, confidence: float = 0.9, standalone: str = "q") -> str:
    return json.dumps({"standalone_query": standalone, "tool_name": tool, "arguments": {}, "confidence": confidence})


def test_explicit_choice_passes() -> None:
    [result] = _run((RoutingCase("film più votati", DB),), [_plan(DB)])

    assert result.source == "planner"
    assert result.passed


def test_silent_fallbacks_are_detected_and_fail() -> None:
    db_case = RoutingCase("film più votati", DB)
    rag_case = RoutingCase("di cosa parla Inception?", RAG)

    invalid, low, crashed = _run((rag_case, db_case, rag_case), ["not json", _plan(DB, 0.2), RuntimeError("offline")])

    # The fallback tool is rag_search: even the "right" tool fails when it was not chosen.
    assert (invalid.tool, invalid.source, invalid.passed) == (RAG, "fallback: invalid JSON", False)
    assert low.source.startswith("fallback: confidence") and not low.passed
    assert (crashed.tool, crashed.source, crashed.passed) == (RAG, "fallback: planner call failed", False)


def test_follow_up_requires_the_rewritten_query() -> None:
    case = next(c for c in ROUTING_CASES if c.history)

    good, bad = _run((case, case), [_plan(DB, standalone="Film horror più votati anni '90"), _plan(DB, standalone="E degli anni '90?")])

    assert good.passed
    assert not bad.passed


def test_cases_cover_both_tools_and_a_follow_up() -> None:
    tools = [case.expected_tool for case in ROUTING_CASES]

    assert tools.count(DB) >= 5 and tools.count(RAG) >= 4
    assert any(case.history for case in ROUTING_CASES)
    assert len(ROUTING_CASES) == 11
