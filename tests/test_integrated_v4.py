"""The integrated architecture (cinema_sql on a schema-4 file): which tools are registered and which rules the planner reads for every combination of flags, that no
text contradicts another, the IMDb id hand-over from the two RAGs, the settings applied to the new operation and a scripted turn through the real orchestrator.

Offline and scripted: they prove wiring and prompt text, not which plan the real model writes (that is the live evaluation, which needs authorisation)."""
from __future__ import annotations

import json

import pytest
from cinema_v3_support import build_v3
from test_cinema_sql_app import FakeClient, Other, Steps, policy

import app as app_module
import planner_rules_v4 as V4
from cinema_db.schema import create_database
from orchestrator import LLMOrchestrator
from tool.cinema_db.constants import ML_GENRES
from tool.cinema_db.tool import CinemaSqlTool
from tool.rag.film.retrieval.adapter import film_facts
from tool.rag.film.retrieval.index import Film
from tool.rag.series import retrieval as R
from tool.rag.series.tool import _view

CFG = app_module.CONFIG["orchestrator"]
OLD_RULE_START = "1g) cinema_sql interroga l'archivio locale"


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("integrated")
    return {"v2": create_database(tmp / "v2.sqlite3"), "v3": build_v3(tmp / "v3.sqlite3"), "v4": build_v3(tmp / "v4.sqlite3", movielens=True)}


def planner_prompt(monkeypatch, files, cinema=None, series=False):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    overrides = {"series_rag": {"enabled": series}, "cinema_db": {"enabled": False}}  # FASE 24: on by default, so "off" is explicit here
    if cinema:
        overrides["cinema_db"] = {"enabled": True, "db_path": str(files[cinema])}
    built = app_module.build_app(overrides)
    orchestrator = built["orchestrator"]
    return orchestrator._planning_instructions(orchestrator._allowed_tool_names(), "default"), orchestrator, built["config"]


@pytest.mark.parametrize("series", [False, True])
@pytest.mark.parametrize("cinema", [None, "v2", "v3", "v4"])
def test_every_flag_combination_registers_the_right_tools_and_rules(monkeypatch, files, cinema, series):
    prompt, orchestrator, config = planner_prompt(monkeypatch, files, cinema, series)
    tools = set(orchestrator.tools)
    assert ("series_rag_search" in tools) is series and ("cinema_sql" in tools) is bool(cinema)
    assert ("1h) series_rag_search" in prompt) is series
    if cinema == "v4":
        # MovieLens is inside the database: the old tool is neither registered nor named anywhere the planner reads
        assert "movie_db_search" not in tools and "movie_db_search" not in prompt
        assert V4.CINEMA_SQL_V4_RULE in prompt and OLD_RULE_START not in prompt and "Copertura temporale" not in prompt
        assert "operation movielens" in prompt and '"name":"cinema_sql"' in prompt and "ml_mode" in prompt
    else:
        assert "movie_db_search" not in tools and "movie_db_search" not in prompt and V4.CINEMA_SQL_V4_RULE not in prompt and "Copertura temporale" not in prompt
        assert (OLD_RULE_START in prompt) is bool(cinema)
        assert ("[Archivio con valutazioni" in prompt) is (cinema == "v3")


def test_with_every_flag_off_the_prompt_is_the_one_the_planner_always_had(monkeypatch, files):
    prompt, _, config = planner_prompt(monkeypatch, files)
    assert prompt.startswith(CFG["instructions"]) and "cinema_sql" not in prompt and config["rag"]["film_index"].get("expose_imdb_id") is None


def test_the_rule_names_exactly_the_tool_operations_and_genres(files):
    schema = CinemaSqlTool(config=app_module.load_cinema_db_config({"enabled": True, "db_path": str(files["v4"]), "max_queries_per_turn": 12, "default_limit": 25})).input_schema
    modes = set(schema["properties"]["ml_mode"]["enum"])
    for mode in modes:
        assert mode in V4.CINEMA_SQL_V4_RULE.replace("genre_stats", "genre_stats")
    assert V4.ML_GENRES_TEXT == ", ".join(ML_GENRES)
    assert "movielens" in schema["properties"]["operation"]["enum"]


def test_a_schema_3_or_2_file_never_gets_the_movielens_text(monkeypatch, files):
    for name in ("v2", "v3"):
        prompt, _, _ = planner_prompt(monkeypatch, files, name)
        assert "operation movielens" not in prompt and V4.CINEMA_SQL_V4_FINAL_INSTRUCTIONS not in json.dumps(app_module.build_app({"cinema_db": {"enabled": True, "db_path": str(files[name])}})["config"]["orchestrator"]["tool_final_instructions"])


def test_the_final_rule_for_the_lists_names_no_provider_and_only_the_v4_mode_has_it(monkeypatch, files):
    _, _, config = planner_prompt(monkeypatch, files, "v4")
    text = config["orchestrator"]["tool_final_instructions"]["cinema_sql"]
    assert text.endswith(V4.CINEMA_SQL_V4_FINAL_INSTRUCTIONS) and "MovieLens" not in V4.CINEMA_SQL_V4_FINAL_INSTRUCTIONS and "TMDb" not in V4.CINEMA_SQL_V4_FINAL_INSTRUCTIONS


def test_the_film_rag_gives_its_imdb_id_to_the_planner_only_in_the_integrated_configuration(monkeypatch, files):
    film = Film(point_id="p", film_id="1", title="Alpha", original_title=None, year=2000, genres=[], plot="x", directors=["D"], cast=["A"], countries=["IT"], duration_minutes=100, imdb_id="tt0000101")
    assert "imdb_id" not in film_facts(film, 1) and film_facts(film, 1, with_imdb_id=True)["imdb_id"] == "tt0000101"
    _, _, config = planner_prompt(monkeypatch, files, "v4")
    assert config["rag"]["film_index"]["expose_imdb_id"] is True
    _, _, plain = planner_prompt(monkeypatch, files, "v3")
    assert "expose_imdb_id" not in plain["rag"].get("film_index", {})


def test_the_series_rag_gives_a_reliable_imdb_id_only_when_asked():
    item = R.Item("1", "wp-1", "series", "Serie", 2010, None, "plot")
    item.imdb_id = "tt0000110"
    assert "imdb_id" not in _view(item, 1, plot_chars=50, listing=False) and _view(item, 1, plot_chars=50, listing=False, with_imdb_id=True)["imdb_id"] == "tt0000110"
    class Pt:
        id, score, vector = "1", 0.5, None
        payload = {"record_id": "wp-1", "entity_type": "series", "title": "S", "imdb_id": "tt0000110", "ids_reliable": True}
    assert R.item_from_point(Pt).imdb_id == "tt0000110"
    Pt.payload = {**Pt.payload, "imdb_id": "None"}
    assert R.item_from_point(Pt).imdb_id is None
    Pt.payload = {**Pt.payload, "imdb_id": "tt0000110", "ids_reliable": False}
    assert R.item_from_point(Pt).imdb_id is None  # an id recovered without confirmation is never handed over


def test_the_movielens_lists_obey_the_content_type_setting_and_serve_user_ratings():
    from preferences import behavior

    assert behavior.source_for("cinema_sql", "movielens") == "user ratings" and behavior.source_for("cinema_sql", "awards") == "official information"
    args = {"operation": "movielens", "ml_mode": "top_rated"}
    assert policy(content_type="series").check_step("cinema_sql", args).arguments is None  # films only, as movie_db_search was
    assert policy(content_type="film").check_step("cinema_sql", args).arguments == args


def test_a_turn_on_the_v4_database_answers_a_ranking_with_one_planner_step_and_no_other_tool(monkeypatch, files):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    built = app_module.build_app({"cinema_db": {"enabled": True, "db_path": str(files["v4"])}})
    cinema = next(t for t in built["orchestrator"].tools.values() if t.name == "cinema_sql")
    tmdb = Other("tmdb_search")
    plan = {"tool_name": "cinema_sql", "arguments": {"operation": "movielens", "ml_mode": "most_rated", "genre": "Drama", "min_votes": 1}, "confidence": 0.9}
    client = FakeClient(plan)
    decision = LLMOrchestrator(config=built["config"], tools=[cinema, tmdb], client=client).run(query="i film drama più votati", conversation_history=[], observer=Steps())
    assert decision["tools"] == ["cinema_sql"] and tmdb.runs == 0 and len(client.calls) == 2
    body = decision["result"]["metadata"]["cinema_db"]
    assert body["status"] == "ok" and body["mode"] == "most_rated" and [m["ratings"] for m in body["movies"]] == [900, 60]
    assert all(n["code"] in {"movielens", "movielens_genres"} for n in body["notes"] if n["code"].startswith("movielens"))
    assert client.calls[1]["instructions"].endswith(V4.CINEMA_SQL_V4_FINAL_INSTRUCTIONS)


@pytest.mark.parametrize("cinema", ["v2", "v3", "v4"])
def test_the_seasons_of_a_series_have_one_owner_tvmaze_and_cinema_sql_never_claims_them(monkeypatch, files, cinema):
    """The overlap of rules 1g and 1e ('how many seasons has X' was in both, and 1g claimed precedence over 1e) must not come back: in every prompt that has cinema_sql the
    seasons, episodes, air dates, next episode, cast and network of ONE series belong to tvmaze_search, and 1g says it never overrides 1e."""
    prompt, orchestrator, _ = planner_prompt(monkeypatch, files, cinema, series=True)
    rule_1g = prompt[prompt.index("\n1g)"):].split("\n1h)")[0].split("\nAllowed tools:")[0]
    assert "MAI sulla 1e" in rule_1g and "SEMPRE di tvmaze_search" in rule_1g and "mai cinema_sql" in rule_1g
    assert "quante stagioni" not in rule_1g and "series senza season" not in rule_1g and "regole 1, 1e e 1f" not in prompt
    rule_1e = prompt[prompt.index(" 1e) "): prompt.index(" 1f) ")]
    assert "stagioni (quante sono" in rule_1e and "tvmaze_search come primo tool" in rule_1e
    series_op = orchestrator.tools["cinema_sql"].input_schema["properties"]["operation"]["description"]
    assert "tvmaze_search" in series_op  # the operation itself points the planner to TVmaze for counts and dates


class FilmRag:
    """A stand-in for rag_search that returns what the real adapter returns in the integrated configuration: `metadata.films` with the `imdb_id` of every film."""
    name, description, input_schema = "rag_search", "rag", {"type": "object"}

    def __init__(self, films):
        self.films, self.runs = films, 0

    def run(self, *, query, params=None, conversation_history=None):
        self.runs += 1
        return {"query": query, "chunks": [], "metadata": {"search_mode": "hybrid", "k_finale": len(self.films), "films": self.films}, "trace": []}


def test_the_imdb_id_of_a_rag_film_reaches_the_planner_and_cinema_sql_resolves_it_without_a_title_search(monkeypatch, files):
    """RAG film first, then cinema_sql with the id found in the first result: the second planner prompt contains every id (10 realistic films), and the second step is answered by
    the real tool from the id alone (no name lookup, no ambiguity between the two homonymous works of the miniature database)."""
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    built = app_module.build_app({"cinema_db": {"enabled": True, "db_path": str(files["v4"])}})
    cinema = next(t for t in built["orchestrator"].tools.values() if t.name == "cinema_sql")
    ids = [f"tt{n:07d}" for n in (101, 106, 107, 103, 104, 110, 112, 201, 202, 203)]
    films = [{"n": i, "imdb_id": imdb, "title": f"Film numero {i} con un titolo abbastanza lungo", "original_title": f"Original title {i}", "year": 1990 + i,
              "directors": ["Regista Uno", "Regista Due"], "cast": ["Attore A", "Attrice B", "Attore C", "Attrice D", "Attore E"], "countries": ["Italia", "Francia"], "duration_minutes": 100 + i}
             for i, imdb in enumerate(ids, start=1)]
    rag = FilmRag(films)
    first = {"tool_name": "rag_search", "arguments": {"query": "film sul lutto"}, "confidence": 0.9, "more_steps": True, "parts": [{"part": "film", "tool": "rag_search"}, {"part": "premi", "tool": "cinema_sql"}]}
    second = {"tool_name": "cinema_sql", "arguments": {"operation": "work_card", "imdb_id": "tt0000106"}, "confidence": 0.9, "more_steps": False}
    client = FakeClient(first, second, {"done": True})
    decision = LLMOrchestrator(config=built["config"], tools=[rag, cinema], client=client).run(query="un film sul lutto e chi lo ha diretto", conversation_history=[], observer=Steps())
    assert decision["tools"] == ["rag_search", "cinema_sql"] and rag.runs == 1
    second_prompt = json.dumps(client.calls[1]["input"], ensure_ascii=False)
    assert all(imdb in second_prompt for imdb in ids)  # the planner sees the id of every film of the first result (the summary is cut at 2.500 characters)
    body = decision["calls"][1]["result"]["metadata"]["cinema_db"]
    assert body["status"] == "ok" and body["subject"]["title"] == "Homonym" and body["subject"]["year"] == 1990
    sql = " ".join(q["sql"] for q in decision["calls"][1]["result"]["trace"][0]["data"]["queries"]).casefold()
    assert ("imdb_title" in sql or "v_external_id" in sql) and " match " not in sql and "name_norm" not in sql  # resolved by the identifier


def test_the_ids_line_covers_both_rags_and_is_absent_when_no_result_has_an_id():
    line = LLMOrchestrator._imdb_ids_line
    assert line({"films": [{"n": 1, "imdb_id": "tt0000101"}, {"n": 2, "title": "no id"}, {"n": 3, "imdb_id": "tt0000103"}]}) == "IMDb ids of the results (position=id): 1=tt0000101, 3=tt0000103"
    assert line({"series_rag": {"items": [{"n": 1, "imdb_id": "tt0000110"}, {"n": 2}]}}) == "IMDb ids of the results (position=id): 1=tt0000110"
    assert line({"films": [{"n": 1}], "series_rag": {"items": [{"n": 1}]}, "cinema_db": {"status": "ok"}}) == "" and line({}) == ""


class SeriesRag:
    """Stand-in for series_rag_search in the integrated configuration: items with the `imdb_id` of the series, as the real tool returns them."""
    name, description, input_schema = "series_rag_search", "series", {"type": "object"}

    def __init__(self, items):
        self.items, self.runs = items, 0

    def run(self, *, query, params=None, conversation_history=None):
        self.runs += 1
        return {"query": query, "chunks": [], "metadata": {"series_rag": {"status": "ok", "level": "series", "count": len(self.items), "items": self.items}}, "trace": []}


def test_a_series_found_by_description_goes_to_tvmaze_for_its_seasons_and_never_to_cinema_sql(monkeypatch, files):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    built = app_module.build_app({"cinema_db": {"enabled": True, "db_path": str(files["v4"])}, "series_rag": {"enabled": True}})
    cinema = next(t for t in built["orchestrator"].tools.values() if t.name == "cinema_sql")
    series, tvmaze, tmdb = SeriesRag([{"n": 1, "imdb_id": "tt0000110", "level": "series", "title": "Show", "year": 2010}]), Other("tvmaze_search"), Other("tmdb_search")
    first = {"tool_name": "series_rag_search", "arguments": {"query": "serie su una pandemia"}, "confidence": 0.9, "more_steps": True,
             "parts": [{"part": "serie", "tool": "series_rag_search"}, {"part": "stagioni", "tool": "tvmaze_search"}]}
    second = {"tool_name": "tvmaze_search", "arguments": {"title": "Show", "facets": ["seasons"]}, "confidence": 0.9, "more_steps": False}
    client = FakeClient(first, second, {"done": True})
    decision = LLMOrchestrator(config=built["config"], tools=[series, tvmaze, tmdb, cinema], client=client).run(query="una serie su una pandemia e quante stagioni ha", conversation_history=[], observer=Steps())
    assert decision["tools"] == ["series_rag_search", "tvmaze_search"] and tvmaze.runs == 1 and tmdb.runs == 0
    assert "tt0000110" in json.dumps(client.calls[1]["input"], ensure_ascii=False)  # the series id is in front of the planner of the second step


def test_a_title_the_database_does_not_have_leads_to_exactly_one_external_step(monkeypatch, files):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    built = app_module.build_app({"cinema_db": {"enabled": True, "db_path": str(files["v4"])}})
    cinema = next(t for t in built["orchestrator"].tools.values() if t.name == "cinema_sql")
    tmdb = Other("tmdb_search")
    first = {"tool_name": "cinema_sql", "arguments": {"operation": "work_card", "imdb_id": "tt9999999"}, "confidence": 0.9, "more_steps": False}
    client = FakeClient(first, {"tool_name": "tmdb_search", "arguments": {"requests": []}, "confidence": 0.9, "more_steps": False}, {"done": True})
    decision = LLMOrchestrator(config=built["config"], tools=[cinema, tmdb], client=client).run(query="dettagli di tt9999999", conversation_history=[], observer=Steps())
    assert decision["tools"] == ["cinema_sql", "tmdb_search"] and tmdb.runs == 1
    assert decision["calls"][0]["result"]["metadata"]["cinema_db"]["status"] == "not_found"
