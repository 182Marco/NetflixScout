"""Offline tests of the Wikidata integration: registration, routing rule text, per-tool final rules, the user
settings and the fallback to other tools.

These check wiring and prompt *text*: they are not evidence of what the real planner chooses. That is
measured only by the live routing evaluation, which needs a separate authorization.
"""
from __future__ import annotations

import json
import re

from stream_support import reply
from wikidata_support import make_tool, routes_for

import app as app_module
from orchestrator import LLMOrchestrator
from preferences import behavior, build_prompt_parts, resolve_preferences
from tool.wikidata.tool import WIKIDATA_TOOL_NAME

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


class _Other:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = name
        self.input_schema = {"type": "object"}

    def run(self, *, query, params=None, conversation_history=None):
        return {"query": query, "chunks": [], "metadata": {self.name: {"ok": True}}, "trace": []}


def _planner(**prefs) -> str:
    return build_prompt_parts(resolve_preferences(prefs).preferences)["planner"]


def test_it_is_registered_allowed_and_in_the_planner_catalog(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    orchestrator = app_module.build_app()["orchestrator"]

    assert WIKIDATA_TOOL_NAME in app_module.CONFIG["orchestrator"]["allowed_tools"]
    assert app_module.CONFIG["wikidata"] == {"max_calls_per_turn": 8}
    assert orchestrator.tools[WIKIDATA_TOOL_NAME].config.max_calls_per_turn == 8
    catalog = orchestrator._catalog_text(orchestrator._allowed_tool_names())
    assert '"name":"wikidata_search"' in catalog and "operation" in catalog and "imdb_id" in catalog


def test_rule_1f_sits_after_1e_and_before_movie_db_and_leaves_the_others_alone() -> None:
    assert INSTRUCTIONS.index("1e) tvmaze_search") < INSTRUCTIONS.index("1f) wikidata_search") < INSTRUCTIONS.index("2) movie_db_search")
    assert _rule("1e", "1f").startswith("1e) tvmaze_search") and _rule("2", "3").startswith("2) movie_db_search")
    before_1f = INSTRUCTIONS[: INSTRUCTIONS.index("1f) wikidata_search")]
    after_1f = INSTRUCTIONS[INSTRUCTIONS.index("2) movie_db_search") :]
    assert "wikidata" not in before_1f and "wikidata" not in after_1f


def test_rule_1f_prefers_wikidata_for_relations_between_works_and_leaves_the_rest_elsewhere() -> None:
    rule = _rule("1f", "2")

    for relation in ("da quale libro", "remake", "prima o dopo", "franchise", "operation resolve"):
        assert relation in rule
    for elsewhere in ("cast", "trama", "premi", "punteggi", "streaming", "trailer", "raccomandazioni", "filmografie", "tmdb_search, regola 1", "regola 1c"):
        assert elsewhere in rule
    assert "Una fonte chiesta esplicitamente dall'utente vince sempre" in rule


def test_rule_1f_never_makes_the_identification_a_preliminary_step_and_never_lets_ids_be_invented() -> None:
    rule = _rule("1f", "2")

    assert "non chiamarlo come passo preliminare di ogni ricerca" in rule
    assert "mai scritti a memoria" in rule and "solo se compaiono nella richiesta, nella conversazione o in un passo già fatto" in rule
    assert "un elenco vuoto non prova che non ne esistano" in rule


def test_rule_1f_allows_one_fallback_step_and_never_a_second_try() -> None:
    rule = _rule("1f", "2")

    assert "UN solo passo successivo con tmdb_search o wikipedia_search" in rule and "mai un secondo tentativo con wikidata_search" in rule
    assert "ambiguo non cercare altrove" in rule


def test_wikidata_serves_official_information_and_no_preference_names_it_or_adds_a_call_to_it() -> None:
    assert behavior.SOURCE_TOOLS[WIKIDATA_TOOL_NAME] == "official information"
    for source in ("reviews", "interviews", "official information", "user ratings"):
        for content in ("film", "series", "both"):
            assert "wikidata" not in _planner(preferred_sources=source, content_type=content).lower()


def test_the_interviews_preference_keeps_its_own_rule_and_does_not_reroute_a_relations_request() -> None:
    """Intent beats the preference: the text only concerns videos (rule 1b) and names no other tool."""
    text = _planner(preferred_sources="interviews")

    assert "regola 1b" in text and "wikidata" not in text and "1f" not in text
    assert "esplicitamente" not in _rule("1f", "2") or "vince sempre" in _rule("1f", "2")


def test_the_final_rule_reaches_only_wikidata_turns_and_names_no_provider_nor_item_codes() -> None:
    tool, _ = make_tool(routes_for())
    config = app_module.build_runtime_config()

    def final_instructions(plan: dict, used) -> str:
        client = FakeClient(plan)
        LLMOrchestrator(config=config, tools=[used], client=client).run(query="domanda", conversation_history=[])
        return client.calls[1]["instructions"]

    own = final_instructions(
        {"tool_name": "wikidata_search", "arguments": {"operation": "resolve", "title": "Sample Film", "year": 1982}, "confidence": 0.9}, tool
    )
    other = final_instructions({"tool_name": "tmdb_search", "arguments": {}, "confidence": 0.9}, _Other("tmdb_search"))

    text = RULES["wikidata_search"]
    assert own.endswith(text) and text not in other
    assert not re.search(r"TMDb|OMDb|MovieLens|Wikipedia|Wikidata|YouTube|TVmaze|\bIMDb\b|\bRAG\b", text)
    for sentence in ("non presentare mai l'elenco come completo", "non chiamarle tutte remake", "non se un'opera è un sequel", "chiedi quale intende", "le fonti non coincidono"):
        assert sentence in text


def test_when_wikidata_cannot_find_the_work_the_planner_goes_elsewhere_once_and_wikidata_is_not_asked_again() -> None:
    tool, transport = make_tool({"search": {"search": []}})
    first = {"tool_name": "wikidata_search", "arguments": {"operation": "relations", "title": "La cosa"}, "confidence": 0.9}
    second = {"tool_name": "tmdb_search", "arguments": {}, "confidence": 0.9}
    client = FakeClient(first, second)
    config = app_module.build_runtime_config()

    decision = LLMOrchestrator(config=config, tools=[tool, _Other("tmdb_search")], client=client).run(
        query="Da cosa è tratto La cosa?", conversation_history=[]
    )

    assert decision["tools"] == ["wikidata_search", "tmdb_search"]
    assert len(transport.calls) == 2  # Wikidata asked once: by label, then by text search
    assert len(client.calls) == 3  # first plan, second plan, final answer: no superfluous step
    assert "tmdb_search" in client.calls[1]["input"][-1]["content"]


def test_an_ambiguous_title_ends_the_turn_without_looking_elsewhere() -> None:
    tool, _ = make_tool(routes_for())
    plan = {"tool_name": "wikidata_search", "arguments": {"operation": "resolve", "title": "Sample Film"}, "confidence": 0.9}
    client = FakeClient(plan)
    config = app_module.build_runtime_config()

    decision = LLMOrchestrator(config=config, tools=[tool], client=client).run(query="Quale Sample Film?", conversation_history=[])

    assert decision["tools"] == ["wikidata_search"] and len(client.calls) == 2  # one plan, one answer
