from __future__ import annotations

import json

from orchestrator import LLMOrchestrator

HISTORY = [
    {"role": "user", "content": "Consigliami un film di fantascienza con robot"},
    {"role": "assistant", "content": "Ti consiglio Blade Runner (1982)."},
    {"role": "user", "content": "E uno con meno azione?"},
    {"role": "assistant", "content": "Prova Ex Machina (2014)."},
]


class FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = "fake"
        self.input_schema = {}
        self.queries: list[str] = []

    def run(self, *, query, params=None, conversation_history=None):
        self.queries.append(query)
        return {"query": query, "chunks": [], "metadata": {}}


class FakeClient:
    """Answers the planning call with `plan` (or raises), then the final-answer call."""

    def __init__(self, plan: dict | Exception) -> None:
        self.plan = plan
        self.calls: list[dict] = []
        self.responses = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            if isinstance(self.plan, Exception):
                raise self.plan
            text = json.dumps(self.plan)
        else:
            text = "Risposta finale."
        return type("Response", (), {"output_text": text})()


def _orchestrator(plan, tools=("rag_search",), **config):
    fake_tools = [FakeTool(name) for name in tools]
    orchestrator_config = {"fallback_tool": "rag_search", "tool_confidence_threshold": 0.6, **config}
    client = FakeClient(plan)
    orch = LLMOrchestrator(config={"orchestrator": orchestrator_config}, tools=fake_tools, client=client)
    return orch, {t.name: t for t in fake_tools}, client


def test_follow_up_query_is_rewritten_and_sent_to_the_tool() -> None:
    plan = {"standalone_query": "film di fantascienza con robot più recenti", "tool_name": "rag_search", "confidence": 0.9}
    orch, tools, _ = _orchestrator(plan)

    decision = orch.run(query="e uno più recente?", conversation_history=HISTORY)

    assert decision["standalone_query"] == "film di fantascienza con robot più recenti"
    assert tools["rag_search"].queries == ["film di fantascienza con robot più recenti"]


def test_full_history_is_sent_unchanged_for_prompt_caching() -> None:
    long_history = HISTORY * 5  # 20 messages, more than any old window
    plan = {"standalone_query": "x", "tool_name": "rag_search", "confidence": 0.9}
    orch, _, client = _orchestrator(plan)

    orch.run(query="e uno più recente?", conversation_history=long_history)

    assert client.calls[0]["input"] == [*long_history, {"role": "user", "content": "e uno più recente?"}]


def test_rewrite_is_kept_when_confidence_is_low_and_fallback_tool_runs() -> None:
    plan = {"standalone_query": "film con robot recenti", "tool_name": "other_tool", "confidence": 0.1}
    orch, tools, _ = _orchestrator(plan, tools=("rag_search", "other_tool"))

    decision = orch.run(query="e uno più recente?", conversation_history=HISTORY)

    assert decision["tool"] == "rag_search"
    assert tools["rag_search"].queries == ["film con robot recenti"]


def test_rewrite_is_kept_with_required_tools() -> None:
    plan = {"standalone_query": "film con robot recenti", "tool_name": "other_tool", "confidence": 0.9}
    orch, tools, _ = _orchestrator(plan, tools=("rag_search", "other_tool"), required_tools=["rag_search"])

    decision = orch.run(query="e uno più recente?", conversation_history=HISTORY)

    assert decision["tool"] == "rag_search"
    assert tools["rag_search"].queries == ["film con robot recenti"]


def test_first_turn_uses_original_query() -> None:
    plan = {"standalone_query": "something else", "tool_name": "rag_search", "confidence": 0.9}
    orch, tools, _ = _orchestrator(plan)

    decision = orch.run(query="film con robot", conversation_history=[])

    assert decision["standalone_query"] == "film con robot"
    assert tools["rag_search"].queries == ["film con robot"]


def test_first_turn_with_required_tools_skips_the_planning_call() -> None:
    plan = {"standalone_query": "something else", "tool_name": "rag_search", "confidence": 0.9}
    orch, tools, client = _orchestrator(plan, required_tools=["rag_search"])

    orch.run(query="film con robot", conversation_history=[])

    assert tools["rag_search"].queries == ["film con robot"]
    assert len(client.calls) == 1  # only the final-answer call


def test_llm_error_falls_back_to_original_query() -> None:
    orch, tools, _ = _orchestrator(RuntimeError("offline"))

    decision = orch.run(query="e uno più recente?", conversation_history=HISTORY)

    assert decision["tool"] == "rag_search"
    assert tools["rag_search"].queries == ["e uno più recente?"]


def test_final_context_includes_genres() -> None:
    orch, _, _ = _orchestrator({})
    tool_result = {
        "tool_name": "rag_search",
        "chunks": [{"testo": "A ship in space.", "title": "Star Odyssey", "release_year": "1979", "genres": "Science Fiction"}],
    }

    messages = orch._build_final_context(query="fantascienza", tool_result=tool_result)

    assert "generi=Science Fiction" in messages[-1]["content"]
