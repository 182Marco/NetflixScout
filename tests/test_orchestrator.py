from __future__ import annotations

import json

import pytest

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


def test_a_single_tool_turn_costs_one_planner_call_and_one_run() -> None:
    plan = {"standalone_query": "x", "tool_name": "rag_search", "confidence": 0.9}
    orch, tools, client = _orchestrator(plan)

    decision = orch.run(query="film con robot", conversation_history=HISTORY)

    assert len(tools["rag_search"].queries) == 1
    assert decision["tools"] == ["rag_search"] and len(client.calls) == 2


class ScriptedClient:
    """Answers each LLM call with the next text of `texts` (planner calls, then the final answer)."""

    def __init__(self, texts: list[str]) -> None:
        self.texts = list(texts)
        self.calls: list[dict] = []
        self.responses = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        text = self.texts.pop(0) if self.texts else "Risposta finale."
        return type("Response", (), {"output_text": text})()


class RecordingTool(FakeTool):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.params: list[dict] = []

    def run(self, *, query, params=None, conversation_history=None):
        self.params.append(dict(params or {}))
        return super().run(query=query, params=params, conversation_history=conversation_history)


def _multi(texts, tool_names=("tmdb_search", "youtube_search", "rag_search"), **config):
    tools = [RecordingTool(name) for name in tool_names]
    client = ScriptedClient(texts)
    orchestrator_config = {"fallback_tool": "rag_search", **config}
    orch = LLMOrchestrator(config={"orchestrator": orchestrator_config}, tools=tools, client=client)
    return orch, {t.name: t for t in tools}, client


def _step(tool, more=False, **arguments):
    return json.dumps(
        {"standalone_query": "q", "tool_name": tool, "arguments": arguments, "confidence": 0.9, "more_steps": more}
    )


def test_a_composite_request_runs_the_tools_in_sequence_without_the_rag() -> None:
    """Actor + critics + interview: TMDb finds the film, YouTube looks for the interview."""
    orch, tools, client = _multi(
        [_step("tmdb_search", True), _step("youtube_search", False, title="Il film"), "Risposta finale."]
    )

    decision = orch.run(query="film con DiCaprio e un'intervista", conversation_history=[])

    assert decision["tools"] == ["tmdb_search", "youtube_search"] and decision["tool"] == "tmdb_search"
    assert [c["tool"] for c in decision["calls"]] == ["tmdb_search", "youtube_search"]
    assert tools["youtube_search"].params[0]["title"] == "Il film"
    assert tools["rag_search"].queries == []
    # Same turn id for both runs: per-turn limits are counted across them.
    assert tools["tmdb_search"].params[0]["turn_id"] == tools["youtube_search"].params[0]["turn_id"]
    # The second planner call sees the first result; the final call carries every result.
    assert "Passi già eseguiti" in client.calls[1]["input"][-1]["content"]
    assert "Risultato 2: tool youtube_search" in client.calls[2]["input"][-1]["content"]


def test_each_used_tool_contributes_its_final_rules_once() -> None:
    orch, _, client = _multi(
        [_step("tmdb_search", True), _step("youtube_search"), "ok"],
        final_instructions="BASE.",
        tool_final_instructions={"youtube_search": "REGOLE-YT.", "rag_search": "REGOLE-RAG."},
    )

    orch.run(query="x", conversation_history=[])

    assert client.calls[-1]["instructions"] == "BASE. REGOLE-YT."


def test_the_turn_stops_at_max_tool_calls_per_turn() -> None:
    texts = [_step("tmdb_search", True, search_query=str(i)) for i in range(5)]
    orch, tools, _ = _multi(texts, max_tool_calls_per_turn=3)

    decision = orch.run(query="x", conversation_history=[])

    assert len(decision["calls"]) == 3 and len(tools["tmdb_search"].queries) == 3


def test_a_repeated_step_ends_the_loop() -> None:
    orch, _, _ = _multi([_step("tmdb_search", True, a=1), _step("tmdb_search", True, a=1)])

    assert orch.run(query="x", conversation_history=[])["tools"] == ["tmdb_search"]


def test_done_ends_the_loop() -> None:
    orch, _, _ = _multi([_step("tmdb_search", True), json.dumps({"done": True})])

    assert orch.run(query="x", conversation_history=[])["tools"] == ["tmdb_search"]


def test_a_failing_next_planning_call_answers_with_what_was_found_and_never_falls_back_to_the_rag() -> None:
    orch, tools, _ = _multi([_step("tmdb_search", True), "not json", "Risposta finale."])

    decision = orch.run(query="x", conversation_history=[])

    assert decision["tools"] == ["tmdb_search"] and decision["final_answer"] == "Risposta finale."
    assert tools["rag_search"].queries == []


def test_an_unknown_or_unsure_next_step_is_dropped() -> None:
    unsure = json.dumps({"tool_name": "youtube_search", "arguments": {}, "confidence": 0.1})
    orch, _, _ = _multi([_step("tmdb_search", True), unsure])

    assert orch.run(query="x", conversation_history=[])["tools"] == ["tmdb_search"]


def test_required_tools_keep_a_single_step() -> None:
    orch, _, _ = _multi([_step("tmdb_search", True)], required_tools=["tmdb_search"])

    assert orch.run(query="x", conversation_history=HISTORY)["tools"] == ["tmdb_search"]


def test_planning_prompt_includes_the_catalog_of_allowed_tools() -> None:
    plan = {"standalone_query": "x", "tool_name": "rag_search", "confidence": 0.9}
    orch, tools, client = _orchestrator(plan, tools=("rag_search", "other_tool"), allowed_tools=["rag_search"])
    tools["rag_search"].input_schema = {"type": "object", "properties": {"query": {"type": "string"}}}

    orch.run(query="film con robot", conversation_history=HISTORY)

    instructions = client.calls[0]["instructions"]
    assert '{"name":"rag_search","description":"fake","parameters":{"type":"object"' in instructions
    assert "other_tool" not in instructions


def test_a_failing_enricher_never_breaks_the_turn() -> None:
    class Broken:
        def enrich(self, *, tool_result):
            raise RuntimeError("boom")

    plan = {"standalone_query": "x", "tool_name": "rag_search", "confidence": 0.9}
    orch, tools, client = _orchestrator(plan)
    orch.enrichers = {"rag_search": Broken()}

    decision = orch.run(query="film con robot", conversation_history=HISTORY)

    assert decision["final_answer"] == "Risposta finale."
    assert decision["result"]["metadata"] == {"enrichment_error": True}
    assert len(tools["rag_search"].queries) == 1


def test_final_instructions_come_from_config_with_the_previous_default() -> None:
    plan = {"standalone_query": "x", "tool_name": "rag_search", "confidence": 0.9}
    default_orch, _, default_client = _orchestrator(plan)
    custom_orch, _, custom_client = _orchestrator(plan, final_instructions="Istruzioni finali di prova.")

    default_orch.run(query="q", conversation_history=[])
    custom_orch.run(query="q", conversation_history=[])

    assert default_client.calls[-1]["instructions"].startswith("Sei l'orchestratore di un sistema multi-tool.")
    assert custom_client.calls[-1]["instructions"] == "Istruzioni finali di prova."


CLARIFY_PLAN = {
    "standalone_query": "Chi c'era in quel film di Sorrentino?",
    "tool_name": None,
    "arguments": {},
    "confidence": 0.9,
    "needs_clarification": True,
    "clarification_question": "Quale film di Sorrentino intendi? Ricordi il titolo o l'anno?",
}


def test_clarification_runs_no_tool_and_answers_with_the_question() -> None:
    orch, tools, client = _orchestrator(CLARIFY_PLAN, tools=("rag_search", "tmdb_search"))

    decision = orch.run(query="Oh, ma chi c'era in quel film di Sorrentino…", conversation_history=[])

    assert decision["tool"] is None and decision["clarification"] is True
    assert decision["final_answer"] == CLARIFY_PLAN["clarification_question"]
    assert decision["result"] == {"query": decision["standalone_query"], "chunks": [], "metadata": {}, "trace": []}
    assert all(tool.queries == [] for tool in tools.values())
    assert len(client.calls) == 1  # planning only: no final-answer call


def test_clarification_without_a_question_falls_back_to_a_tool() -> None:
    plan = {**CLARIFY_PLAN, "tool_name": "rag_search", "clarification_question": "  "}
    orch, tools, _ = _orchestrator(plan)

    decision = orch.run(query="film di Sorrentino", conversation_history=[])

    assert decision["tool"] == "rag_search" and tools["rag_search"].queries == ["film di Sorrentino"]


def test_required_tools_are_never_replaced_by_a_clarification() -> None:
    orch, tools, _ = _orchestrator(CLARIFY_PLAN, required_tools=["rag_search"])

    decision = orch.run(query="e quello?", conversation_history=HISTORY)

    assert decision["tool"] == "rag_search" and len(tools["rag_search"].queries) == 1


def test_normal_turns_ignore_a_false_clarification_flag() -> None:
    plan = {"standalone_query": "x", "tool_name": "rag_search", "confidence": 0.9, "needs_clarification": False,
            "clarification_question": "?"}
    orch, tools, _ = _orchestrator(plan)

    assert orch.run(query="film con robot", conversation_history=[])["tool"] == "rag_search"


def _plan_with_parts(first_tool, parts, more=False):
    return json.dumps(
        {
            "standalone_query": "q",
            "tool_name": first_tool,
            "arguments": {},
            "confidence": 0.9,
            "more_steps": more,
            "parts": parts,
        }
    )


FILM_AND_INTERVIEW = [
    {"part": "un film con DiCaprio", "tool": "tmdb_search"},
    {"part": "un'intervista all'attore", "tool": "youtube_search"},
]


def test_a_part_for_another_tool_means_another_step_even_if_more_steps_is_false() -> None:
    orch, tools, client = _multi(
        [_plan_with_parts("tmdb_search", FILM_AND_INTERVIEW, more=False), _step("youtube_search"), "ok"]
    )

    decision = orch.run(query="x", conversation_history=[])

    assert decision["tools"] == ["tmdb_search", "youtube_search"]
    assert decision["planning"]["pending"] == [] and decision["planning"]["stop_reason"] == "complete"
    # The next-step prompt names the part still to do.
    assert "un'intervista all'attore" in client.calls[1]["input"][-1]["content"]


def test_parts_that_name_an_unknown_tool_are_ignored() -> None:
    parts = [{"part": "qualcosa", "tool": "inventato"}, {"part": "", "tool": "tmdb_search"}, "male"]
    orch, _, client = _multi([_plan_with_parts("tmdb_search", parts)])

    decision = orch.run(query="x", conversation_history=[])

    assert decision["tools"] == ["tmdb_search"] and decision["planning"]["parts"] == []
    assert len(client.calls) == 2


def test_an_unrun_part_is_declared_not_searched_in_the_final_prompt() -> None:
    """The real failure: the interview was never searched, yet the answer said "not found"."""
    orch, tools, client = _multi(
        [_plan_with_parts("tmdb_search", FILM_AND_INTERVIEW), json.dumps({"done": True}), "ok"]
    )

    decision = orch.run(query="x", conversation_history=[])

    assert decision["tools"] == ["tmdb_search"]
    assert decision["planning"]["stop_reason"] == "done"
    assert decision["planning"]["pending"] == [FILM_AND_INTERVIEW[1]]
    final_prompt = client.calls[-1]["input"][-1]["content"]
    assert "NON eseguite" in final_prompt and "un'intervista all'attore" in final_prompt
    assert "motivo: done" in final_prompt
    assert tools["youtube_search"].queries == []


@pytest.mark.parametrize(
    ("texts", "reason"),
    [
        ([_plan_with_parts("tmdb_search", FILM_AND_INTERVIEW), "not json", "ok"], "planner_failed"),
        (
            [
                _plan_with_parts("tmdb_search", FILM_AND_INTERVIEW),
                json.dumps({"tool_name": "youtube_search", "confidence": 0.1}),
                "ok",
            ],
            "unknown_tool_or_low_confidence",
        ),
    ],
)
def test_the_reason_the_turn_stopped_early_is_recorded(texts, reason) -> None:
    orch, _, _ = _multi(texts)

    planning = orch.run(query="x", conversation_history=[])["planning"]

    assert planning["stop_reason"] == reason and len(planning["pending"]) == 1


def test_a_single_tool_turn_has_no_pending_parts() -> None:
    orch, _, _ = _multi([_plan_with_parts("tmdb_search", [FILM_AND_INTERVIEW[0]])])

    planning = orch.run(query="x", conversation_history=[])["planning"]

    assert planning["pending"] == [] and planning["stop_reason"] == "complete"

