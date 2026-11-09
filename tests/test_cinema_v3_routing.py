"""Routing scenarios of `cinema_sql` on the miniature schema-3 database: for each scenario the tool chosen, the external steps (at most ONE targeted fallback), the
level of reliability the model is given, and the planner prompt (v3 text only with a v3 file, preference «user ratings» for `ratings`). Offline, no model call:
the planner is scripted, so these tests prove what the tool and the orchestrator do with a plan, not which plan the real model writes (that is the live evaluation)."""
from __future__ import annotations

import json

import pytest
from test_cinema_sql_app import Other, _run
from test_cinema_sql_v3 import tool, run  # noqa: F401  (fixture)

import app as app_module
from cinema_db.schema import create_database
from preferences import behavior, build_prompt_parts, resolve_preferences


def _plan(tool_name, **arguments):
    return {"tool_name": tool_name, "arguments": arguments, "confidence": 0.9}


# (scenario, the single planned cinema_sql step, expected follow_up tool or None, expected identity level or None)
SCENARIOS = [
    ("verified film", {"operation": "work_card", "title": "Alpha Film"}, None, "verified"),
    ("uncertain identity", {"operation": "work_card", "title": "Beta Film"}, "tmdb_search", "uncertain"),
    ("rule based identity", {"operation": "work_card", "title": "Gamma Film"}, None, "rule_based"),
    ("by director", {"operation": "filmography", "person": "Ann Director"}, None, None),
    ("main cast with billing order", {"operation": "cast", "title": "Alpha Film", "query": "who stars in Alpha Film"}, None, "verified"),
    ("audience ratings", {"operation": "ratings", "title": "Alpha Film"}, None, "verified"),
    ("audience ratings of an uncertain work", {"operation": "ratings", "title": "Beta Film"}, "omdb_search", "uncertain"),
    ("critics scores asked of the archive", {"operation": "ratings", "title": "Alpha Film", "query": "metascore and rotten tomatoes of Alpha Film"}, "omdb_search", "verified"),
    ("data absent from the database", {"operation": "awards", "title": "Alpha Film"}, "wikipedia_search", "verified"),
    ("title not in the database", {"operation": "ratings", "title": "Nonexistent Film"}, "omdb_search", None),
    ("namesake titles", {"operation": "find_work", "title": "Homonym"}, None, None),
]


@pytest.mark.parametrize("name,arguments,fallback,level", SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_each_scenario_chooses_the_tool_with_at_most_one_targeted_external_step(tool, name, arguments, fallback, level):
    query = arguments.pop("query", "q")
    result = tool.run(query=query, params=dict(arguments))
    body = result["metadata"]["cinema_db"]
    subject = body.get("subject") or {}
    assert subject.get("identity_level") == level
    follow_up = result.get("follow_up")
    assert (follow_up["available"] and fallback in follow_up["summary"]) if fallback else follow_up is None
    if query != "q":  # the orchestrator test always asks "domanda": the follow-up depends on the wording, covered by the direct call above
        return
    # through the orchestrator: the planner closes after the first step, or takes exactly the ONE fallback the result named
    externals = {n: Other(n) for n in ("omdb_search", "tmdb_search", "wikipedia_search", "movie_db_search")}
    plans = [_plan("cinema_sql", **arguments)] + ([_plan(fallback)] if fallback else [])
    decision, client, _ = _run(tool, *plans, others=list(externals.values()))
    ran = {n: e.runs for n, e in externals.items() if e.runs}
    assert ran == ({fallback: 1} if fallback else {})
    assert len(decision["tools"]) == 1 + (1 if fallback else 0)


def test_the_level_the_model_receives_matches_the_stored_level(tool):
    states = {t: run(tool, operation="find_work", title=t)[1]["reliability"]["identity"]["state"] for t in ("Alpha Film", "Gamma Film", "Beta Film")}
    assert states == {"Alpha Film": "verified", "Gamma Film": "partial", "Beta Film": "uncertain"}
    _, rule = run(tool, operation="work_card", title="Gamma Film")
    assert any(n["code"] == "identity_rule_based" for n in rule["notes"]) and "follow_up" not in tool.run(query="q", params={"operation": "work_card", "title": "Gamma Film"})


def test_a_merged_person_and_the_provenance_on_request(tool):
    _, films = run(tool, operation="filmography", person="Cy Merged")
    assert [w["title"] for w in films["works"]] == ["Alpha Film", "Gamma Film"]
    _, prov = run(tool, operation="provenance", title="Dup Film")
    assert prov["status"] == "ok" and tool.run(query="q", params={"operation": "provenance", "title": "Beta Film"}).get("follow_up") is None  # asked for itself: no external step


# ---- the planner text ---------------------------------------------------------------------------------------------------------------
def test_the_planner_text_routes_each_kind_of_request_and_only_with_a_v3_file(tool, tmp_path):
    v3 = app_module.build_app({"cinema_db": {"enabled": True, "db_path": str(tool.db_path)}})["config"]["orchestrator"]["tool_rules"]["cinema_sql"]
    v2_path = create_database(tmp_path / "v2.sqlite3")
    v2 = app_module.build_app({"cinema_db": {"enabled": True, "db_path": str(v2_path)}})["config"]["orchestrator"]["tool_rules"]["cinema_sql"]
    assert v2 == app_module.CINEMA_SQL_ROUTING_RULE and v3.startswith(v2) and v3 != v2  # v2 prompt untouched; v3 only adds
    for fragment in ("PRIMA ratings", "Metascore, Rotten Tomatoes", "omdb_search (1d)", "movie_db_search (2)", "billing_order", "rule_based", "provenance", "UN passo esterno", "sono la prima fonte per un titolo (ratings)", "mai operation sql su v_work_rating", "anche quando l'utente dice «dagli utenti»"):
        assert fragment in v3 and fragment not in v2
    assert "tmdb_search" in v2 and "novità" in v2  # dynamic data (releases, latest films) stays with the online tool in the base rule
    assert "ratings" not in v2 and "identity_level" not in v2


def test_the_user_ratings_preference_reaches_ratings_and_the_other_sources_keep_their_tools():
    assert behavior.source_for("cinema_sql", "ratings") == "user ratings"
    for operation in ("find_work", "cast", "awards", "provenance", None):
        assert behavior.source_for("cinema_sql", operation) == "official information"
    assert behavior.source_for("omdb_search", "anything") == "reviews" and behavior.source_for("movie_db_search") == "user ratings" and behavior.source_for("unknown") is None
    assert set(behavior.SOURCE_TOOL_OPERATIONS["cinema_sql"].values()) <= set(behavior.SOURCE_TOOLS.values())


def test_with_user_ratings_set_the_planner_gets_both_the_preference_and_the_v3_rule(tool):
    prefs = resolve_preferences({"preferred_sources": "user ratings"}).preferences
    parts = build_prompt_parts(prefs)
    from test_cinema_sql_app import FakeClient, Steps
    from orchestrator import LLMOrchestrator

    config = app_module.build_app({"cinema_db": {"enabled": True, "db_path": str(tool.db_path)}})["config"]
    client = FakeClient(_plan("cinema_sql", operation="ratings", title="Alpha Film"))
    LLMOrchestrator(config=config, tools=[tool], client=client).run(query="che voto ha Alpha Film", conversation_history=[], observer=Steps(), prompt_parts=parts)
    planner_prompt = json.dumps(client.calls[0]["input"]) + json.dumps(client.calls[0].get("instructions", ""))
    assert "voti degli utenti" in planner_prompt and "PRIMA ratings" in planner_prompt and "Metascore" in planner_prompt


# ---- activation prerequisites (nothing is activated here) -------------------------------------------------------------------------------
def test_activation_and_rollback_need_only_the_two_variables_and_the_start_checks_the_file(tool, tmp_path):
    import sqlite3
    from cinema_v3_support import build_v3

    assert app_module.CONFIG["cinema_db"]["enabled"] is False and app_module.CONFIG["cinema_db"]["db_path"] == "cinema_db/data/cinema.sqlite3"
    env = {"CINEMA_DB_ENABLED": "1", "CINEMA_DB_PATH": str(tool.db_path)}
    cfg = app_module.build_runtime_config(app_module.cinema_db_overrides(env))["cinema_db"]
    app_module.ensure_cinema_db_ready(cfg)  # a valid v3 file passes the probe
    assert app_module.build_runtime_config(app_module.cinema_db_overrides({}))["cinema_db"]["enabled"] is False  # unsetting the variables is the rollback
    broken = build_v3(tmp_path / "broken.sqlite3")
    conn = sqlite3.connect(broken)
    conn.execute("DROP VIEW v_work_status")
    conn.commit()
    conn.close()
    for bad in (broken, tmp_path / "missing.sqlite3"):
        with pytest.raises(RuntimeError):
            app_module.ensure_cinema_db_ready({**cfg, "db_path": str(bad)})
