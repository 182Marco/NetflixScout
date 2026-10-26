"""Offline tests: trailing articles, `by_title` tiers and series filtering in MovieLens rankings."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app import build_app, build_runtime_config
from movie_db.config import load_movie_db_config
from movie_db.harness.evaluation.cases import EVAL_OVERRIDES
from movie_db.harness.fixtures.build_fixture_db import FIXTURE_DIR
from movie_db.harness.ingestion.build import build_movie_db
from tool.movie_db.movie_db_tool import SERIES_EXCLUDED_NOTE, WORK_TYPE_UNVERIFIED, MovieDbTool
from tool.movie_db.titles import normalize_title, stored_form, title_key
from tool.movie_db.work_type import filter_series
from tool.tmdb.work_type import TmdbWorkTypeChecker, imdb_tt
from tests.tmdb_support import make_tool

# id, raw title, genres, imdb id
EXTRA_MOVIES = [
    (11, "Kingdom II, The (Riget II) (1997)", "Drama|Horror", "0120000"),
    (12, "Heat Wave (2000)", "Drama", "0120001"),
    (13, "Firefly (2002)", "Sci-Fi", "0303461"),
    (14, "Planet Earth II (2016)", "Documentary", "0120004"),
    (15, "Mystery Film (1990)", "Mystery", ""),
    (16, "Unknown Origin (1991)", "Mystery", "0120006"),
]
# ratings per movie: (movie, count, rating). Series rate highest; Heat Wave is more rated than Heat.
EXTRA_RATINGS = [(11, 3, 3.0), (12, 9, 3.0), (13, 4, 5.0), (14, 4, 4.9), (15, 3, 4.5), (16, 3, 4.4)]


class FakeClient:
    def __init__(self, output: dict) -> None:
        self.output = json.dumps(output)
        self.responses = self

    def create(self, **kwargs):
        return type("Response", (), {"output_text": self.output})()


class FakeChecker:
    def __init__(self, verdicts: dict[str, str]) -> None:
        self.verdicts = verdicts
        self.asked: list[list[str]] = []

    def classify(self, imdb_ids):
        self.asked.append(list(imdb_ids))
        return {i: self.verdicts[i] for i in imdb_ids if i in self.verdicts}


@pytest.fixture(scope="module")
def config(tmp_path_factory):
    source = tmp_path_factory.mktemp("src")
    for name in ("movies.csv", "ratings.csv", "tags.csv", "links.csv"):
        shutil.copy(FIXTURE_DIR / name, source / name)
    with (source / "movies.csv").open("a", encoding="utf-8") as handle:
        for movie_id, title, genres, _ in EXTRA_MOVIES:
            handle.write(f'{movie_id},"{title}",{genres}\n')
    with (source / "links.csv").open("a", encoding="utf-8") as handle:
        for movie_id, _, _, imdb in EXTRA_MOVIES:
            handle.write(f"{movie_id},{imdb},\n")
    with (source / "ratings.csv").open("a", encoding="utf-8") as handle:
        user = 100
        for movie_id, count, rating in EXTRA_RATINGS:
            for _ in range(count):
                user += 1
                handle.write(f"{user},{movie_id},{rating},964982703\n")
    db_path = tmp_path_factory.mktemp("db") / "extra.sqlite3"
    runtime = build_runtime_config({"movie_db": {**EVAL_OVERRIDES["movie_db"], "db_path": str(db_path)}})
    cfg = load_movie_db_config(runtime["movie_db"])
    build_movie_db(source_dir=source, db_path=db_path, ingestion=cfg.ingestion)
    return cfg


def _run(config, plan: dict, checker=None) -> dict:
    tool = MovieDbTool(config=config, client=FakeClient(plan), work_type_checker=checker)
    return tool.run(query="q", params={}, conversation_history=[])


def _titles(result) -> list[str]:
    return [chunk["title"] for chunk in result["chunks"]]


# --- title normalization -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Matrix, The", "The Matrix"),
        ("Kingdom II, The (Riget II)", "The Kingdom II (Riget II)"),
        ("City of Lost Children, The (Cité des enfants perdus, La)",
         "The City of Lost Children (La Cité des enfants perdus)"),
        ("Hotel, L'", "L'Hotel"),
        ("Heat", "Heat"),
        ("Hello, World", "Hello, World"),  # a comma that is not followed by an article
        ("Dark Knight, The Rises", "Dark Knight, The Rises"),
    ],
)
def test_normalize_title(raw, expected) -> None:
    assert normalize_title(raw) == expected


def test_stored_form_and_key() -> None:
    assert stored_form("The Matrix") == "Matrix, The"
    assert stored_form("Heat") is None
    assert stored_form("Theory of Everything") is None  # "The" must be a whole word
    assert title_key("Matrix, The") == title_key("the matrix")


def test_results_show_the_normalized_title_but_the_database_is_untouched(config) -> None:
    result = _run(config, {"operation": "by_title", "title": "Kingdom"})
    assert _titles(result) == ["The Kingdom II (Riget II)"]
    import sqlite3

    with sqlite3.connect(f"file:{config.db_path}?mode=ro", uri=True) as conn:
        stored = conn.execute("SELECT clean_title FROM movies WHERE movie_id = 11").fetchone()[0]
    assert stored == "Kingdom II, The (Riget II)"


# --- by_title priority ---------------------------------------------------------------------


def test_by_title_exact_beats_a_more_popular_substring(config) -> None:
    # "Heat Wave" has more ratings than "Heat" but only contains it.
    result = _run(config, {"operation": "by_title", "title": "heat"})
    assert _titles(result) == ["Heat", "Heat Wave"]


def test_by_title_normalized_match_beats_substring(config) -> None:
    result = _run(config, {"operation": "by_title", "title": "The Kingdom II"})
    assert _titles(result) == ["The Kingdom II (Riget II)"]
    typed_stored = _run(config, {"operation": "by_title", "title": "Kingdom II, The"})
    assert _titles(typed_stored) == ["The Kingdom II (Riget II)"]


@pytest.mark.parametrize("typed", ["The Matrix", "Matrix, The", "matrix", "MATRIX"])
def test_by_title_existing_searches_still_work(config, typed) -> None:
    assert _titles(_run(config, {"operation": "by_title", "title": typed}))[0] == "The Matrix"


def test_by_title_wildcards_stay_literal(config) -> None:
    assert _run(config, {"operation": "by_title", "title": "%"})["chunks"] == []



# --- series in rankings --------------------------------------------------------------------


def test_series_are_dropped_from_rankings_and_the_limit_is_refilled(config) -> None:
    checker = FakeChecker({"0303461": "series", "0120004": "series", "0133093": "movie"})
    result = _run(config, {"operation": "top_rated", "limit": 2}, checker)
    titles = _titles(result)
    assert "Firefly" not in titles and "Planet Earth II" not in titles
    assert len(titles) == 2
    assert result["metadata"]["excluded_series"] >= 1
    assert result["metadata"]["work_type_verified"] is False  # unverified rows remain
    assert result["metadata"]["work_type_note"] == SERIES_EXCLUDED_NOTE


def test_unverifiable_titles_are_kept_in_place_and_marked(config) -> None:
    # No imdb id (Mystery Film) and an id TMDb cannot settle (Unknown Origin) stay, flagged.
    checker = FakeChecker({"0303461": "series", "0120004": "series"})
    result = _run(config, {"operation": "top_rated", "genre": "Mystery", "limit": 5}, checker)
    by_title = {c["title"]: c["work_type"] for c in result["chunks"]}
    assert by_title["Mystery Film"] == "unverified"
    assert by_title["Unknown Origin"] == "unverified"
    assert _titles(result)[:2] == ["Mystery Film", "Unknown Origin"]  # order by rating untouched


def test_all_verified_films_clear_the_unverified_flag(config) -> None:
    checker = FakeChecker(
        {"0303461": "series", "0133093": "movie", "0083658": "movie", "0078748": "movie", "0088763": "movie"}
    )
    result = _run(config, {"operation": "top_rated", "genre": "Sci-Fi", "limit": 2}, checker)
    assert "Firefly" not in _titles(result)
    assert {c["work_type"] for c in result["chunks"]} == {"movie"}
    assert result["metadata"]["work_type_verified"] is True
    assert "work_type_note" not in result["metadata"]


def test_every_ranking_operation_filters_series(config) -> None:
    checker = FakeChecker({"0303461": "series", "0120004": "series"})
    for plan in (
        {"operation": "most_rated", "limit": 20},
        {"operation": "by_genre_year", "genre": "Sci-Fi", "limit": 20},
    ):
        assert "Firefly" not in _titles(_run(config, plan, checker))


def test_without_a_checker_nothing_is_filtered_and_everything_is_unverified(config) -> None:
    result = _run(config, {"operation": "top_rated", "limit": 3})
    assert "Firefly" in _titles(result)
    assert {k: v for k, v in result["metadata"].items() if k != "operation"} == {
        "row_count": 3,
        **WORK_TYPE_UNVERIFIED,
    }


def test_by_title_is_not_filtered_by_work_type(config) -> None:
    checker = FakeChecker({"0303461": "series"})
    result = _run(config, {"operation": "by_title", "title": "Firefly"}, checker)
    assert _titles(result) == ["Firefly"]
    assert checker.asked == []


def test_ids_beyond_the_limit_are_not_looked_up() -> None:
    rows = [{"imdb_id": str(i), "title": f"t{i}"} for i in range(10)]
    checker = FakeChecker({"0": "series", "1": "movie", "2": "movie"})
    kept, dropped = filter_series(rows, limit=2, checker=checker)
    assert [r["title"] for r in kept] == ["t1", "t2"] and dropped == 1
    assert checker.asked == [["0", "1"], ["2"]]


# --- TMDb checker (fake transport) ---------------------------------------------------------


def _find(movie: bool, tv: bool) -> dict:
    return {"movie_results": [{"id": 1}] if movie else [], "tv_results": [{"id": 2}] if tv else []}


def test_imdb_tt_pads_and_rejects() -> None:
    assert imdb_tt("114709") == "tt0114709" and imdb_tt("0114709") == "tt0114709"
    assert imdb_tt("") is None and imdb_tt("abc") is None


def test_tmdb_checker_classifies_with_find_and_leaves_the_rest_out() -> None:
    tool, transport = make_tool(
        {
            "/find/tt0000001": _find(True, False),
            "/find/tt0000002": _find(False, True),
            "/find/tt0000003": _find(False, False),
            "/find/tt0000004": _find(True, True),
        }
    )
    verdicts = TmdbWorkTypeChecker(tool=tool).classify(["1", "2", "3", "4", "5", "x"])
    assert verdicts == {"1": "movie", "2": "series"}  # none/both/404 and a bad id are unverifiable
    assert "/find/tt0000005" in transport.paths and len(transport.calls) == 5  # "x" costs nothing


def test_tmdb_checker_has_its_own_budget_and_stops_when_spent() -> None:
    routes = {f"/find/tt{i:07d}": _find(True, False) for i in range(1, 6)}
    tool, transport = make_tool(routes, max_calls=1)  # the turn budget does not apply
    verdicts = TmdbWorkTypeChecker(tool=tool, max_checks=3).classify(["1", "2", "3", "4", "5"])
    assert list(verdicts) == ["1", "2", "3"] and len(transport.calls) == 3


def test_tmdb_checker_without_a_key_does_nothing(monkeypatch) -> None:
    from tool.tmdb.errors import TmdbConfigError
    from tool.tmdb.tool import TmdbTool

    tool, transport = make_tool({})
    monkeypatch.setattr(TmdbTool, "_credentials", lambda self: (_ for _ in ()).throw(TmdbConfigError("no key")))
    assert TmdbWorkTypeChecker(tool=tool).classify(["1"]) == {} and transport.calls == []


def test_tmdb_checker_end_to_end_with_the_tool(config) -> None:
    tool, _ = make_tool(
        {
            "/find/tt0303461": _find(False, True),
            "/find/tt0120004": _find(False, True),
        }
    )
    movie_tool = MovieDbTool(
        config=config,
        client=FakeClient({"operation": "most_rated", "limit": 20}),
        work_type_checker=TmdbWorkTypeChecker(tool=tool),
    )
    result = movie_tool.run(query="q", params={}, conversation_history=[])
    assert not {"Firefly", "Planet Earth II"} & set(_titles(result))
    assert result["metadata"]["excluded_series"] == 2


def test_build_app_wires_the_checker() -> None:
    movie_tool = build_app()["orchestrator"].tools["movie_db_search"]
    assert isinstance(movie_tool.work_type_checker, TmdbWorkTypeChecker)
