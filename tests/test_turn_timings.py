"""The turn reports where its time went (planner calls, tools, local SQL, answer). Measurement only: it must not change what the turn does."""
from __future__ import annotations

import json

from orchestrator import LLMOrchestrator, _http_calls, _sql_ms
from test_orchestrator_follow_up import NO_OFFER, OFFER, OfferingTool, ScriptedClient, _step
from turn import RESULT_FOLLOW_UP


def _orch(texts, results):
    tool = OfferingTool("wikipedia_search", results)
    client = ScriptedClient(texts)
    return LLMOrchestrator(config={"orchestrator": {"fallback_tool": "wikipedia_search"}}, tools=[tool], client=client), client


def test_timings_count_every_planner_call_and_tool() -> None:
    orch, client = _orch([_step("wikipedia_search", topic="X"), _step("wikipedia_search", topic="Y"), "ok"],
                         [{RESULT_FOLLOW_UP: OFFER}, {RESULT_FOLLOW_UP: NO_OFFER}])
    decision = orch.run(query="parlami di X", conversation_history=[])
    t = decision["timings"]
    assert t["planner_calls"] == 2 and [c["kind"] for c in t["planner"]] == ["first", "next"]
    assert len(t["tools"]) == 2 and t["tool_ms"] == sum(x["ms"] for x in t["tools"])
    assert all(c["ms"] is not None and c["ms"] >= 0 for c in t["planner"])
    assert t["answer_ms"] >= 0 and t["run_ms"] >= t["planner_ms"]
    assert len(client.calls) == 3  # unchanged: two plans and the answer


def test_a_single_step_turn_has_one_planner_call() -> None:
    orch, client = _orch([_step("wikipedia_search", topic="X"), "ok"], [{}])
    t = orch.run(query="x", conversation_history=[])["timings"]
    assert t["planner_calls"] == 1 and len(client.calls) == 2


def test_a_failing_planner_call_is_still_timed() -> None:
    class Boom(ScriptedClient):
        def create(self, **kwargs):
            if not self.calls:
                self.calls.append(kwargs)
                raise RuntimeError("down")
            return super().create(**kwargs)

    tool = OfferingTool("wikipedia_search", [{}])
    orch = LLMOrchestrator(config={"orchestrator": {"fallback_tool": "wikipedia_search"}}, tools=[tool], client=Boom(["ok"]))
    t = orch.run(query="x", conversation_history=[])["timings"]
    assert t["planner"][0].get("failed") is True and t["planner"][0]["ms"] >= 0


def test_sql_and_http_helpers_read_the_trace() -> None:
    result = {"trace": [{"kind": "cinema_sql_calls", "title": "t", "data": {"queries": [{"ms": 1.5}, {"ms": 2.0}]}},
                        {"kind": "tmdb_calls", "title": "t", "data": {"calls": [{"method": "GET", "url": "u"}] * 3}}]}
    assert _sql_ms(result) == 3.5 and _http_calls(result) == 3
    assert _sql_ms({}) == 0 and _http_calls({}) == 0


def test_consume_stream_reports_the_answer_tokens_only_when_the_response_has_them() -> None:
    from types import SimpleNamespace as NS

    from orchestrator import _consume_stream

    done = NS(type="response.completed", response=NS(usage=NS(input_tokens=1234, output_tokens=56)))
    usage: dict[str, int] = {}
    assert _consume_stream([NS(type="response.output_text.delta", delta="ciao"), done], [], lambda _t: None, None, usage) is None
    assert usage == {"input_tokens": 1234, "output_tokens": 56}
    bare: dict[str, int] = {}
    assert _consume_stream([NS(type="response.completed")], [], lambda _t: None, None, bare) is None and bare == {}


def test_the_decision_always_carries_the_answer_tokens_key() -> None:
    orch, _ = _orch([_step("wikipedia_search", topic="X"), "ok"], [{}])
    assert orch.run(query="x", conversation_history=[])["timings"]["answer_tokens"] == {}
