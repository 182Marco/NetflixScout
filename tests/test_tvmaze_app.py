"""Offline tests of the TVmaze integration: registration, routing rule text, how `content_type`
reaches the planner, per-tool final rules and the fallback to TMDb.

These check wiring and prompt *text*: they are not evidence of what the real planner chooses. That is
measured only by the live routing evaluation, which needs a separate authorization.
"""
from __future__ import annotations

import json
import re

from stream_support import reply
from tvmaze_support import make_tool, routes_for

import app as app_module
from orchestrator import LLMOrchestrator
from preferences import behavior, build_prompt_parts, resolve_preferences
from tool.tvmaze.tool import TVMAZE_TOOL_NAME

INSTRUCTIONS = app_module.CONFIG["orchestrator"]["instructions"]
RULES = app_module.CONFIG["orchestrator"]["tool_final_instructions"]


def _rule(label: str, next_label: str) -> str:
    start = INSTRUCTIONS.index(f"{label}) ")
    return INSTRUCTIONS[start : INSTRUCTIONS.index(f"{next_label}) ", start)]


class FakeClient:
    """Each planning call returns the next plan; the final answer is plain text."""

    def __init__(self, *plans: dict) -> None:
        self.outputs = [json.dumps(plan) for plan in plans] + ["Risposta finale."]
        self.calls: list[dict] = []
        self.responses = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return reply(self.outputs.pop(0), kwargs)


class _Tmdb:
    name = "tmdb_search"
    description = "TMDb"
    input_schema = {"type": "object"}

    def run(self, *, query, params=None, conversation_history=None):
        return {"query": query, "chunks": [], "metadata": {"tmdb": {"ok": True}}, "trace": []}


def _planner(**prefs) -> str:
    return build_prompt_parts(resolve_preferences(prefs).preferences)["planner"]


def test_it_is_registered_allowed_and_in_the_planner_catalog(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    orchestrator = app_module.build_app()["orchestrator"]

    assert TVMAZE_TOOL_NAME in app_module.CONFIG["orchestrator"]["allowed_tools"]
    assert app_module.CONFIG["tvmaze"] == {"max_calls_per_turn": 6}
    assert orchestrator.tools[TVMAZE_TOOL_NAME].config.max_calls_per_turn == 6
    catalog = orchestrator._catalog_text(orchestrator._allowed_tool_names())
    assert '"name":"tvmaze_search"' in catalog and "facets" in catalog


def test_rule_1e_sits_after_1d_and_before_movie_db_and_leaves_the_others_alone() -> None:
    assert INSTRUCTIONS.index("1d) omdb_search") < INSTRUCTIONS.index("1e) tvmaze_search") < INSTRUCTIONS.index("2) movie_db_search")
    assert _rule("1d", "1e").startswith("1d) omdb_search") and _rule("2", "3").startswith("2) movie_db_search")
    assert "tvmaze" not in _rule("3", "4") and "tvmaze" not in _rule("1c", "1d")


def test_rule_1_hands_the_structured_series_data_to_1e_without_duplicating_them() -> None:
    rule1 = _rule("1", "1b")

    assert "stagioni ed episodi" not in rule1 and "regola 1e" in rule1
    assert "descrizione, creatori, streaming, trailer, recensioni, raccomandazioni, elenchi" in rule1


def test_rule_1e_prefers_tvmaze_for_structured_series_data_and_keeps_the_other_requests_elsewhere() -> None:
    rule = _rule("1e", "2")

    for structured in ("stagioni", "numerazione", "prossimo episodio", "cast e personaggi", "in onda o conclusa"):
        assert structured in rule
    for elsewhere in ("streaming", "trailer", "raccomandazioni", "tmdb_search, regola 1", "film"):
        assert elsewhere in rule
    assert "Una fonte chiesta esplicitamente dall'utente vince sempre" in rule
    assert "non obbliga a usare tvmaze_search: decide l'intento" in rule


def test_rule_1e_allows_one_fallback_step_and_never_a_second_try() -> None:
    rule = _rule("1e", "2")

    assert "UN solo passo successivo con tmdb_search" in rule and "mai un secondo tentativo con tvmaze_search" in rule
    assert "ambiguo non cercare altrove" in rule


def test_the_series_preference_orients_the_content_without_forcing_tvmaze() -> None:
    text = behavior.CONTENT_PLANNER["series"]

    assert "regola 1e" in text and "non obbliga a usare tvmaze_search" in text
    assert "rag_search" in text and "movie_db_search" in text
    assert "tvmaze" not in behavior.CONTENT_PLANNER["film"]
    assert "tvmaze" not in _planner(content_type="film") and "tvmaze" in _planner(content_type="series")


def test_tvmaze_serves_official_information_and_no_source_preference_adds_a_call_to_it() -> None:
    assert behavior.SOURCE_TOOLS[TVMAZE_TOOL_NAME] == "official information"
    for source in ("reviews", "interviews", "official information", "user ratings"):
        assert "tvmaze" not in _planner(preferred_sources=source).lower()


def test_a_reviews_preference_keeps_its_own_rule_and_does_not_reroute_a_structure_request() -> None:
    """Intent beats the preference: the `reviews` text only concerns critic scores (rule 1d)."""
    text = _planner(preferred_sources="reviews", content_type="series")

    assert "regola 1d" in text and "regola 1e" in text
    assert "esplicitamente il giudizio o i punteggi della critica" in _rule("1d", "1e")
    assert "episodi" not in _rule("1d", "1e")


def test_the_final_rule_reaches_only_tvmaze_turns_and_names_no_provider() -> None:
    tvmaze, _ = make_tool(routes_for())
    config = app_module.build_runtime_config()

    def final_instructions(plan: dict, tool) -> str:
        client = FakeClient(plan)
        LLMOrchestrator(config=config, tools=[tool], client=client).run(query="domanda", conversation_history=[])
        return client.calls[1]["instructions"]

    own = final_instructions({"tool_name": "tvmaze_search", "arguments": {"title": "Sample Show"}, "confidence": 0.9}, tvmaze)
    other = final_instructions({"tool_name": "tmdb_search", "arguments": {}, "confidence": 0.9}, _Tmdb())

    assert own.endswith(RULES["tvmaze_search"]) and RULES["tvmaze_search"] not in other
    assert not re.search(r"TMDb|OMDb|MovieLens|Wikipedia|YouTube|TVmaze|\bRAG\b", RULES["tvmaze_search"])
    assert "le fonti non coincidono" in RULES["tvmaze_search"] and "non inventarle" in RULES["tvmaze_search"]


def test_when_tvmaze_cannot_find_the_series_the_planner_goes_to_tmdb_once_and_tvmaze_is_not_asked_again() -> None:
    tvmaze, transport = make_tool({"/search/shows": []})
    first = {"tool_name": "tvmaze_search", "arguments": {"title": "La casa di carta"}, "confidence": 0.9}
    second = {"tool_name": "tmdb_search", "arguments": {}, "confidence": 0.9}
    client = FakeClient(first, second)
    config = app_module.build_runtime_config()

    decision = LLMOrchestrator(config=config, tools=[tvmaze, _Tmdb()], client=client).run(
        query="Cast di La casa di carta", conversation_history=[]
    )

    assert decision["tools"] == ["tvmaze_search", "tmdb_search"]
    assert len(transport.calls) == 1  # TVmaze asked once
    assert len(client.calls) == 3  # first plan, second plan, final answer: no superfluous step
    assert "tvmaze_search" in client.calls[1]["input"][-1]["content"] or "can look the series up" in client.calls[1]["input"][-1]["content"]
