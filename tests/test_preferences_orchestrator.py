"""Where the settings reach the prompts: the planner and the final answer, nowhere else (fake client)."""
from __future__ import annotations

import json

from preferences import build_prompt_parts, defaults, resolve_preferences
from stream_support import reply

from orchestrator import LLMOrchestrator

PLAN = json.dumps({"standalone_query": "q", "tool_name": "tmdb_search", "arguments": {}, "confidence": 0.9})
FINAL_INSTRUCTIONS = "REGOLE FINALI BASE."


class ScriptedClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.responses = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return reply(PLAN if not kwargs.get("stream") else "Risposta finale.", kwargs)


class Tool:
    name = "tmdb_search"
    description = "fake"
    input_schema: dict = {}

    def run(self, *, query, params=None, conversation_history=None):
        return {"query": query, "chunks": [{"title": "X"}], "metadata": {}, "trace": []}


def _orchestrator(client: ScriptedClient) -> LLMOrchestrator:
    config = {"orchestrator": {"fallback_tool": "tmdb_search", "final_instructions": FINAL_INSTRUCTIONS}}
    return LLMOrchestrator(config=config, tools=[Tool()], client=client)


def _run(**kwargs) -> ScriptedClient:
    client = ScriptedClient()
    _orchestrator(client).run(query="q", conversation_history=[], **kwargs)
    return client


def test_without_parts_every_prompt_is_the_legacy_one() -> None:
    client = _run()

    assert all("Preferenze dell'utente" not in c["instructions"] for c in client.calls)
    assert all("Impostazioni dell'utente" not in c["instructions"] for c in client.calls)
    assert client.calls[-1]["instructions"] == FINAL_INSTRUCTIONS


def test_parts_reach_the_planner_and_the_final_answer_and_only_those() -> None:
    parts = build_prompt_parts(resolve_preferences({"response_tone": "Homie", "preferred_sources": "reviews"}).preferences)
    client = _run(prompt_parts=parts)
    planner, answer = client.calls[0]["instructions"], client.calls[-1]["instructions"]

    assert planner.rstrip().endswith(parts["planner"]) and parts["answer"] not in planner
    assert answer == f"{FINAL_INSTRUCTIONS} {parts['answer']}" and parts["planner"] not in answer
    assert len(client.calls) == len(_run().calls)  # a setting never adds an LLM call


def test_two_turns_with_different_settings_do_not_accumulate() -> None:
    client = ScriptedClient()
    orchestrator = _orchestrator(client)
    first = build_prompt_parts(resolve_preferences({"response_tone": "Homie"}).preferences)
    second = build_prompt_parts(defaults())

    orchestrator.run(query="q", conversation_history=[], prompt_parts=first)
    orchestrator.run(query="q", conversation_history=[], prompt_parts=second)
    last_answer = client.calls[-1]["instructions"]

    assert second["answer"] in last_answer and "Tono Homie" not in last_answer
    assert last_answer.count("Impostazioni dell'utente per QUESTO turno") == 1


def test_the_web_format_instructions_come_after_the_settings() -> None:
    client = ScriptedClient()
    parts = build_prompt_parts(defaults())
    final_output = {"text_format": {"type": "json_schema", "name": "x", "schema": {}, "strict": True}, "instructions": "WEBFORMAT"}

    _orchestrator(client).run(query="q", conversation_history=[], prompt_parts=parts, final_output=final_output)

    answer = client.calls[-1]["instructions"]
    assert answer.index(parts["answer"]) < answer.index("WEBFORMAT")
