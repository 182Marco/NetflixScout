from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from app import CONFIG, build_runtime_config
from movie_db.config import MovieDbConfig, load_movie_db_config


def test_config_has_movie_db_section_and_keeps_existing_ones() -> None:
    assert {"orchestrator", "rag", "movie_db"} <= set(CONFIG)
    assert "conversation" in CONFIG["orchestrator"]
    assert "retrieval" in CONFIG["rag"]
    assert load_movie_db_config(CONFIG["movie_db"]).enabled is True


def test_overrides_go_through_build_runtime_config() -> None:
    runtime = build_runtime_config({"movie_db": {"query": {"max_limit": 20}}})

    config = load_movie_db_config(runtime["movie_db"])

    assert config.query.max_limit == 20
    assert config.query.default_limit == CONFIG["movie_db"]["query"]["default_limit"]
    assert CONFIG["movie_db"]["query"]["max_limit"] == 50  # defaults untouched


def test_unknown_keys_are_rejected() -> None:
    raw = copy.deepcopy(CONFIG["movie_db"])
    raw["query"]["sql"] = "DROP TABLE movies"

    with pytest.raises(ValidationError):
        load_movie_db_config(raw)


def test_max_limit_below_default_limit_is_rejected() -> None:
    raw = copy.deepcopy(CONFIG["movie_db"])
    raw["query"]["max_limit"] = raw["query"]["default_limit"] - 1

    with pytest.raises(ValidationError):
        load_movie_db_config(raw)


def test_models_have_no_defaults_so_config_is_the_only_source() -> None:
    raw = copy.deepcopy(CONFIG["movie_db"])
    del raw["query"]["timeout_ms"]

    with pytest.raises(ValidationError):
        load_movie_db_config(raw)


def test_json_schema_marks_ui_exposed_fields() -> None:
    schema = MovieDbConfig.model_json_schema()
    query_props = schema["$defs"]["QueryConfig"]["properties"]

    assert query_props["max_limit"]["ui_exposed"] is True
    assert schema["properties"]["db_path"]["ui_exposed"] is False
    assert schema["$defs"]["ParserConfig"]["properties"]["instructions"]["ui_exposed"] is False
