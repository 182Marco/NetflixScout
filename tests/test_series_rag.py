"""Offline tests of the `series_rag_search` tool and its integration: feature flag, registration, prompt text only while the tool is on, the content-type guard,
the presenters (terminal and web from one view), failure paths and a turn through the orchestrator with the REAL tool on an in-memory collection.

They check wiring and prompt *text*; what the real planner chooses is measured by the live evaluation (pipelines/wikipedia_series/EVAL_REPORT.md)."""
from __future__ import annotations

import json

import numpy as np
import pytest
from qdrant_client import QdrantClient, models
from stream_support import reply

import app as app_module
from orchestrator import LLMOrchestrator
from preferences import SettingsPolicy, behavior, resolve_preferences
from presenters.series_view import LABELS, series_view
from presenters.terminal.series import render_series_rag
from presenters.web.series import serialize_series_rag_step
from pipelines.wikipedia_series.index import point_id
from tool.rag.series import retrieval as R
from tool.rag.series.config import SeriesRagConfig
from tool.rag.series.tool import SeriesRagTool
from turn import STEP_SERIES_RAG, NullObserver, TraceStep

CONFIG = app_module.CONFIG
RULE = app_module.SERIES_RAG_ROUTING_RULE
DIM = 8


def _vec(i: int) -> list[float]:
    v = np.zeros(DIM, dtype=np.float32)
    v[i % DIM] = 1.0
    return v.tolist()


def _mk(rid, et, title, i, **kw):
    p = {"record_id": rid, "entity_type": et, "title": title, "title_norm": R.norm(title), "title_base_norm": R.base_title_norm(title),
         "original_title_norm": R.norm(kw.pop("original", "")), "default_search_eligible": kw.pop("eligible", True),
         "plot_text": kw.pop("plot", "trama di " + title), "year": kw.pop("year", 2000), "wikipedia_url": "https://it.wikipedia.org/wiki/" + title.replace(" ", "_"), **kw}
    return models.PointStruct(id=point_id(rid), vector=_vec(i), payload=p)


@pytest.fixture()
def index():
    c = QdrantClient(":memory:")
    c.create_collection("t", vectors_config=models.VectorParams(size=DIM, distance=models.Distance.COSINE))
    c.upsert("t", points=[
        _mk("s1", "series", "Alfa", 0, subtype="tv_series"),
        _mk("s2", "series", "Beta", 0, subtype="anime", eligible=False),
        _mk("s3", "series", "Gamma", 1),
        _mk("e1", "episode", "Pilota", 0, series_id="s1", series_title="Alfa", season_number=1, episode_number=1),
        _mk("e2", "episode", "Secondo", 0, series_id="s1", series_title="Alfa", season_number=1, episode_number=2),
    ])
    return R.SeriesIndex(client=c, collection="t")


def cfg(**kw) -> SeriesRagConfig:
    return SeriesRagConfig.model_validate({**CONFIG["series_rag"], "enabled": True, **kw})


def make_tool(index, signals=None, *, reorder=None, parse_error=False, embed_error=False):
    sg = signals or R.SeriesSignals(positive_it="x", positive_en="x")

    def factories(config, usage):
        def embed(texts):
            if embed_error:
                raise ConnectionError("down")
            usage.record("embedding", type("U", (), {"prompt_tokens": 7, "total_tokens": 7})())
            return np.stack([np.asarray(_vec(0), dtype=np.float32) for _ in texts])

        def parse(question):
            if parse_error:
                raise RuntimeError("bad json")
            usage.record("parser", type("U", (), {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120})())
            return sg
        return embed, parse, reorder
    return SeriesRagTool(config=cfg(), index=index, factories=factories)


# ---- config, flag, registration -----------------------------------------------------------------------------------------------------
OFF_CINEMA = {"cinema_db": {"enabled": False}}  # FASE 24: cinema_sql is on by default; these tests compare the series tool alone


def test_the_flag_is_on_by_default_and_the_config_has_exactly_the_documented_keys() -> None:
    assert CONFIG["series_rag"]["enabled"] is True and CONFIG["series_rag"]["collection"] == "wikipedia_series_it_v1"
    assert set(CONFIG["series_rag"]) == set(SeriesRagConfig.model_fields)
    assert "series_rag_search" in CONFIG["orchestrator"]["allowed_tools"] and "series_rag_search" in CONFIG["orchestrator"]["tool_final_instructions"]
    with pytest.raises(Exception):
        SeriesRagConfig.model_validate({**CONFIG["series_rag"], "extra": 1})


def test_off_the_tool_is_not_registered_and_on_it_is(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    off = app_module.build_app({**OFF_CINEMA, "series_rag": {"enabled": False}})["orchestrator"]
    on = app_module.build_app({**OFF_CINEMA, "series_rag": {"enabled": True}})["orchestrator"]
    assert "series_rag_search" not in off.tools and "series_rag_search" in on.tools
    assert [t for t in on.tools if t != "series_rag_search"] == list(off.tools)


def test_the_environment_variable_switches_the_flag_and_follows_the_qdrant_url() -> None:
    """FASE 24: ON by default. Unset leaves it, an explicit false switches it off, the Qdrant URL is followed also with the default."""
    assert app_module.series_rag_overrides({}) == {} and app_module.series_rag_overrides({"SERIES_RAG_ENABLED": "0"}) == {"series_rag": {"enabled": False}}
    assert app_module.series_rag_overrides({"SERIES_RAG_ENABLED": " on "}) == {"series_rag": {"enabled": True}}
    assert app_module.series_rag_overrides({"SERIES_RAG_ENABLED": "1", "VECTORSTORE_QDRANT_URL": "http://h:1"}) == {"series_rag": {"enabled": True, "url": "http://h:1"}}
    assert app_module.series_rag_overrides({"VECTORSTORE_QDRANT_URL": "http://h:1"}) == {"series_rag": {"url": "http://h:1"}}
    assert app_module.series_rag_overrides({"SERIES_RAG_ENABLED": "off", "VECTORSTORE_QDRANT_URL": "http://h:1"}) == {"series_rag": {"enabled": False}}


def test_a_flag_on_start_stops_with_the_way_back_when_qdrant_or_the_collection_is_missing() -> None:
    app_module.ensure_series_rag_ready({**CONFIG["series_rag"], "enabled": False, "url": "http://127.0.0.1:1"})   # off: nothing to check
    with pytest.raises(RuntimeError, match="SERIES_RAG_ENABLED"):
        app_module.ensure_series_rag_ready({**CONFIG["series_rag"], "enabled": True, "url": "http://127.0.0.1:1"})


def _prompt(orchestrator) -> str:
    return orchestrator._planning_instructions(orchestrator._allowed_tool_names(), "default")


def test_with_the_flag_off_the_planner_prompt_is_exactly_what_it_was_without_the_tool(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    off_config = {**OFF_CINEMA, "series_rag": {"enabled": False}}
    off = app_module.build_app(off_config)["orchestrator"]
    without_rules = app_module.build_app({**off_config, "orchestrator": {"tool_rules": {}}})["orchestrator"]
    assert _prompt(off) == _prompt(without_rules)
    assert "series_rag_search" not in _prompt(off) and "1h)" not in _prompt(off)
    on = _prompt(app_module.build_app({**OFF_CINEMA, "series_rag": {"enabled": True}})["orchestrator"])
    assert "\n" + RULE in on and on.index(RULE) < on.index("Allowed tools:") and '"name":"series_rag_search"' in on


def test_the_routing_rule_splits_the_work_with_tvmaze_and_tmdb_and_never_asks_twice() -> None:
    for covered in ("serie come X", "puntata", "trama di una stagione", "film per la televisione", "anime", "similar e recommendations"):
        assert covered in RULE
    for elsewhere in ("quante stagioni", "prossimo episodio", "(regola 1e", "1e", "streaming", "trailer", "voti", "novità", "(3)", "(1c)", "(1f)"):
        assert elsewhere in RULE
    assert "UN solo passo" in RULE and "mai un secondo tentativo con series_rag_search" in RULE and "non prova che la serie non esista" in RULE
    assert "ha la precedenza sulle regole 1 e 3" in RULE
    assert "ELENCARE gli episodi" in RULE and "sempre della 1e" in RULE         # lists of episodes belong to TVmaze: its numbering is complete


# ---- user settings ------------------------------------------------------------------------------------------------------------------------
def test_it_serves_official_information_and_runs_for_series_only() -> None:
    assert behavior.SOURCE_TOOLS["series_rag_search"] == "official information"
    series, film, both = (SettingsPolicy(resolve_preferences({"content_type": c}).preferences) for c in ("series", "film", "both"))
    assert series.check_step("series_rag_search", {"query": "x"}).arguments == {"query": "x"}
    assert both.check_step("series_rag_search", {"query": "x"}).arguments == {"query": "x"}
    verdict = film.check_step("series_rag_search", {"query": "x"})
    assert verdict.arguments is None and verdict.setting == "content_type"
    assert series.check_step("rag_search", {"query": "x"}).arguments is None    # the film index stays forbidden under «series»


def test_a_preferred_source_never_adds_a_step_for_this_tool() -> None:
    from preferences import behavior
    for source in ("reviews", "interviews", "official information", "user ratings"):
        assert "series_rag_search" not in behavior.SOURCES_PLANNER[source]  # the SOURCES text; the settings intro and the content block name the tool on purpose


# ---- the tool -------------------------------------------------------------------------------------------------------------------------
def test_a_search_returns_results_without_ids_or_urls_in_the_prompt_part_and_with_them_in_the_trace(index) -> None:
    result = make_tool(index).run(query="una serie", params={"query": "una serie", "turn_id": "t1", "turn_language": "it"})
    assert result["outcome"]["status"] == "ok" and result["chunks"] == []
    meta = result["metadata"]["series_rag"]
    assert meta["level"] == "series" and meta["count"] == 2 and [i["title"] for i in meta["items"]] == ["Alfa", "Gamma"]
    text = json.dumps(meta)
    assert "wikipedia.org" not in text and "record_id" not in text and "s1" not in [i.get("id") for i in meta["items"]]
    step = result["trace"][0]
    assert step["kind"] == STEP_SERIES_RAG and step["data"]["items"][0]["url"].startswith("https://it.wikipedia.org/") and "calls" not in step["data"]
    assert result["usage"]["tokens"]["parser"]["total"] == 120 and result["usage"]["tokens"]["embedding"]["input"] == 7
    assert step["data"]["timings_ms"]["total"] >= 0


def test_k_final_signals_and_config_decide_how_many(index) -> None:
    tool = make_tool(index, R.SeriesSignals(positive_it="x", positive_en="x", requested_count=1))
    assert tool.run(query="x")["metadata"]["series_rag"]["count"] == 1
    assert make_tool(index).run(query="x", params={"query": "x", "k_final": 1})["metadata"]["series_rag"]["count"] == 1
    assert make_tool(index).run(query="x", params={"k_final": 99})["outcome"]["reason"] == "invalid_request"


def test_a_named_series_that_the_catalogue_does_not_have_is_empty_with_one_follow_up(index) -> None:
    sg = R.SeriesSignals(level="episode", positive_it="x", positive_en="x", series_title="Inesistente")
    result = make_tool(index, sg).run(query="episodi di Inesistente")
    assert result["outcome"] == {"status": "empty", "reason": "series_not_in_index"}
    follow = result["follow_up"]
    assert follow["available"] and "tmdb_search" in follow["summary"] and "do not search this tool again" in follow["summary"]
    assert result["metadata"]["series_rag"]["notes"]["series_not_in_index"] == "Inesistente"


def test_a_mixed_manga_anime_page_is_found_by_exact_title_and_flagged(index) -> None:
    sg = R.SeriesSignals(positive_it="x", positive_en="x", series_title="Beta")
    result = make_tool(index, sg).run(query="Beta")
    item = result["metadata"]["series_rag"]["items"][0]
    assert item["title"] == "Beta" and item["mixed_manga_and_anime_page"] is True
    assert make_tool(index).run(query="x")["metadata"]["series_rag"]["items"] and all(not i.get("mixed_manga_and_anime_page") for i in make_tool(index).run(query="x")["metadata"]["series_rag"]["items"])


def test_listing_children_keeps_titles_and_numbers_only(index) -> None:
    sg = R.SeriesSignals(level="episode", positive_it="x", positive_en="x", series_title="Alfa", season_number=1, list_children=True)
    meta = make_tool(index, sg).run(query="episodi della stagione 1")["metadata"]["series_rag"]
    assert meta["listing"] is True and [(i["season"], i["episode"]) for i in meta["items"]] == [(1, 1), (1, 2)] and all("plot" not in i for i in meta["items"])


def test_a_parser_failure_still_searches_and_says_so(index) -> None:
    result = make_tool(index, parse_error=True).run(query="una serie")
    assert result["outcome"]["status"] == "ok" and result["metadata"]["series_rag"]["notes"]["parser_failed"] == "RuntimeError"


def test_reorder_is_applied_and_its_failure_keeps_the_dense_order(index) -> None:
    ok = make_tool(index, reorder=lambda request, sg, cands: list(reversed(range(len(cands)))))
    result = ok.run(query="x")
    assert [i["title"] for i in result["metadata"]["series_rag"]["items"]] == ["Gamma", "Alfa"] and result["trace"][0]["data"]["engine"] == "llm_reorder"

    def boom(*_a):
        raise RuntimeError("x")
    result = make_tool(index, reorder=boom).run(query="x")
    assert result["metadata"]["series_rag"]["notes"]["reorder_failed"] is True and result["metadata"]["series_rag"]["items"][0]["title"] == "Alfa"


def test_an_unreachable_backend_is_a_tool_error_with_one_follow_up_and_no_secret(index) -> None:
    result = make_tool(index, embed_error=True).run(query="x")
    assert result["outcome"] == {"status": "error", "reason": "series_rag_unavailable"} and result["follow_up"]["available"]
    assert "down" not in json.dumps(result)           # only the exception class, never its message


def test_the_planner_schema_is_small_and_has_two_fields() -> None:
    from tool.rag.series.tool import planner_schema
    schema = planner_schema()
    assert set(schema["properties"]) == {"query", "k_final"} and len(json.dumps(schema)) < 1200


def test_the_collection_is_never_written(index) -> None:
    import ast
    import pathlib
    src = "".join(p.read_text() for p in pathlib.Path("tool/rag/series").glob("*.py"))
    assert not {"upsert", "delete_collection", "create_collection", "set_payload", "delete_points"} & {n.attr for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Attribute)}


# ---- presenters ---------------------------------------------------------------------------------------------------------------------------
def _step(index, **kw) -> TraceStep:
    result = make_tool(index, **kw).run(query="x")
    s = result["trace"][0]
    return TraceStep(kind=s["kind"], title=s["title"], data=s["data"])


def test_terminal_and_web_show_the_same_view(index, capsys) -> None:
    step = _step(index)
    web = serialize_series_rag_step(step, "it")
    assert web["kind"] == STEP_SERIES_RAG and [r["label"] for r in web["results"]] == ["Alfa (2000)", "Gamma (2000)"]
    assert web["results"][0]["url"] == "https://it.wikipedia.org/wiki/Alfa" and web["license_url"].startswith("https://creativecommons.org/") and "calls" not in web
    render_series_rag(step, "it")
    out = capsys.readouterr().out
    assert "SERIE TV" in out and "Alfa (2000)" in out and "https://it.wikipedia.org/wiki/Alfa" in out and "CC BY-SA 4.0" in out


def test_only_public_wikipedia_links_and_clean_text_reach_the_interface() -> None:
    data = {"status": "ok", "level": "series", "engine": "dense", "items": [
        {"n": 1, "label": "Bad\x1b[31m title", "level": "series", "url": "https://evil.example/x"},
        {"n": 2, "label": "Ok", "level": "series", "url": "http://it.wikipedia.org/wiki/Ok"},
        {"n": 3, "label": "Good", "level": "series", "url": "https://it.wikipedia.org/wiki/Good"}], "notes": {}}
    view = series_view(TraceStep(kind=STEP_SERIES_RAG, title="t", data=data), "en")
    assert [r.url for r in view.results] == [None, None, "https://it.wikipedia.org/wiki/Good"] and "\x1b" not in view.results[0].label


def test_labels_exist_in_italian_english_and_german_and_unknown_languages_read_english(index) -> None:
    assert set(LABELS) == {"it", "en", "de"} and all(set(LABELS["it"]) == set(LABELS[k]) for k in LABELS)
    assert series_view(_step(index), "fr").title == LABELS["en"]["title"] and series_view(_step(index), "de").title == "SERIEN"


# ---- a turn through the orchestrator with the real tool ---------------------------------------------------------------------------------------
class FakeClient:
    def __init__(self, *plans: dict) -> None:
        self.outputs = [json.dumps(p) for p in plans] + ["Risposta finale."]
        self.calls: list[dict] = []
        self.responses = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return reply(self.outputs.pop(0), kwargs)


class Other:
    def __init__(self, name: str) -> None:
        self.name, self.description, self.input_schema, self.runs = name, name, {"type": "object"}, 0

    def run(self, *, query, params=None, conversation_history=None):
        self.runs += 1
        return {"query": query, "chunks": [], "metadata": {self.name: {"ok": True}}, "trace": []}


class Steps(NullObserver):
    def __init__(self) -> None:
        self.steps: list[TraceStep] = []

    def step(self, step: TraceStep) -> None:
        self.steps.append(step)


def test_a_turn_uses_one_planner_step_and_the_final_rule_reaches_only_its_own_turns(index) -> None:
    tool, tvmaze = make_tool(index), Other("tvmaze_search")
    client, observer = FakeClient({"tool_name": "series_rag_search", "arguments": {"query": "una serie"}, "confidence": 0.9}), Steps()
    decision = LLMOrchestrator(config=app_module.build_runtime_config(), tools=[tool, tvmaze], client=client).run(query="una serie", conversation_history=[], observer=observer)
    assert decision["tools"] == ["series_rag_search"] and tvmaze.runs == 0 and len(client.calls) == 2
    assert client.calls[1]["instructions"].endswith(CONFIG["orchestrator"]["tool_final_instructions"]["series_rag_search"])
    assert [s.kind for s in observer.steps if s.kind == STEP_SERIES_RAG] == [STEP_SERIES_RAG]
    other = FakeClient({"tool_name": "tvmaze_search", "arguments": {}, "confidence": 0.9})
    LLMOrchestrator(config=app_module.build_runtime_config(), tools=[Other("tvmaze_search")], client=other).run(query="x", conversation_history=[])
    assert CONFIG["orchestrator"]["tool_final_instructions"]["series_rag_search"] not in other.calls[1]["instructions"]


def test_a_missing_series_leads_to_exactly_one_other_step_and_this_tool_is_not_asked_again(index) -> None:
    sg = R.SeriesSignals(level="episode", positive_it="x", positive_en="x", series_title="Inesistente")
    tvmaze = Other("tvmaze_search")
    client = FakeClient({"tool_name": "series_rag_search", "arguments": {"query": "episodi di Inesistente"}, "confidence": 0.9},
                        {"tool_name": "tvmaze_search", "arguments": {}, "confidence": 0.9})
    decision = LLMOrchestrator(config=app_module.build_runtime_config(), tools=[make_tool(index, sg), tvmaze], client=client).run(query="episodi di Inesistente", conversation_history=[])
    assert decision["tools"] == ["series_rag_search", "tvmaze_search"] and tvmaze.runs == 1 and len(client.calls) == 3
    assert "tmdb_search" in client.calls[1]["input"][-1]["content"]      # the planner is told the gap is not a proof and where to look once


def test_the_documented_series_step_is_what_the_serializer_produces() -> None:
    import re
    from pathlib import Path
    doc = Path("web_api/contracts/chat_stream.md").read_text(encoding="utf-8")
    documented = {k: json.loads(b) for k, b in re.findall(r"```json step=(\w+)\n(.*?)\n```", doc, re.S)}["series_index"]
    data = {"status": "ok", "reason": None, "level": "episode", "engine": "llm_reorder", "items": [
        {"n": 1, "level": "episode", "title": "Pilota", "label": "Alfa S1E1 – Pilota", "year": None, "url": "https://it.wikipedia.org/wiki/Pilota", "score": 0.4321}],
        "notes": {"series_resolved": [{"record_id": "wp-1", "title": "Alfa", "year": 2000}]}, "signals": {}, "timings_ms": {"total": 2400},
            "phases": {"wide": {"requested": 50, "n": 2, "items": [{"n": 1, "label": "Beta S1E2 – Altro", "year": None, "similarity": 0.51}, {"n": 2, "label": "Alfa S1E1 – Pilota", "year": None, "similarity": 0.43}]}, "rerank": {"engine": "llm", "requested": 40, "n": 2, "items": [{"n": 1, "label": "Alfa S1E1 – Pilota", "year": None, "rank_before": 2}, {"n": 2, "label": "Beta S1E2 – Altro", "year": None, "rank_before": 1}]}, "selection": {"requested": 1, "n": 1}}}
    assert serialize_series_rag_step(TraceStep(kind=STEP_SERIES_RAG, title="t", data=data), "it") == documented
    assert "calls" not in documented and "record_id" not in json.dumps(documented)


# ---- the live routing cases (offline checks of their argument validation) -----------------------------------------------------------------
def test_series_routing_cases_are_well_formed_and_the_default_cases_are_untouched() -> None:
    from movie_db.harness.evaluation.routing_cases import ROUTING_CASES, SERIES, SERIES_ROUTING_CASES
    from movie_db.harness.evaluation.run_routing_eval import check_series
    assert len(ROUTING_CASES) == 69 and not any(c.expected_tool == SERIES for c in ROUTING_CASES)
    cases = [c for c in SERIES_ROUTING_CASES if c.expected_tool == SERIES]
    assert len(SERIES_ROUTING_CASES) == 24 and len(cases) == 11 and all(c.expected_series for c in cases)
    exp = cases[9].expected_series      # "Dammi 3 miniserie…": the number goes in k_final
    assert check_series(exp, {"query": "Dammi 3 miniserie storiche", "k_final": 3}, "Dammi 3 miniserie storiche") is None
    assert "k_final" in check_series(exp, {"query": "Dammi 3 miniserie storiche"}, "Dammi 3 miniserie storiche")
    assert "query lacks" in check_series(cases[0].expected_series, {"query": "serie"}, "serie")
    assert check_series(cases[0].expected_series, "x", "x") == "arguments is not an object"


# ---- K-wide cap and the three stages --------------------------------------------------------------------------------------------------
def test_the_k_wide_is_capped_at_50_for_both_rags() -> None:
    import pytest
    from tool.rag.film.retrieval.adapter import settings_from
    from tool.rag.series.config import load_series_rag_config
    assert CONFIG["series_rag"]["pool"] <= 50 and CONFIG["rag"]["film_index"]["pool"] <= 50
    assert settings_from({"film_index": {"pool": 300, "rerank": {"pool": 40}}}).pool == 50
    with pytest.raises(Exception):
        load_series_rag_config({**CONFIG["series_rag"], "pool": 300})
    with pytest.raises(Exception):
        load_series_rag_config({**CONFIG["series_rag"], "pool": 20, "rerank_pool": 40})


def test_the_rerankers_use_sol_not_luna() -> None:
    assert CONFIG["series_rag"]["rerank_model"] == "gpt-5.6-sol" and CONFIG["rag"]["film_index"]["rerank"]["model"] == "gpt-5.6-sol"


def test_the_series_view_always_has_the_three_stages() -> None:
    from presenters.series_view import series_view
    data = {"status": "ok", "level": "series", "engine": "dense", "items": [{"n": 1, "title": "A", "label": "A", "level": "series", "year": 2000}], "notes": {},
            "timings_ms": {"total": 5}}                                   # no `phases`: exact-title lookups and old steps still show three stages
    view = series_view(TraceStep(kind=STEP_SERIES_RAG, title="t", data=data), "it")
    assert [p.key for p in view.phases] == ["wide", "rerank", "selection"] and view.phases[2].total == 1
