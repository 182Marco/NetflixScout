"""`cinema_sql` on a schema-3 database: policy chosen from the file, ratings, identification levels, provenance, merged persons, and the unchanged behaviour on schema 2."""
from __future__ import annotations

import json

import sqlite3

import pytest
from cinema_v3_support import build_v3

import app as app_module
from cinema_db.schema import create_database
from tool.cinema_db.config import CinemaDbConfig
from tool.cinema_db.tool import CinemaSqlTool
from tool.cinema_db.versions import schema_version_of


@pytest.fixture(scope="module")
def tool(tmp_path_factory) -> CinemaSqlTool:
    path = build_v3(tmp_path_factory.mktemp("v3") / "cinema.v3.sqlite3")
    return CinemaSqlTool(config=CinemaDbConfig(enabled=True, db_path=str(path), max_queries_per_turn=40, default_limit=25))


def run(tool, **arguments):
    result = tool.run(query=arguments.pop("query", "q"), params=arguments)
    return result, result["metadata"]["cinema_db"]


def test_the_policy_is_chosen_from_the_file(tool, tmp_path):
    assert tool.schema == 3 and "v_work_rating(" in tool.description and "identity_level" in tool.description
    v2 = create_database(tmp_path / "v2.sqlite3")
    assert schema_version_of(v2) == 2 and CinemaSqlTool(config=CinemaDbConfig(enabled=True, db_path=str(v2), max_queries_per_turn=5, default_limit=25)).schema == 2
    assert schema_version_of(tmp_path / "missing.sqlite3") == 2


def test_schema_2_has_no_ratings_or_provenance_and_says_so(tmp_path):
    v2 = create_database(tmp_path / "v2.sqlite3")
    old = CinemaSqlTool(config=CinemaDbConfig(enabled=True, db_path=str(v2), max_queries_per_turn=5, default_limit=25))
    for op in ("ratings", "provenance"):
        result, body = run(old, operation=op, title="Alpha Film")
        assert body["status"] == "empty" and body["reason"] == "not_in_this_database" and result["follow_up"]["available"]


def test_search_by_title_year_director_and_the_level_of_identification(tool):
    _, body = run(tool, operation="find_work", title="Alpha Film", year=2000, director="Ann Director")
    assert body["status"] == "ok" and body["subject"]["imdb_id"] == "tt0000101" and body["subject"]["identity_level"] == "verified" and body["reliability"]["identity"]["state"] == "verified"
    _, uncertain = run(tool, operation="find_work", title="Beta Film")
    assert uncertain["subject"]["identity_level"] == "uncertain" and uncertain["reliability"]["identity"]["state"] == "uncertain"
    assert [n["code"] for n in uncertain["notes"] if n["code"].startswith("identity")] == ["identity_uncertain"]
    _, rule = run(tool, operation="find_work", title="Gamma Film")
    assert rule["subject"]["identity_level"] == "rule_based" and rule["reliability"]["identity"]["state"] == "partial" and any(n["code"] == "identity_rule_based" for n in rule["notes"])


def test_namesakes_are_alternatives_with_their_levels_and_a_year_settles_it(tool):
    _, body = run(tool, operation="find_work", title="Homonym")
    assert body["status"] == "ambiguous" and {c["year"]: c["identity_level"] for c in body["candidates"]} == {1990: "verified", 1991: "uncertain"} and "subject" not in body
    _, settled = run(tool, operation="find_work", title="Homonym", year=1990)
    assert settled["status"] == "ok" and settled["subject"]["work_id"] == 105


def test_cast_comes_in_billing_order_and_the_merged_person_appears_once(tool):
    _, body = run(tool, operation="cast", title="Alpha Film")
    assert [p["name"] for p in body["cast"]] == ["Bob Actor", "Cy Merged"] and [p.get("billing_order") for p in body["cast"]] == [1, 2]
    assert body["cast"][1]["person_id"] == 204 and body["reliability"]["billing_order"]["state"] == "partial" and any(n["code"] == "cast_order_partial" for n in body["notes"])
    result, _ = run(tool, operation="cast", title="Alpha Film", query="who stars in Alpha Film, the main cast?")
    assert "follow_up" not in result  # the order is recorded: no step to another tool just to learn who leads
    _, films = run(tool, operation="filmography", person_id=204)
    assert [w["title"] for w in films["works"]] == ["Alpha Film", "Gamma Film"]  # the work of the merged entity is not listed twice
    _, crew = run(tool, operation="crew", title="Alpha Film")
    assert crew["crew"] == [{"role": "director", "people": ["Ann Director"]}]


def test_ratings_of_a_title_with_their_scales_and_votes(tool):
    _, body = run(tool, operation="ratings", title="Alpha Film")
    got = {r["source"]: (r["rating"], r["scale_max"], r["votes"]) for r in body["ratings"]}
    assert got == {"imdb-datasets": (7.5, 10, 5000), "movielens-32m-aggregates": (4.0, 5, 900)} and any(n["code"] == "ratings" for n in body["notes"])
    result, empty = run(tool, operation="ratings", title="Show")
    assert empty["status"] == "empty" and empty["reason"] == "no_rating_recorded" and result["follow_up"]["available"]
    result, asked = run(tool, operation="ratings", title="Alpha Film", query="metascore and rotten tomatoes of Alpha Film")
    assert "critics_scores" in "".join(result["follow_up"]["reasons"])  # the critics' scores are not local: ONE step to the external tool


def test_best_rated_titles_need_the_minimum_votes(tool):
    _, body = run(tool, operation="ratings", min_votes=500)
    assert [(r["title"], r["votes"]) for r in body["ranking"]] == [("Dup Film", 1000), ("Alpha Film", 5000)]  # best rating first (8.0 before 7.5)
    assert body["min_votes"] == 500 and any(n["code"] == "ratings_ranking" for n in body["notes"])
    assert any(n["code"] == "ratings_mixed_types" for n in body["notes"])  # no type asked: the answer must say films and series are mixed
    _, films = run(tool, operation="ratings", min_votes=500, type="film")
    assert not any(n["code"] == "ratings_mixed_types" for n in films["notes"])
    _, wide = run(tool, operation="ratings", min_votes=10, year_from=2001, year_to=2010)
    assert [r["title"] for r in wide["ranking"]] == ["Beta Film", "Dup Film", "Gamma Film"]  # 9.0, 8.0, 6.0 (Alpha Film is from 2000)


def test_provenance_of_a_work_with_two_imdb_ids_and_of_a_merged_person(tool):
    _, body = run(tool, operation="provenance", title="Dup Film")
    assert {(i["value"], i["primary"]) for i in body["identifiers"]} == {("tt0000104", True), ("tt0000105", False)}
    assert {(c["field"], c["value"], c["source_ref"]) for c in body["claims"]} >= {("imdb_alt_title_type", "short", "tt0000105"), ("imdb_alt_release_year", "1999", "tt0000105")}
    assert body["identification"]["identity_level"] == "verified"
    _, who = run(tool, operation="provenance", person="Dee Newcomer")
    assert who["status"] == "empty" and who["reason"] == "no_provenance_recorded"  # nothing recorded: said as such, nothing invented
    _, merged = run(tool, operation="provenance", person_id=204)
    assert merged["merged_persons"][0]["merged_person_id"] == 203 and merged["candidates_not_attached"][0]["tier"] == "weak_single_title"
    assert {i["value"] for i in merged["identifiers"]} >= {"nm1", "Q203"}  # the identifiers of the merged person are visible through the canonical one
    _, conflict = run(tool, operation="provenance", title="Beta Film")
    assert any(c["field"] == "wikipedia_it_page_director_conflict" for c in conflict["claims"])


def test_episodes_seasons_and_series(tool):
    _, seasons = run(tool, operation="series", title="Show")
    assert seasons["status"] == "ok" and seasons["seasons"][0]["season_number"] == 1
    _, eps = run(tool, operation="series", title="Show", season=1)
    assert [e["title"] for e in eps["episodes"]] == ["Pilot"]


def test_missing_data_is_said_without_inventing(tool):
    result, body = run(tool, operation="find_work", title="No Such Film")
    assert body["status"] == "not_found" and result["follow_up"]["available"]
    _, person = run(tool, operation="filmography", person="Nobody Here")
    assert person["status"] == "not_found"
    _, none = run(tool, operation="awards", title="Alpha Film")
    assert none["status"] == "empty"


def test_the_new_views_are_readable_by_sql_and_the_base_tables_are_not(tool):
    _, body = run(tool, operation="sql", sql="SELECT identity_level, count(*) AS n FROM v_work_status GROUP BY identity_level ORDER BY identity_level LIMIT 10")
    assert {r["identity_level"]: r["n"] for r in body["rows"]} == {"rule_based": 1, "uncertain": 2, "verified": 6}
    result, _ = run(tool, operation="sql", sql="SELECT value FROM work_rating LIMIT 3")
    assert result["outcome"]["status"] == "error"
    result, _ = run(tool, operation="sql", sql="SELECT * FROM entity_canonical LIMIT 3")
    assert result["outcome"]["status"] == "error"
    _, canon = run(tool, operation="sql", sql="SELECT merged_name, canonical_entity_id FROM v_entity_canonical LIMIT 3")
    assert canon["rows"] == [{"merged_name": "Cy Merged", "canonical_entity_id": 204}]


def test_the_planner_learns_the_v3_capabilities_only_with_a_v3_database(tool, tmp_path):
    on = app_module.build_runtime_config({"cinema_db": {"enabled": True, "db_path": str(tool.db_path)}})
    app = app_module.build_app({"cinema_db": {"enabled": True, "db_path": str(tool.db_path)}})
    rules = app["config"]["orchestrator"]["tool_rules"]["cinema_sql"]
    assert app_module.CINEMA_SQL_V3_RULE_ADDENDUM in rules and "ratings" in rules and "identity_level" in rules
    v2 = create_database(tmp_path / "v2.sqlite3")
    app2 = app_module.build_app({"cinema_db": {"enabled": True, "db_path": str(v2)}})
    assert app2["config"]["orchestrator"]["tool_rules"]["cinema_sql"] == app_module.CINEMA_SQL_ROUTING_RULE
    assert on["cinema_db"]["enabled"] is True and "cinema_sql" not in app_module.build_app({"cinema_db": {"enabled": False}})["orchestrator"].tools  # flag off: not even registered
    assert app_module.CONFIG["cinema_db"]["enabled"] is True and app_module.CONFIG["cinema_db"]["db_path"] == "cinema_db/data/cinema.v4.candidate6.sqlite3"  # FASE 24: the default is the candidate 6


# ---- the turn through the orchestrator (fake planner and answer, the REAL tool on the miniature v3 database) --------------------------
def test_a_rating_question_is_answered_locally_with_no_external_step(tool):
    from test_cinema_sql_app import Other, _run
    plan = {"tool_name": "cinema_sql", "arguments": {"operation": "ratings", "title": "Alpha Film"}, "confidence": 0.9}
    omdb, movie_db = Other("omdb_search"), Other("movie_db_search")
    decision, client, _ = _run(tool, plan, others=[omdb, movie_db])
    assert decision["tools"] == ["cinema_sql"] and omdb.runs == 0 and movie_db.runs == 0 and len(client.calls) == 2  # one plan, one answer
    assert decision["result"]["metadata"]["cinema_db"]["ratings"][0]["votes"] == 5000


def test_an_uncertain_identity_reaches_the_answer_with_its_level_and_a_missing_rating_leads_to_one_external_step(tool):
    from test_cinema_sql_app import Other, _run
    decision, client, _ = _run(tool, {"tool_name": "cinema_sql", "arguments": {"operation": "work_card", "title": "Beta Film"}, "confidence": 0.9}, {"done": True})
    assert decision["tools"] == ["cinema_sql"] and len(client.calls) == 3  # an uncertain identity offers ONE planning step; the planner may close with `done`
    prompt = json.dumps(client.calls[2]["input"])
    assert "identity_uncertain" in prompt and "uncertain" in prompt.replace("identity_uncertain", "")  # the note AND the level of the work reach the model
    first = {"tool_name": "cinema_sql", "arguments": {"operation": "ratings", "title": "Show"}, "confidence": 0.9}
    second = {"tool_name": "omdb_search", "arguments": {}, "confidence": 0.9}
    omdb = Other("omdb_search")
    decision, client, _ = _run(tool, first, second, others=[omdb])
    assert decision["tools"] == ["cinema_sql", "omdb_search"] and omdb.runs == 1 and len(client.calls) == 3  # plan, plan, answer: ONE external step, then the answer


def test_the_answer_rules_forbid_qualitative_judgements_on_ratings():
    from tool.cinema_db.tool import FINAL_INSTRUCTIONS

    assert "non aggiungere giudizi qualitativi" in FINAL_INSTRUCTIONS and "valore, scala, numero di voti e data" in FINAL_INSTRUCTIONS
