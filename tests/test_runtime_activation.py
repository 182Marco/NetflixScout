"""FASE 24: the integrated runtime is the DEFAULT. `cinema_sql` (candidate 6, MovieLens inside) and `series_rag_search` are on without any variable; `CINEMA_DB_ENABLED=0` and
`SERIES_RAG_ENABLED=0` switch each off on its own (an explicit variable beats the default); `movie_db_search` is never registered in the integrated runtime (its code stays);
`rag_search` and `series_rag_search` are two separate tools. Offline: no model, no network."""
from __future__ import annotations

from pathlib import Path

import pytest

import app as app_module
from cinema_db.harness import candidate

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / candidate.EXPECTED["path"]
EXTERNAL = {"tmdb_search", "youtube_search", "wikipedia_search", "omdb_search", "tvmaze_search", "wikidata_search"}


def runtime(env: dict[str, str]) -> dict:
    """The tools and config of the app exactly as the entry points build them from an environment (`build_ready_app` minus the startup probes)."""
    overrides = app_module._deep_merge(app_module.cinema_db_overrides(env), app_module.series_rag_overrides(env))
    return app_module.build_app(overrides)


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")


def test_without_any_variable_both_systems_are_on_and_the_old_tool_is_not_registered() -> None:
    built = runtime({})
    tools = set(built["orchestrator"].tools)
    assert tools == {"rag_search", "series_rag_search", "cinema_sql", *EXTERNAL}
    assert "movie_db_search" not in tools and "movie_db_search" not in built["orchestrator"]._allowed_tool_names()
    assert built["orchestrator"].tools["cinema_sql"].movielens is True


def test_the_two_rags_are_two_separate_tools_with_their_own_configuration() -> None:
    built = runtime({})
    film, series = built["orchestrator"].tools["rag_search"], built["orchestrator"].tools["series_rag_search"]
    assert film is not series and film.name != series.name
    assert built["config"]["series_rag"]["collection"] == "wikipedia_series_it_v1" and type(film) is not type(series)
    assert "wikipedia_series_it_v1" not in repr(built["config"]["rag"])  # the film side never names the series collection
    assert "film_index" in built["config"]["rag"] and "series_rag" in built["config"]


def test_each_system_switches_off_on_its_own() -> None:
    no_cinema = set(runtime({"CINEMA_DB_ENABLED": "0"})["orchestrator"].tools)
    assert "cinema_sql" not in no_cinema and "series_rag_search" in no_cinema and "movie_db_search" not in no_cinema  # no legacy tool is registered any more
    no_series = runtime({"SERIES_RAG_ENABLED": "0"})
    assert "series_rag_search" not in no_series["orchestrator"].tools and "cinema_sql" in no_series["orchestrator"].tools
    assert "movie_db_search" not in no_series["orchestrator"].tools  # the integrated database still replaces it
    assert "1h) series_rag_search" not in no_series["orchestrator"]._planning_instructions(no_series["orchestrator"]._allowed_tool_names(), "default")


def test_both_off_together_leave_only_the_external_tools_and_the_film_rag() -> None:
    built = runtime({"CINEMA_DB_ENABLED": "0", "SERIES_RAG_ENABLED": "0"})
    assert set(built["orchestrator"].tools) == {"rag_search", *EXTERNAL}
    prompt = built["orchestrator"]._planning_instructions(built["orchestrator"]._allowed_tool_names(), "default")
    assert "cinema_sql" not in prompt and "series_rag_search" not in prompt and "movie_db_search" not in prompt


@pytest.mark.parametrize("value", ["0", "false", "no", "off", " OFF "])
def test_any_false_value_switches_off_and_any_true_value_keeps_it_on(value) -> None:
    assert app_module.cinema_db_overrides({"CINEMA_DB_ENABLED": value}) == {"cinema_db": {"enabled": False}}
    assert app_module.series_rag_overrides({"SERIES_RAG_ENABLED": value}) == {"series_rag": {"enabled": False}}


def test_an_explicit_variable_beats_the_default_and_the_path_cannot_revive_a_disabled_system() -> None:
    assert app_module.build_runtime_config(app_module.cinema_db_overrides({"CINEMA_DB_ENABLED": "0", "CINEMA_DB_PATH": "x.sqlite3"}))["cinema_db"]["enabled"] is False
    chosen = app_module.build_runtime_config(app_module.cinema_db_overrides({"CINEMA_DB_PATH": "cinema_db/data/other.sqlite3"}))["cinema_db"]
    assert chosen["enabled"] is True and chosen["db_path"] == "cinema_db/data/other.sqlite3"  # the path alone picks the file; the default keeps it on
    assert app_module.build_runtime_config(app_module.series_rag_overrides({"VECTORSTORE_QDRANT_URL": "http://h:1"}))["series_rag"]["url"] == "http://h:1"
    assert app_module.build_runtime_config(app_module.series_rag_overrides({"SERIES_RAG_ENABLED": "0", "VECTORSTORE_QDRANT_URL": "http://h:1"}))["series_rag"]["enabled"] is False


def test_the_default_database_is_the_candidate_6_with_the_expected_digest() -> None:
    assert app_module.CONFIG["cinema_db"]["db_path"] == candidate.EXPECTED["path"] == "cinema_db/data/cinema.v4.candidate6.sqlite3"
    assert candidate.EXPECTED["content_sha256"] == "27d2d09e1c0764b85b5734fc5a5ca7c7001e817f0e240c62775440a89b8147ea"
    assert app_module.CONFIG["series_rag"]["enabled"] is True and app_module.CONFIG["cinema_db"]["enabled"] is True


@pytest.mark.skipif(not CANDIDATE.is_file(), reason="needs the candidate 6 file (not versioned)")
def test_the_default_file_is_the_candidate_6_by_name_schema_and_digest_and_the_policy_has_movielens() -> None:
    info = candidate.identify()  # raises CandidateMismatch for any other file; reads build_info only
    assert info["schema_version"] == "4" and info["content_sha256"] == candidate.EXPECTED["content_sha256"]
    built = runtime({})
    cinema = built["orchestrator"].tools["cinema_sql"]
    assert Path(cinema.db_path).resolve() == CANDIDATE.resolve() and cinema.movielens
    app_module.ensure_cinema_db_ready(built["config"]["cinema_db"])  # opens the file with its own policy, as the start does
