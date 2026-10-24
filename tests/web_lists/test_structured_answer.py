"""One LLM call writes the answer and the list references; the terminal call is unchanged."""
from __future__ import annotations

import pytest

import app as app_module
from orchestrator import LLMOrchestrator
from web_lists import final_output
from web_lists_support import ANSWER, MOVIE_REF, FakeClient, raw_list, structured


class _Tool:
    name = "rag_search"
    description = "fake"
    input_schema: dict = {}

    def run(self, *, query, params=None, conversation_history=None):
        return {"query": query, "chunks": [], "metadata": {}}


PLAN = '{"standalone_query": "x", "tool_name": "rag_search", "confidence": 0.9}'
CONFIG = {"orchestrator": {"fallback_tool": "rag_search", "tool_confidence_threshold": 0.6}}


def _run(client, **kwargs):
    orch = LLMOrchestrator(config=CONFIG, tools=[_Tool()], client=client)
    return orch.run(query="q", conversation_history=[], **kwargs)


def test_with_final_output_the_final_call_is_one_and_returns_answer_and_lists() -> None:
    client = FakeClient(PLAN, structured(ANSWER + "  ", raw_list(MOVIE_REF)))
    decision = _run(client, final_output=final_output())
    planning, final = client.responses.calls
    assert len(client.responses.calls) == 2  # planner + the single final call: no list call
    assert "text" not in planning
    assert final["text"]["format"]["strict"] is True
    assert final["instructions"].endswith(final_output()["instructions"])
    assert decision["final_answer"] == ANSWER.strip() and decision["final_lists"] == [raw_list(MOVIE_REF)]


def test_markdown_survives_the_json_round_trip() -> None:
    text = 'Titolo\n\n- **Film** "A" \\ ✓ — `x`\n\n> citazione 🎬'
    decision = _run(FakeClient(PLAN, structured(text)), final_output=final_output())
    assert decision["final_answer"] == text


@pytest.mark.parametrize(
    "output",
    ["not json", "", "{}", '{"answer": "", "lists": []}', '{"answer": 5, "lists": []}', '{"answer": "ok'],
    ids=["text", "empty-or-refusal", "no-answer", "blank", "wrong-type", "truncated"],
)
def test_a_bad_structured_output_takes_the_existing_fallback_without_a_second_call(output) -> None:
    client = FakeClient(PLAN, output)
    decision = _run(client, final_output=final_output())
    assert len(client.responses.calls) == 2
    assert decision["final_answer"] == "Non ho abbastanza informazioni per rispondere."
    assert decision["final_lists"] == [] and "answer_failed" in decision["planning"]["fallbacks"]


def test_a_failing_final_call_takes_the_fallback_and_no_lists() -> None:
    client = FakeClient(PLAN, RuntimeError("boom"))
    decision = _run(client, final_output=final_output())
    assert len(client.responses.calls) == 2 and decision["final_lists"] == []
    assert "answer_failed" in decision["planning"]["fallbacks"]


def test_lists_that_are_not_a_list_become_empty() -> None:
    client = FakeClient(PLAN, '{"answer": "Ciao", "lists": "x"}')
    decision = _run(client, final_output=final_output())
    assert decision["final_answer"] == "Ciao" and decision["final_lists"] == []


def test_without_final_output_the_final_call_is_exactly_the_old_one() -> None:
    client = FakeClient(PLAN, "Risposta finale.")
    decision = _run(client)
    final = client.responses.calls[1]
    assert set(final) == {"model", "instructions", "input"}  # no `text`
    assert final_output()["instructions"] not in final["instructions"]
    assert decision["final_answer"] == "Risposta finale." and decision["final_lists"] == []


def test_handle_query_passes_final_output_only_when_given(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "classify_query_domain", lambda q, history=None: {"is_cinema": True, "is_italian": True})
    seen = []

    class _Orchestrator:
        def run(self, *, query, conversation_history=None, tool_overrides=None, observer=None, **extra):
            seen.append(extra)
            return {"tool": None, "tools": [], "final_answer": "ok", "final_lists": [raw_list(MOVIE_REF)] if extra else []}

    app = {"config": app_module.build_runtime_config(), "orchestrator": _Orchestrator()}
    terminal = app_module.handle_query(app, "q")
    web = app_module.handle_query(app, "q", final_output=final_output())
    assert seen == [{}, {"final_output": final_output()}]
    assert terminal.item_refs == [] and web.item_refs == [raw_list(MOVIE_REF)]
