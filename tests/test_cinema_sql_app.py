"""Offline tests of the `cinema_sql` integration: the feature flag, the registration, the routing rule that exists only while the tool is on, the user settings, the fallback to the
external tools and the turn through the orchestrator with the REAL tool on a miniature database.

They check wiring and prompt *text*: they are not evidence of what the real planner chooses. That is measured by the live evaluation (docs/cinema_db/PHASE6_LIVE.md).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from cinema_build_support import make_inputs, make_phase4
from stream_support import reply

import app as app_module
from cinema_db.harness.build.build import Inputs, run_build
from orchestrator import LLMOrchestrator
from preferences import SettingsPolicy, behavior, build_prompt_parts, resolve_preferences
from tool.cinema_db.config import CinemaDbConfig
from tool.cinema_db.tool import CinemaSqlTool
from turn import STEP_CINEMA_SQL_CALLS, NullObserver, TraceStep

CONFIG = app_module.CONFIG
INSTRUCTIONS = CONFIG["orchestrator"]["instructions"]
RULE = app_module.CINEMA_SQL_ROUTING_RULE


@pytest.fixture(scope="module")
def tool(tmp_path_factory) -> CinemaSqlTool:
    tmp = tmp_path_factory.mktemp("cinema_app")
    base = make_inputs(tmp, awards_demo=True)
    out = tmp / "out" / "cinema.sqlite3"
    run_build(out, Inputs(base.film_snapshot, base.series_snapshot, base.film_catalog, base.series_dir, phase4=make_phase4(tmp / "p4")), log=lambda *_: None)
    return CinemaSqlTool(config=CinemaDbConfig(enabled=True, db_path=str(out), max_queries_per_turn=12, default_limit=25))


class FakeClient:
    def __init__(self, *plans: dict) -> None:
        self.outputs = [json.dumps(plan) for plan in plans] + ["Risposta finale."]
        self.calls: list[dict] = []
        self.responses = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return reply(self.outputs.pop(0), kwargs)


class Other:
    def __init__(self, name: str) -> None:
        self.name, self.description, self.input_schema = name, name, {"type": "object"}
        self.runs = 0

    def run(self, *, query, params=None, conversation_history=None):
        self.runs += 1
        return {"query": query, "chunks": [], "metadata": {self.name: {"ok": True}}, "trace": []}


class Steps(NullObserver):
    def __init__(self) -> None:
        self.steps: list[TraceStep] = []

    def step(self, step: TraceStep) -> None:
        self.steps.append(step)


def policy(**values) -> SettingsPolicy:
    return SettingsPolicy(resolve_preferences(values).preferences)


# ---- the feature flag and the registration ------------------------------------------------------------------------------------------
def test_the_flag_is_off_by_default_and_the_config_has_exactly_the_documented_keys() -> None:
    assert CONFIG["cinema_db"] == {"enabled": False, "db_path": "cinema_db/data/cinema.sqlite3", "max_queries_per_turn": 12, "default_limit": 25}
    assert "cinema_sql" in CONFIG["orchestrator"]["allowed_tools"] and "cinema_sql" in CONFIG["orchestrator"]["tool_final_instructions"]


def test_off_the_tool_is_not_registered_and_on_it_is(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    off = app_module.build_app()["orchestrator"]
    on = app_module.build_app({"cinema_db": {"enabled": True}})["orchestrator"]
    assert "cinema_sql" not in off.tools and "cinema_sql" not in off._allowed_tool_names()
    assert "cinema_sql" in on.tools and on.tools["cinema_sql"].config.max_queries_per_turn == 12
    assert [t for t in on.tools if t != "cinema_sql"] == list(off.tools)  # every other tool is the same, in the same order


def test_the_environment_variable_switches_the_flag_for_both_entry_points() -> None:
    assert app_module.cinema_db_overrides({}) == {} and app_module.cinema_db_overrides({"CINEMA_DB_ENABLED": "0"}) == {}
    for value in ("1", "true", "YES", " on "):
        assert app_module.cinema_db_overrides({"CINEMA_DB_ENABLED": value}) == {"cinema_db": {"enabled": True}}


def test_a_missing_database_with_the_flag_on_stops_the_start_with_the_command_to_build_it(tmp_path) -> None:
    app_module.ensure_cinema_db_ready({**CONFIG["cinema_db"], "enabled": False, "db_path": str(tmp_path / "none.sqlite3")})  # off: nothing to check
    with pytest.raises(RuntimeError, match="python -m cinema_db.harness.build.build"):
        app_module.ensure_cinema_db_ready({**CONFIG["cinema_db"], "enabled": True, "db_path": str(tmp_path / "none.sqlite3")})
    (tmp_path / "there.sqlite3").write_bytes(b"")
    app_module.ensure_cinema_db_ready({**CONFIG["cinema_db"], "enabled": True, "db_path": str(tmp_path / "there.sqlite3")})


# ---- the planner prompt --------------------------------------------------------------------------------------------------------------
def _prompt(orchestrator) -> str:
    return orchestrator._planning_instructions(orchestrator._allowed_tool_names(), "default")


def test_with_the_flag_off_the_planner_prompt_is_exactly_what_it_was_without_the_tool(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    off = app_module.build_app()["orchestrator"]
    without_rules = app_module.build_app({"orchestrator": {"tool_rules": {}}})["orchestrator"]
    assert _prompt(off) == _prompt(without_rules)
    assert "cinema_sql" not in _prompt(off) and "1g)" not in _prompt(off) and "cinema_sql" not in INSTRUCTIONS


def test_with_the_flag_on_the_rule_follows_the_instructions_and_the_catalog_has_the_tool(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    off, on = (_prompt(app_module.build_app(o)["orchestrator"]) for o in ({}, {"cinema_db": {"enabled": True}}))
    assert on.startswith(INSTRUCTIONS) and "\n" + RULE in on and on.index(RULE) < on.index("Allowed tools:")
    assert '"name":"cinema_sql"' in on and "operation" in on and "v_work(" in on
    assert on.replace("\n" + RULE, "").replace(", cinema_sql", "") .split("Tool catalog")[0] == off.split("Tool catalog")[0]  # the rule is the only change before the catalog


def test_the_routing_rule_covers_what_the_tool_answers_and_leaves_the_rest_to_the_other_tools() -> None:
    for covered in ("filmography", "crew", "cast", "collaborations", "awards", "relations", "franchise", "companies", "find_work", "find_person", "work_card", "quante stagioni"):
        assert covered in RULE
    for elsewhere in ("trama", "punteggi, voti e classifiche (1d, 2)", "streaming", "trailer", "novità", "ultimi film", "(1e", "(1c)", "consigli"):
        assert elsewhere in RULE
    assert "ha la precedenza sulle regole 1, 1e e 1f" in RULE


def test_the_rule_never_lets_an_empty_or_partial_result_end_the_search_and_keeps_wikidata_as_the_fallback() -> None:
    assert "non prova che l'informazione non esista" in RULE and "UN solo passo con lo strumento esterno" in RULE and "mai un secondo tentativo con cinema_sql" in RULE
    assert "wikidata_search resta sempre disponibile come ripiego" in RULE and "wikidata_search per relazioni" in RULE
    assert "non scegliere tu e non cercare altrove" in RULE and "la scelta è dell'utente" in RULE  # a namesake is never picked arbitrarily
    assert "mai un identificativo a memoria" in RULE.replace("non scrivere mai un identificativo a memoria", "mai un identificativo a memoria")
    assert "non distinguono remake" in RULE and "wikipedia_search" in RULE
    assert "i premi attribuiti a una persona" in RULE.lower() and "awards con il titolo" in RULE


# ---- the user settings -----------------------------------------------------------------------------------------------------------------
def test_cinema_sql_serves_official_information_and_never_reviews_or_user_ratings() -> None:
    assert behavior.SOURCE_TOOLS["cinema_sql"] == "official information"
    assert set(behavior.SOURCE_TOOLS) >= set(CONFIG["orchestrator"]["allowed_tools"])  # every allowed tool declares the preference it serves
    for source in ("reviews", "interviews", "official information", "user ratings"):
        for content in ("film", "series", "both"):
            assert "cinema" not in build_prompt_parts(resolve_preferences({"preferred_sources": source, "content_type": content}).preferences)["planner"].lower()


def test_the_content_type_is_applied_to_the_tool_through_its_type_argument() -> None:
    series, film, both = policy(content_type="series"), policy(content_type="film"), policy(content_type="both")
    assert series.check_step("cinema_sql", {"operation": "filmography", "person": "X"}).arguments == {"operation": "filmography", "person": "X", "type": "series"}
    assert film.check_step("cinema_sql", {"operation": "find_work", "title": "X"}).arguments == {"operation": "find_work", "title": "X", "type": "film"}
    assert both.check_step("cinema_sql", {"operation": "find_work", "title": "X"}).arguments == {"operation": "find_work", "title": "X"}
    assert series.check_step("cinema_sql", {"operation": "find_work", "title": "X", "type": "film"}).arguments is None  # the request names the forbidden kind
    assert film.check_step("cinema_sql", {"operation": "series", "title": "X"}).arguments is None  # a series-only operation under «film»
    assert series.check_step("cinema_sql", {"operation": "series", "title": "X"}).arguments == {"operation": "series", "title": "X", "type": "series"}
    verdict = series.check_step("cinema_sql", {"operation": "cast", "work_id": 5})
    assert verdict.arguments == {"operation": "cast", "work_id": 5}  # an id is the identity: nothing to filter
    assert series.check_step("cinema_sql", {"operation": "sql", "sql": "SELECT 1"}).arguments == {"operation": "sql", "sql": "SELECT 1"}


def test_an_explicit_request_for_another_source_is_the_planners_conflict_to_declare_and_the_guard_does_not_touch_it() -> None:
    """With `interviews` or `reviews` set, a filmography request is not a conflict (it is not another SOURCE of judgement); the guard only enforces the content type."""
    for source in ("interviews", "reviews", "user ratings", "official information"):
        p = policy(preferred_sources=source)
        assert p.check_step("cinema_sql", {"operation": "filmography", "person": "Christopher Nolan"}).arguments == {"operation": "filmography", "person": "Christopher Nolan"}


# ---- a turn through the orchestrator with the real tool ----------------------------------------------------------------------------------
def _run(tool: CinemaSqlTool, *plans: dict, others=()):
    client = FakeClient(*plans)
    observer = Steps()
    config = app_module.build_runtime_config()
    decision = LLMOrchestrator(config=config, tools=[tool, *others], client=client).run(query="domanda", conversation_history=[], observer=observer)
    return decision, client, observer


def test_a_turn_answers_from_the_local_archive_with_one_planner_step_and_no_other_tool(tool) -> None:
    plan = {"tool_name": "cinema_sql", "arguments": {"operation": "filmography", "person": "Ann Regista"}, "confidence": 0.9}
    tmdb = Other("tmdb_search")
    decision, client, observer = _run(tool, plan, others=[tmdb])
    assert decision["tools"] == ["cinema_sql"] and tmdb.runs == 0 and len(client.calls) == 2  # one plan, one answer: no superfluous step
    metadata = decision["result"]["metadata"]["cinema_db"]
    assert metadata["status"] == "ok" and [w["title"] for w in metadata["works"]] == ["Prequel di prova", "Film di prova"]
    steps = [s for s in observer.steps if s.kind == STEP_CINEMA_SQL_CALLS]
    assert len(steps) == 1 and steps[0].data["queries_count"] >= 3 and "calls" not in steps[0].data
    prompt = client.calls[1]["input"][-1]["content"] if isinstance(client.calls[1]["input"][-1]["content"], str) else json.dumps(client.calls[1]["input"])
    assert "wikipedia_it" not in prompt and "Ann_Regista" not in prompt  # the page titles are for the interface's links, not for the model
    assert client.calls[1]["instructions"].endswith(CONFIG["orchestrator"]["tool_final_instructions"]["cinema_sql"])


def test_the_final_rule_of_the_tool_reaches_only_its_own_turns_and_names_no_provider_nor_code() -> None:
    text = CONFIG["orchestrator"]["tool_final_instructions"]["cinema_sql"]
    assert not re.search(r"\bTMDb\b.*provenienza|OMDb|MovieLens|YouTube|TVmaze|\bRAG\b", text.replace("(id interni, IMDb, TMDb, Wikidata)", ""))
    for sentence in ("tra quelli registrati", "ambiguous", "unverified", "not_found", "non prova"):
        assert sentence in text
    other_tool = Other("tmdb_search")
    client = FakeClient({"tool_name": "tmdb_search", "arguments": {}, "confidence": 0.9})
    LLMOrchestrator(config=app_module.build_runtime_config(), tools=[other_tool], client=client).run(query="domanda", conversation_history=[])
    assert text not in client.calls[1]["instructions"]


def test_a_not_found_result_leads_to_exactly_one_external_step_and_cinema_sql_is_not_asked_again(tool) -> None:
    first = {"tool_name": "cinema_sql", "arguments": {"operation": "filmography", "person": "Nessuno Esiste"}, "confidence": 0.9}
    second = {"tool_name": "tmdb_search", "arguments": {}, "confidence": 0.9}
    tmdb = Other("tmdb_search")
    decision, client, observer = _run(tool, first, second, others=[tmdb])
    assert decision["tools"] == ["cinema_sql", "tmdb_search"] and tmdb.runs == 1 and len(client.calls) == 3  # plan, plan, answer
    summary = client.calls[1]["input"][-1]["content"]
    assert "does not prove" in summary and "tmdb_search" in summary  # the planner is told the local gap is not a proof and where to look once
    assert [s.data["status"] for s in observer.steps if s.kind == STEP_CINEMA_SQL_CALLS] == ["not_found"]


def test_an_ambiguous_title_ends_the_turn_without_looking_elsewhere_and_without_choosing(tool) -> None:
    # two identifiers that point at different works: the tool lists both and picks neither (the miniature has no namesakes)
    plan = {"tool_name": "cinema_sql", "arguments": {"operation": "find_work", "imdb_id": "tt9000001", "wikidata_id": "Q9003"}, "confidence": 0.9}
    tmdb = Other("tmdb_search")
    decision, client, _ = _run(tool, plan, others=[tmdb])
    metadata = decision["result"]["metadata"]["cinema_db"]
    assert decision["tools"] == ["cinema_sql"] and tmdb.runs == 0 and len(client.calls) == 2  # one plan, one answer: nobody searches elsewhere
    assert metadata["status"] == "ambiguous" and len(metadata["candidates"]) == 2 and "subject" not in metadata and "follow_up" not in decision["result"]


def test_an_id_given_by_the_planner_skips_the_name_search_and_a_bad_request_is_an_error_not_a_crash(tool) -> None:
    first = tool.run(query="q", params={"operation": "find_work", "title": "Film di prova"})["metadata"]["cinema_db"]["subject"]["work_id"]
    decision, _, observer = _run(tool, {"tool_name": "cinema_sql", "arguments": {"operation": "cast", "work_id": first}, "confidence": 0.9})
    assert decision["result"]["metadata"]["cinema_db"]["subject"]["work_id"] == first and decision["result"]["metadata"]["cinema_db"]["total"] == 2
    assert not any("v_name" in q["sql"] for s in observer.steps if s.kind == STEP_CINEMA_SQL_CALLS for q in s.data["queries"])
    bad, _, _ = _run(tool, {"tool_name": "cinema_sql", "arguments": {"operation": "cast"}, "confidence": 0.9})
    assert bad["result"]["outcome"]["status"] == "error" and bad["result"]["metadata"]["cinema_db"]["error"] == "invalid_request"


def test_the_query_budget_is_per_turn_across_every_run_of_the_turn(tool) -> None:
    small = CinemaSqlTool(config=CinemaDbConfig(enabled=True, db_path=tool.config.db_path, max_queries_per_turn=3, default_limit=25))
    params = {"operation": "find_work", "title": "Film di prova", "turn_id": "T1"}
    outcomes = [small.run(query="q", params=dict(params))["outcome"]["status"] for _ in range(3)]
    assert outcomes[0] == "ok" and "error" in outcomes[1:]  # two queries per lookup: the third query of the turn does not run
    assert small.run(query="q", params={**params, "turn_id": "T2"})["outcome"]["status"] == "ok"
