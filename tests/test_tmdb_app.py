from __future__ import annotations

import ast
import json
from pathlib import Path

from tmdb_support import MOVIE_ID, make_tool, movie_payload, search_movie_payload

import app as app_module
from orchestrator import LLMOrchestrator
from tmdb.enrich import TmdbRagEnricher
from tmdb.tool import TMDB_TOOL_NAME, TmdbTool

ROOT = Path(__file__).resolve().parents[1]


class FakeClient:
    """Planning call → `plan`; final answer otherwise. Keeps every request."""

    def __init__(self, plan: dict) -> None:
        self.outputs = [json.dumps(plan), "Risposta finale."]
        self.calls: list[dict] = []
        self.responses = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return type("Response", (), {"output_text": self.outputs.pop(0)})()


def _app(tool: TmdbTool, client: FakeClient) -> dict:
    config = app_module.build_runtime_config()
    return {"config": config, "orchestrator": LLMOrchestrator(config=config, tools=[tool], client=client)}


def _classify_italian(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "classify_query_domain", lambda q, history=None: {"is_cinema": True, "is_italian": True})


def _routing_rule(number: int) -> str:
    instructions = app_module.CONFIG["orchestrator"]["instructions"]
    start = instructions.index(f"{number}) ")
    end = instructions.find(f"{number + 1}) ", start)
    return instructions[start : end if end != -1 else len(instructions)]


def test_routing_rules_are_prioritized_by_need() -> None:
    """Regressions from the real TMDb run: "Parlami del film Arrival" and "Dimmi qualcosa su
    Dune" went to RAG; earlier, "cast" in the RAG sentence sent a director question to RAG."""
    tmdb, db, rag, mixed = (_routing_rule(n) for n in (1, 2, 3, 4))

    assert "prevalgono su ogni altra indicazione" in app_module.CONFIG["orchestrator"]["instructions"]
    assert tmdb.startswith(f"1) {TMDB_TOOL_NAME}") and "punto di partenza" in tmdb
    assert "parlami di Arrival" in tmdb and "dimmi qualcosa su Dune" in tmdb
    assert all(topic in tmdb for topic in ("chi ha diretto", "cast", "durata", "streaming", "ambiguo"))
    # Real eval: with "let TMDb results disambiguate" the planner used `search` (no credits).
    assert "usa movie_details o tv_details con il titolo" in tmdb and "search solo quando" in tmdb
    assert db.startswith("2) movie_db_search") and all(topic in db for topic in ("voti", "classifiche", "confronti"))
    assert rag.startswith("3) rag_search") and all(topic in rag for topic in ("raccomandazioni", "temi", "somiglianze"))
    assert "solo come riferimento" in rag and "non tmdb_search" in rag
    assert "cast" not in rag and "diretto" not in rag
    assert "un solo tool per turno" in mixed


def test_final_instructions_use_enrichment_sources_and_names_faithfully() -> None:
    final = app_module.CONFIG["orchestrator"]["final_instructions"]

    assert "tmdb_enrichment" in final and "'matched'" in final
    assert "stesso ordine" in final and "Non attribuire mai a un film i dati di un altro" in final
    assert "fonte dei voti" in final
    assert "candidates" in final and "quale versione" in final
    assert "alfabeto non latino" in final and "dichiarandola come tale" in final
    assert "work_type_verified false" in final
    assert "constraints_summary" in final and "senza aggiungere deduzioni tue" in final


def test_planner_can_ask_for_clarification_instead_of_searching() -> None:
    instructions = app_module.CONFIG["orchestrator"]["instructions"]

    assert "needs_clarification, clarification_question" in instructions
    assert "0) Chiarimento" in instructions and "Sorrentino" in instructions
    assert "Non dedurre un titolo dalla sola menzione di una persona" in instructions


def test_build_app_registers_the_tool(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    orchestrator = app_module.build_app({"tmdb": {"max_results": 3}})["orchestrator"]

    tool = orchestrator.tools[TMDB_TOOL_NAME]
    assert isinstance(tool, TmdbTool) and tool.config.max_results == 3
    assert TMDB_TOOL_NAME in orchestrator._allowed_tool_names()
    assert TMDB_TOOL_NAME in app_module.CONFIG["orchestrator"]["instructions"]
    assert tool.credentials is None  # `.env` is read on first use, not at build time


def test_build_app_registers_the_rag_enricher_on_the_same_tmdb_tool(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    enabled = app_module.build_app()["orchestrator"]
    disabled = app_module.build_app({"orchestrator": {"rag_enrichment": {"enabled": False}}})["orchestrator"]

    enricher = enabled.enrichers["rag_search"]
    assert isinstance(enricher, TmdbRagEnricher) and enricher.tool is enabled.tools[TMDB_TOOL_NAME]
    assert enricher.max_candidates == app_module.CONFIG["orchestrator"]["rag_enrichment"]["max_candidates"]
    assert set(enabled.enrichers) == {"rag_search"}
    assert disabled.enrichers == {}


def test_tmdb_step_reaches_the_turn_with_the_turn_language(monkeypatch) -> None:
    _classify_italian(monkeypatch)
    tool, transport = make_tool({"/search/movie": search_movie_payload(), f"/movie/{MOVIE_ID}": movie_payload()})
    plan = {
        "standalone_query": "Chi ha diretto Interstellar?",
        "tool_name": TMDB_TOOL_NAME,
        "arguments": {"requests": [{"operation": "movie_details", "title": "Interstellar", "facets": ["credits"]}]},
        "confidence": 0.9,
    }
    client = FakeClient(plan)

    turn = app_module.handle_query(_app(tool, client), "Chi ha diretto Interstellar?", history=[])

    assert turn.tool == TMDB_TOOL_NAME and turn.answer == "Risposta finale."
    assert [s.kind for s in turn.steps] == ["classification", "query_rewrite", "tool_selection", "tmdb_calls"]
    assert turn.steps[-1].data["calls"][-1].endswith(f"/movie/{MOVIE_ID}?api_key=***")
    assert transport.params(f"/movie/{MOVIE_ID}")["language"] == "it-IT"
    final_prompt = client.calls[-1]["input"][-1]["content"]
    assert "Christopher Nolan" in final_prompt and "api_key" not in final_prompt


def test_planner_sees_the_tool_catalog(monkeypatch) -> None:
    _classify_italian(monkeypatch)
    tool, _ = make_tool({})
    client = FakeClient({"standalone_query": "x", "tool_name": TMDB_TOOL_NAME, "arguments": {}, "confidence": 0.9})

    app_module.handle_query(_app(tool, client), "trending?", history=[])

    instructions = client.calls[0]["instructions"]
    assert '"name":"tmdb_search"' in instructions
    assert "movie_details:" in instructions and '"requests"' in instructions


def test_invalid_planner_arguments_still_produce_an_answer_without_http(monkeypatch) -> None:
    _classify_italian(monkeypatch)
    tool, transport = make_tool({})
    client = FakeClient({"standalone_query": "x", "tool_name": TMDB_TOOL_NAME, "arguments": {"url": "https://x"}, "confidence": 0.9})

    turn = app_module.handle_query(_app(tool, client), "domanda", history=[])

    assert transport.calls == [] and turn.answer == "Risposta finale."
    assert [s.kind for s in turn.steps][-1] == "tool_selection"  # no calls step: nothing was called


def test_runtime_never_imports_the_tmdb_harness() -> None:
    runtime_files = [ROOT / "app.py", *[p for p in sorted((ROOT / "tmdb").rglob("*.py")) if "harness" not in p.parts]]
    for path in runtime_files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "harness" not in node.module, path
