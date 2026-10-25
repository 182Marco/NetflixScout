"""Offline tests of the step 9 integration: registration, availability, routing rule text,
per-tool final rules and startup notice.

These tests check wiring and prompt *text* with fake clients: they are not evidence of what
the real planner chooses. That is measured only by the live routing and E2E evaluations,
which need a separate authorization.
"""
from __future__ import annotations

import json

from youtube_support import make_tool, search_item, video_item

import app as app_module
from orchestrator import LLMOrchestrator
from presenters import OutputChannel, present
from turn import STEP_YOUTUBE_CALLS
from youtube.tool import YOUTUBE_TOOL_NAME, YoutubeTool
from stream_support import reply

INSTRUCTIONS = app_module.CONFIG["orchestrator"]["instructions"]


def _rule(label: str, next_label: str) -> str:
    start = INSTRUCTIONS.index(f"{label}) ")
    return INSTRUCTIONS[start : INSTRUCTIONS.index(f"{next_label}) ", start)]


class FakeClient:
    """Planning call -> `plan`; final answer otherwise. Keeps every request."""

    def __init__(self, plan: dict) -> None:
        self.outputs = [json.dumps(plan), "Risposta finale."]
        self.calls: list[dict] = []
        self.responses = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return reply(self.outputs.pop(0), kwargs)


# --- registration and availability -------------------------------------------------------------


def test_build_app_registers_the_youtube_tool_from_you_tube_config(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    orchestrator = app_module.build_app({"you_tube": {"max_results": 5}})["orchestrator"]

    tool = orchestrator.tools[YOUTUBE_TOOL_NAME]
    assert isinstance(tool, YoutubeTool) and tool.config.max_results == 5
    assert tool.config.max_searches_per_turn == app_module.CONFIG["you_tube"]["max_searches_per_turn"]
    assert tool.credentials is None  # `.env` is read on first use, not at build time


def test_youtube_is_allowed_and_in_the_planner_catalog(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    orchestrator = app_module.build_app()["orchestrator"]

    assert app_module.CONFIG["orchestrator"]["allowed_tools"][-1] == YOUTUBE_TOOL_NAME
    assert YOUTUBE_TOOL_NAME in orchestrator._allowed_tool_names()
    catalog = orchestrator._catalog_text(orchestrator._allowed_tool_names())
    assert '"name":"youtube_search"' in catalog and "cast_interview" in catalog


def test_the_rag_enricher_and_the_fallback_are_unchanged(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    orchestrator = app_module.build_app()["orchestrator"]

    assert set(orchestrator.enrichers) == {"rag_search"}
    assert app_module.CONFIG["orchestrator"]["fallback_tool"] == "rag_search"


# --- routing rule text (not the planner's behaviour) ---------------------------------------------


def test_rule_1b_sits_between_tmdb_and_movie_db() -> None:
    assert INSTRUCTIONS.index("1) tmdb_search") < INSTRUCTIONS.index("1b) youtube_search") < INSTRUCTIONS.index("2) movie_db_search")


def test_rule_1b_names_the_video_kinds_and_keeps_trailers_on_tmdb() -> None:
    rule = _rule("1b", "2")

    assert rule.startswith("1b) youtube_search è il punto di partenza per i video su un film identificato")
    for topic in ("director_interview", "cast_interview", "making-of", "dietro le quinte", "backstage", "commenti"):
        assert topic in rule
    assert "Per i trailer resta tmdb_search" in rule
    assert "chieda esplicitamente YouTube o accetti la proposta" in rule


def test_rule_1b_forbids_inventing_arguments() -> None:
    rule = _rule("1b", "2")

    assert "year, director, cast e alternative_titles" in rule
    assert "non inventarli, non tradurli e non dedurli" in rule


def test_rule_1_marks_tmdb_trailers_as_official_links_and_rag_rule_is_unchanged() -> None:
    assert "trailer (link ufficiali TMDb)" in _rule("1", "1b")
    rag = _rule("3", "4")
    assert rag.startswith("3) rag_search") and "youtube" not in rag.lower()


# --- per-tool final rules ---------------------------------------------------------------------


def _turn(plan: dict, tool) -> FakeClient:
    client = FakeClient(plan)
    config = app_module.build_runtime_config()
    orchestrator = LLMOrchestrator(config=config, tools=[tool], client=client)
    orchestrator.run(query="domanda", conversation_history=[])
    return client


class _FakeTmdb:
    name = "tmdb_search"
    description = "TMDb"
    input_schema = {"type": "object"}

    def run(self, *, query, params=None, conversation_history=None):
        return {"query": query, "chunks": [], "metadata": {}, "trace": []}


def test_youtube_final_rules_only_on_youtube_turns() -> None:
    youtube_rules = app_module.CONFIG["orchestrator"]["tool_final_instructions"]["youtube_search"]
    tool, _ = make_tool({"/search": {"items": []}})

    youtube_turn = _turn({"tool_name": "youtube_search", "arguments": {"title": "Dune", "kinds": ["making_of"]}, "confidence": 0.9}, tool)
    tmdb_turn = _turn({"tool_name": "tmdb_search", "arguments": {}, "confidence": 0.9}, _FakeTmdb())

    youtube_final = youtube_turn.calls[1]["instructions"]
    tmdb_final = tmdb_turn.calls[1]["instructions"]
    assert youtube_final.endswith(youtube_rules) and youtube_rules not in tmdb_final
    assert tmdb_final == app_module.CONFIG["orchestrator"]["final_instructions"]


def test_orchestrator_without_tool_rules_keeps_the_previous_behaviour() -> None:
    config = app_module.build_runtime_config()
    config["orchestrator"].pop("tool_final_instructions")
    orchestrator = LLMOrchestrator(config=config, tools=[_FakeTmdb()], client=FakeClient({}))

    assert orchestrator._final_instructions("youtube_search") == config["orchestrator"]["final_instructions"]
    assert orchestrator._final_instructions(None) == config["orchestrator"]["final_instructions"]


def test_tmdb_final_rules_offer_youtube_when_no_trailer_is_found() -> None:
    final = app_module.CONFIG["orchestrator"]["final_instructions"]

    assert "Se il tool usato è tmdb_search, sono stati chiesti i video e non risultano trailer" in final
    assert "proponi di cercarli su YouTube" in final


# --- the whole turn with fake clients -------------------------------------------------------


def test_a_planned_youtube_turn_reaches_the_presenter(monkeypatch, capsys) -> None:
    monkeypatch.setattr(app_module, "classify_query_domain", lambda q, history=None: {"is_cinema": True, "is_italian": True})
    tool, transport = make_tool(
        {
            "/search": {"items": [search_item("vid00000001", "Interstellar - Making of")]},
            "/videos": {"items": [video_item("vid00000001", "Interstellar - Making of", description="Making of the film.")]},
        }
    )
    plan = {"standalone_query": "Making of di Interstellar", "tool_name": "youtube_search", "arguments": {"title": "Interstellar", "kinds": ["making_of"]}, "confidence": 0.9}
    client = FakeClient(plan)
    config = app_module.build_runtime_config()
    built = {"config": config, "orchestrator": LLMOrchestrator(config=config, tools=[tool], client=client)}

    turn = app_module.handle_query(built, "Trovami il making of di Interstellar", [])
    present(turn, OutputChannel.terminal)

    assert turn.tool == "youtube_search" and STEP_YOUTUBE_CALLS in [step.kind for step in turn.steps]
    assert transport.paths == ["/search", "/videos"]
    assert "Interstellar - Making of" in capsys.readouterr().out
    # The turn language reached the tool and was ignored without a validation error.
    assert turn.answer == "Risposta finale."

