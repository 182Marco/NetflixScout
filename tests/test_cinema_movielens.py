"""`cinema_sql` `movielens` (schema 4): the six lists of the old MovieLens tool on a miniature schema-4 database (invented data), the policy chosen from the file,
and the guarantees that did not exist before (series and episodes never in a ranking, excluded films visible with their reason, schema 3 untouched)."""
from __future__ import annotations

import json

import json

import pytest
from cinema_v3_support import build_v3

from movie_db.schema import GENRES, normalize_tag
from tool.cinema_db import ml_titles
from tool.cinema_db.config import CinemaDbConfig
from tool.cinema_db.constants import ML_GENRES
from tool.cinema_db.tool import CinemaSqlTool, planner_schema
from tool.cinema_db.versions import schema_version_of
from tool.movie_db import titles as old_titles


def make(path, movielens=True):
    return CinemaSqlTool(config=CinemaDbConfig(enabled=True, db_path=str(build_v3(path, movielens=movielens)), max_queries_per_turn=40, default_limit=25))


@pytest.fixture(scope="module")
def tool(tmp_path_factory) -> CinemaSqlTool:
    return make(tmp_path_factory.mktemp("v4") / "cinema.v4.sqlite3")


def run(tool, **arguments):
    result = tool.run(query="q", params={"operation": "movielens", **arguments})
    return result, result["metadata"]["cinema_db"]


def test_the_policy_follows_the_file_and_schema_3_is_untouched(tool, tmp_path):
    assert schema_version_of(tool.db_path) == 4 and tool.schema == 3 and "v_ml_movie(" in tool.description + json.dumps(tool.description)
    old = make(tmp_path / "v3.sqlite3", movielens=False)
    assert schema_version_of(old.db_path) == 3
    _, body = run(old, ml_mode="top_rated", min_votes=1)
    assert body["status"] == "empty" and body["reason"] == "not_in_this_database"


def test_vocabularies_equal_the_old_tool():
    assert tuple(GENRES) == ML_GENRES
    for title in ("Matrix, The", "The Matrix", "Kingdom II, The (Riget II)", "Cité, La (La Cité)", "Heat", "L'avventura"):
        assert ml_titles.normalize_title(title) == old_titles.normalize_title(title) and ml_titles.stored_form(title) == old_titles.stored_form(title)
    assert normalize_tag("  Time   Travel ") == " ".join("  Time   Travel ".split()).casefold()


def test_a_ranking_lists_films_only_in_the_old_order(tool):
    _, body = run(tool, ml_mode="top_rated", min_votes=50)
    assert [m["title"] for m in body["movies"]] == ["Alpha Film", "Gamma Film"]  # Dup Film has 40 ratings (< 50); the series (110) and the episode (112) never rank
    _, most = run(tool, ml_mode="most_rated", min_votes=1)
    assert [m["title"] for m in most["movies"]] == ["Alpha Film", "Gamma Film", "Dup Film"]  # most ratings first
    assert most["movies"][0]["avg_rating"] == 4.0 and most["movies"][0]["ratings"] == 900 and most["scale_max"] == 5


def test_genre_and_years_filter_with_movielens_genres(tool):
    _, body = run(tool, ml_mode="top_rated", min_votes=1, genre="drama")
    assert {m["title"] for m in body["movies"]} == {"Alpha Film", "Gamma Film"} and all("Drama" in m["genres"] for m in body["movies"])
    _, years = run(tool, ml_mode="most_rated", min_votes=1, year_from=2001, year_to=2005)
    assert [m["title"] for m in years["movies"]] == ["Gamma Film"]
    result = tool.run(query="q", params={"operation": "movielens", "ml_mode": "top_rated", "genre": "Mystery-Thriller"})
    assert result["metadata"]["cinema_db"]["error"] == "invalid_request"


def test_title_search_has_three_tiers_and_shows_films_outside_the_catalogue(tool):
    _, body = run(tool, ml_mode="by_title", title="alpha")
    assert [m["title"] for m in body["movies"]] == ["Alpha Film"]
    _, article = run(tool, ml_mode="by_title", title="Film, The Gamma")  # typed in the stored form: tier 0 (exact) sorts before a longer match
    assert [m["ml_title"] if "ml_title" in m else m["title"] for m in article["movies"]][0] == "Gamma Film"
    _, outside = run(tool, ml_mode="by_title", title="Gone_Film")  # '_' is literal, not a wildcard
    assert outside["movies"][0]["status"] == "excluded" and outside["movies"][0]["reason"] == "outside_entry_rule:video" and outside["movies"][0]["work_id"] is None
    _, literal = run(tool, ml_mode="by_title", title="100%")
    assert [m["status"] for m in literal["movies"]] == ["excluded"]
    _, wildcard = run(tool, ml_mode="by_title", title="Gone%Film")
    assert wildcard["status"] == "empty"


def test_tag_search_counts_distinct_users_and_normalises_the_tag(tool):
    _, body = run(tool, ml_mode="by_tag", tag="  FUNNY ")
    assert [(m["title"], m["tag_users"]) for m in body["movies"]] == [("Show", 9), ("Dup Film", 7), ("Alpha Film", 5)]  # tags carry no 'ranking' filter, as in the old tool
    _, none = run(tool, ml_mode="by_tag", tag="nonexistent-tag")
    assert none["status"] == "empty"


def test_genre_statistics_average_the_films_not_the_ratings(tool):
    _, body = run(tool, ml_mode="genre_stats", min_votes=50)
    stats = {g["genre"]: g for g in body["genres"]}
    assert stats["Drama"]["films"] == 2 and stats["Drama"]["avg_rating"] == round((4.0 + 3.5) / 2, 3) and stats["Drama"]["ratings"] == 900 + 60  # the series (4.8, 500) is out
    assert any(n["code"] == "movielens_films_only" for n in body["notes"])
    assert [g["genre"] for g in body["genres"]] == ["Comedy", "Drama"]  # ordered by the mean, best first (Drama fell below Comedy once the series left); Sci-Fi has only 40 ratings


def test_tag_search_always_shows_the_kind_and_type_narrows_it(tool):
    _, everything = run(tool, ml_mode="by_tag", tag="funny")
    kinds = {m["title"]: m["kind"] for m in everything["movies"]}
    assert kinds["Show"] in {"series", "miniseries"} and kinds["Alpha Film"] == "film"  # default unchanged: every linked work, with its kind
    assert any(n["code"] == "movielens_any_kind" for n in everything["notes"])
    _, films = run(tool, ml_mode="by_tag", tag="funny", type="film")
    assert [m["title"] for m in films["movies"]] == ["Dup Film", "Alpha Film"] and not any(n["code"] == "movielens_any_kind" for n in films["notes"])
    _, series = run(tool, ml_mode="by_tag", tag="funny", type="series")
    assert [m["title"] for m in series["movies"]] == ["Show"]


def test_the_planner_schema_stays_small_and_every_operation_has_a_fallback():
    props = planner_schema()["properties"]
    assert {"ml_mode", "genre", "tag"} <= set(props) and "movielens" in props["operation"]["enum"]


def test_the_step_of_a_movielens_list_names_its_own_source_and_no_wikipedia_licence(tool):
    from presenters.cinema_view import cinema_calls_view
    from turn import TraceStep

    result = tool.run(query="q", params={"operation": "movielens", "ml_mode": "most_rated", "min_votes": 1})
    step = result["trace"][0]
    for language in ("it", "en", "de"):
        view = cinema_calls_view(TraceStep(kind=step["kind"], title=step["title"], data=step["data"]), language)
        assert "MovieLens" in view.source and "Wikipedia" not in view.source and view.licenses == [] and view.operation_label
        assert any("1-5" in note or "1–5" in note or "1" in note for note in view.notes) and len(view.notes) >= 1
        assert "work_id" not in json.dumps({**view.model_dump(), "queries": []}) and view.queries and all("v_ml_movie" in q.sql for q in view.queries)  # ids appear only inside the executed SQL
