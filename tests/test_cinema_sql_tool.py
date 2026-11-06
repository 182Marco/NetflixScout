"""The `cinema_sql` tool on the miniature database (invented data built by the real build code, deterministic, no real file needed) and its pure parts."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from cinema_build_support import make_inputs, make_phase4

from cinema_db.harness.build.build import Inputs, run_build
from tool.cinema_db import constants, queries
from tool.cinema_db.approved_views import POLICY
from tool.cinema_db.config import SUGGESTED_CONFIG, CinemaDbConfig, load_cinema_db_config
from tool.cinema_db.models import CinemaSqlInput
from tool.cinema_db.names import fts_query, normalize_name
from tool.cinema_db.tool import FALLBACKS, FINAL_INSTRUCTIONS, CinemaSqlTool, planner_schema, views_summary
from turn import TOOL_PARAM_TURN_LANGUAGE


@pytest.fixture(scope="module")
def tool(tmp_path_factory) -> CinemaSqlTool:
    tmp = tmp_path_factory.mktemp("cinema_tool")
    base = make_inputs(tmp, awards_demo=True)
    inputs = Inputs(base.film_snapshot, base.series_snapshot, base.film_catalog, base.series_dir, phase4=make_phase4(tmp / "phase4"))
    out = tmp / "out" / "cinema.sqlite3"
    run_build(out, inputs, log=lambda *_: None)
    return CinemaSqlTool(config=CinemaDbConfig(enabled=True, db_path=str(out), max_queries_per_turn=40, default_limit=25))


def call(tool: CinemaSqlTool, **arguments):
    result = tool.run(query="test request", params=arguments)
    return result, result["metadata"]["cinema_db"]


# ---- operations on the miniature ------------------------------------------------------------------------------------------------
def test_identification_cast_and_filmography(tool):
    _, film = call(tool, operation="find_work", title="Film di prova")
    assert film["subject"]["year"] == 1982 and film["subject"]["directors"] == ["Ann Regista"] and film["subject"]["imdb_id"] == "tt9000001"
    _, alias = call(tool, operation="find_work", title="Test Film")  # the original title is a name of the same work
    assert alias["subject"]["work_id"] == film["subject"]["work_id"]
    _, cast = call(tool, operation="cast", title="Film di prova")
    assert [(p["name"], p["character"]) for p in cast["cast"]] == [("Bob Attore", "Eroe"), ("Cara Attrice", None)] and cast["total"] == 2
    _, filmography = call(tool, operation="filmography", person="Ann Regista")
    assert [(w["title"], w["year"], w["kind"]) for w in filmography["works"]] == [("Prequel di prova", 1980, "short"), ("Film di prova", 1982, "film")]
    both = call(tool, operation="filmography", person="Ann Regista", type="film")[1]  # "film" also covers shorts and TV films, as the field says
    assert [w["title"] for w in both["works"]] == ["Prequel di prova", "Film di prova"] and both["total"] == 2
    series_only = call(tool, operation="filmography", person="Ann Regista", type="series")[1]
    assert (series_only["status"], series_only["total"]) == ("empty", 0)


def test_a_person_known_only_from_phase_four_has_a_birth_year_and_credits(tool):
    _, m = call(tool, operation="find_person", person="Dora Sceneggiatrice")
    assert m["subject"]["birth_year"] == 1950 and m["subject"]["credits_by_role"] == {"writer": 1}
    assert "person" in [n["code"] for n in m["notes"]]


def test_awards_with_category_ceremony_and_nominee(tool):
    _, m = call(tool, operation="awards", title="Film di prova")
    rows = {(r["category"], r["outcome"], name) for r in m["results"] for name in (r["people"] or [None])}
    assert ("Miglior film", "won", None) in rows and ("Miglior regia", "won", "Bob Attore") in rows and ("Miglior regia", "nominated", "Dora Sceneggiatrice") in rows
    assert ("Miglior regia", "won", "Ann Regista") in rows  # the winner named by the P1346 qualifier
    assert m["total"] == 3 and {r["year"] for r in m["results"]} == {1983}
    _, nominated = call(tool, operation="awards", title="Film di prova", outcome="nominated")
    assert nominated["total"] == 1


def test_series_seasons_and_episodes_with_their_gaps(tool):
    _, seasons = call(tool, operation="series", title="Serie di prova")
    assert [(s["season_number"], s["episodes"]) for s in seasons["seasons"]] == [(1, 1), (2, 1)] and seasons["episodes_without_season"] == 1
    _, s1 = call(tool, operation="series", title="Serie di prova", season=1)
    assert s1["episodes"] == [{"episode_number": 1, "title": "Pilota", "original_title": "Pilot", "date": "2016-07-15"}]
    _, missing = call(tool, operation="series", title="Serie di prova", season=9)
    assert (missing["status"], missing["reason"]) == ("empty", "season_or_episodes_not_in_catalogue")


def test_relations_companies_and_franchise(tool):
    _, relations = call(tool, operation="relations", title="Film di prova")
    assert {(r["relation"], r["title"]) for r in relations["relations"]} >= {("is based on", "Romanzo di prova"), ("is based on", "Romanzo senza nome offline"), ("follows", "Prequel di prova")}
    _, companies = call(tool, operation="companies", title="Film di prova")
    assert companies["companies"] == [{"role": "production", "companies": ["Casa Senza Nome", "Casa di Prova"]}]
    _, franchise = call(tool, operation="franchise", title="Film di prova")
    assert franchise["franchises"][0]["franchise"] == "Saga di prova"
    _, company = call(tool, operation="companies", company="Casa di Prova")
    assert [w["title"] for w in company["works"]] == ["Film di prova"]


def test_the_work_card_and_free_sql(tool):
    _, card = call(tool, operation="work_card", title="Film di prova")
    assert card["writers"] == ["Dora Sceneggiatrice"] and card["countries"] == ["Italy"] and {m["currency"] for m in card["money"]} == {"USD", "EUR"}
    assert "money" in [n["code"] for n in card["notes"]]
    _, free = call(tool, operation="sql", sql="SELECT kind, count(*) AS n FROM v_work GROUP BY kind LIMIT 20")
    assert {r["kind"] for r in free["rows"]} >= {"film", "series", "episode"} and free["columns"] == ["kind", "n"]


def test_a_season_of_a_work_that_is_not_a_series_and_unknown_names_are_reported(tool):
    assert call(tool, operation="series", title="Film di prova")[1]["status"] in {"empty", "not_found", "unverified"}
    result, unknown = call(tool, operation="find_person", person="Nessuno Esiste")
    assert unknown["status"] == "not_found" and result["follow_up"]["available"] is True


# ---- models and the planner's view of the tool -----------------------------------------------------------------------------------
@pytest.mark.parametrize("arguments,fragment", [
    ({"operation": "cast"}, "needs title"),
    ({"operation": "filmography"}, "needs person"),
    ({"operation": "find_work", "tmdb_id": 5}, "needs type"),
    ({"operation": "find_work", "title": "x", "imdb_id": "12345"}, "imdb_id"),
    ({"operation": "find_person", "person": "x", "wikidata_id": "Z1"}, "wikidata_id"),
    ({"operation": "awards", "title": "x", "person": "y"}, "exactly one"),
    ({"operation": "awards"}, "exactly one"),
    ({"operation": "companies"}, "needs a work"),
    ({"operation": "filmography", "person": "x", "year_from": 2000, "year_to": 1990}, "year_from"),
    ({"operation": "find_work", "title": "x", "sql": "SELECT 1"}, "only for operation sql"),
    ({"operation": "sql"}, "needs sql"),
])
def test_invalid_requests_are_refused_with_the_field_and_never_the_value(tool, arguments, fragment):
    with pytest.raises(Exception) as caught:
        CinemaSqlInput(query="q", **arguments)
    assert fragment in str(caught.value)
    result = tool.run(query="q", params={**arguments, "title": "SECRET TITLE"} if "title" in arguments else arguments)
    assert result["outcome"]["status"] == "error" and result["metadata"]["cinema_db"]["error"] == "invalid_request"
    assert "SECRET TITLE" not in json.dumps(result)


def test_unknown_fields_are_refused_and_the_turn_language_is_ignored(tool):
    assert tool.run(query="q", params={"operation": "find_work", "title": "x", "database": "other"})["metadata"]["cinema_db"]["error"] == "invalid_request"
    result = tool.run(query="q", params={"operation": "find_work", "title": "Film di prova", TOOL_PARAM_TURN_LANGUAGE: "de"})
    assert result["metadata"]["cinema_db"]["status"] == "ok"


def test_the_planner_schema_is_compact_and_the_description_lists_the_real_views():
    schema = planner_schema()
    text = json.dumps(schema, separators=(",", ":"))
    assert len(text) < 4000 and '"title":"' not in text and '"default":null' not in text and '"anyOf":[{"type":"string"},{"type":"null"}]' not in text
    assert set(schema["properties"]["operation"]["enum"]) == set(__import__("tool.cinema_db.operations", fromlist=["OPERATIONS"]).OPERATIONS)
    summary = views_summary()
    for view in ("v_work(", "v_person(", "v_credit(", "v_award_result(", "v_work_relation(", "v_franchise("):
        assert view in summary
    assert set(FALLBACKS) == set(schema["properties"]["operation"]["enum"])


def test_the_tool_satisfies_the_protocol_and_the_config_has_no_surprises():
    t = CinemaSqlTool(config=load_cinema_db_config(SUGGESTED_CONFIG))
    assert t.name == "cinema_sql" and callable(t.run) and isinstance(t.description, str) and t.input_schema["required"] == ["query", "operation"]
    with pytest.raises(Exception):
        load_cinema_db_config({**SUGGESTED_CONFIG, "extra": 1})
    assert t.db_path.name == "cinema.sqlite3"


def test_the_final_instructions_say_what_the_local_data_cannot_prove():
    for phrase in ("incompleto", "non prova", "ambiguous", "unverified", "not_found", "total", "numbered_episodes"):
        assert phrase in FINAL_INSTRUCTIONS


def test_every_note_a_result_can_carry_exists_and_says_something():
    assert all(isinstance(text, str) and len(text) > 20 for text in constants.NOTES.values())
    assert {"coverage", "awards", "franchise", "relations", "series", "episode_duplicates", "limit", "unverified"} <= set(constants.NOTES)


# ---- names and queries -----------------------------------------------------------------------------------------------------------
def test_names_are_normalised_like_the_build_and_search_text_cannot_inject_fts_syntax():
    assert normalize_name("Il Cavaliere Oscuro – Il ritorno!") == "il cavaliere oscuro il ritorno" and normalize_name("千と千尋の神隠し") == "千と千尋の神隠し"
    assert fts_query('padri OR "x" NEAR(a b) *') == '"padri" "or" "x" "near" "a" "b"*'
    assert fts_query("   ") is None and fts_query("***") is None


def test_queries_never_contain_the_text_the_model_wrote():
    evil = "x'; DROP TABLE work; --"
    for sql, params in (queries.works_by_name(normalize_name(evil), constants.SCREEN_KINDS, 12), queries.persons_by_name(normalize_name(evil), 12),
                        queries.awards_by_name(f"%{evil}%", evil, None, None, None, "asc", 10), queries.companies_by_name(normalize_name(evil), 5)):
        assert "DROP" not in sql and "'" not in sql.replace("'work'", "").replace("'person'", "").replace("'company'", "").replace("'film'", "").replace("'short'", "") \
            .replace("'tv_film'", "").replace("'series'", "").replace("'miniseries'", "") and params
    with pytest.raises(ValueError):
        queries.works_by_column("title; DROP", 1)
    with pytest.raises(ValueError):
        queries.awards_of("year", 1, None, None, None, "asc", 5)


def test_every_query_the_tool_can_build_passes_the_validator():
    from tool.cinema_db.validator import validate

    built = [
        queries.works_by_name("x", constants.SCREEN_KINDS, 12), queries.works_by_title_search('"x"*', constants.FILM_KINDS, 12), queries.works_by_column("work_id", 1),
        queries.work_ids_by_external("tmdb_movie", 1), queries.directors_of([1, 2]), queries.persons_by_name("x", 12), queries.persons_by_title_search('"x"*', 12),
        queries.persons_by_column("wikidata_id", "Q1"), queries.role_counts([1, 2]), queries.companies_by_name("x", 5), queries.franchises_by_name("x", 5),
        queries.filmography(1, "director", "film", 1990, 2000, "desc", 25), queries.filmography_count(1, None, None, None, None), queries.cast_of(1, 25), queries.cast_count(1),
        queries.crew_of(1, None, 25), queries.shared_works(1, 2, "director", "cast", "asc", 50), queries.top_collaborators(1, None, "cast", 10),
        queries.awards_of("person_id", 1, "won", 1990, 2000, "asc", 25), queries.awards_by_name("%x%", "x", None, None, None, "desc", 25), queries.awards_count(None, None, "%x%", None, None, None),
        queries.seasons_of(1, 50), queries.episode_counts([1, 2]), queries.episodes_of(1, 2, 25), queries.companies_of(1, 25), queries.works_of_company(1, 25),
        queries.franchise_of(1), queries.franchise_members(1, 25), queries.relations_of(1, 25), queries.credits_by_roles(1, ["writer"], 20),
        queries.genres_of(1), queries.countries_of(1), queries.money_of(1),
    ]
    for sql, params in built:
        validate(sql, params, POLICY)  # raises if a view, a column or a function is not approved


def test_the_tool_package_has_no_network_llm_or_credential_code():
    root = Path(__file__).resolve().parents[1] / "tool" / "cinema_db"
    forbidden = {"urllib", "http", "socket", "requests", "openai", "cohere", "httpx", "aiohttp", "subprocess", "dotenv"}
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) and node.level == 0 else []
            assert not any(n.split(".")[0] in forbidden for n in names), (path.name, names)
        assert "os.environ" not in path.read_text(encoding="utf-8"), path.name


def test_the_tool_is_meant_for_the_official_information_setting_and_carries_no_ratings_or_reviews(tool):
    from tool.cinema_db.tool import SOURCE_CATEGORY

    root = Path(__file__).resolve().parents[1]
    fields = json.loads((root / "preferences" / "fields.json").read_text(encoding="utf-8"))
    sources = next(f for f in fields["fields"] if f["id"] == "preferred_sources")
    values = {o["value"] for o in sources["options"]}
    assert SOURCE_CATEGORY == "official information" and SOURCE_CATEGORY in values and {"reviews", "user ratings"} <= values
    from preferences import behavior

    assert behavior.SOURCE_TOOLS["cinema_sql"] == SOURCE_CATEGORY  # wired in phase 6, with the conflict tests in tests/test_cinema_sql_app.py
    forbidden = ("rating", "score", "review", "vote", "plot", "overview", "synopsis")
    for arguments in ({"operation": "work_card", "title": "Film di prova"}, {"operation": "cast", "title": "Film di prova"}, {"operation": "awards", "title": "Film di prova"},
                      {"operation": "series", "title": "Serie di prova"}, {"operation": "relations", "title": "Film di prova"}, {"operation": "find_person", "person": "Ann Regista"}):
        text = json.dumps(call(tool, **arguments)[1]).casefold()
        keys = {k for k in __import__("re").findall(r'"([a-z_]+)":', text)}
        assert not [k for k in keys if any(word in k for word in forbidden)], (arguments, keys)


# ---- defects found by the live evaluation (docs/cinema_db/PHASE6_LIVE.md) -------------------------------------------------------------------
def test_an_award_name_narrows_the_awards_of_a_work_or_a_person_instead_of_being_refused(tool):
    """The planner writes {title, award: 'Oscar', outcome: 'won'} for «how many Oscars did X win»: that is one request, not two targets."""
    _, narrowed = call(tool, operation="awards", title="Film di prova", award="regia")
    assert narrowed["status"] == "ok" and {r["category"] for r in narrowed["results"]} == {"Miglior regia"} and narrowed["total"] == 2
    _, wins = call(tool, operation="awards", title="Film di prova", award="premio", outcome="won")
    assert wins["total"] == 2 and {r["outcome"] for r in wins["results"]} == {"won"}
    _, person = call(tool, operation="awards", person="Bob Attore", award="Miglior regia")
    assert person["status"] == "ok" and {r["category"] for r in person["results"]} == {"Miglior regia"}
    both = tool.run(query="q", params={"operation": "awards", "title": "Film di prova", "person": "Bob Attore"})
    assert both["metadata"]["cinema_db"]["error"] == "invalid_request"  # a work AND a person is still two targets


def test_a_refused_request_tells_the_planner_which_rule_it_broke_and_allows_one_correction(tool):
    result = tool.run(query="q", params={"operation": "awards", "title": "Film di prova", "person": "Bob Attore", "title_secret": "x"})
    assert result["outcome"]["status"] == "error" and result["follow_up"]["available"] is True and result["follow_up"]["reasons"] == ["invalid_request"]
    clean = tool.run(query="q", params={"operation": "awards", "title": "SECRET TITLE", "person": "SECRET PERSON"})
    summary = clean["follow_up"]["summary"]
    assert "awards needs exactly one target" in summary and "Correct them once" in summary and "SECRET" not in json.dumps(clean)  # the rule, never the user's words
    assert clean["metadata"]["cinema_db"]["errors"][0]["rule"].startswith("awards needs exactly one target")


def test_crew_without_a_role_lists_every_role_and_says_the_writer_credit_can_name_source_authors(tool):
    _, crew = call(tool, operation="crew", title="Film di prova")
    assert {g["role"] for g in crew["crew"]} >= {"director", "writer"}
    assert "crew" in [n["code"] for n in crew["notes"]] and "source material" in next(n["text"] for n in crew["notes"] if n["code"] == "crew")
    assert "role" in planner_schema()["properties"] and "several roles" in planner_schema()["properties"]["role"]["description"]


def test_the_final_instructions_forbid_quoting_internal_ids_and_calling_unread_roles_missing():
    assert "work_id e person_id sono identificativi interni: non citarli mai" in FINAL_INSTRUCTIONS and "non che mancano" in FINAL_INSTRUCTIONS
