from __future__ import annotations

import pytest
from pydantic import ValidationError

import app as app_module
from tool.omdb.config import OmdbConfig, load_omdb_config


def test_the_section_has_only_the_public_call_limit() -> None:
    assert set(app_module.CONFIG["omdb"]) == {"max_calls_per_turn"}
    assert set(OmdbConfig.model_fields) == {"max_calls_per_turn"}
    assert load_omdb_config(app_module.CONFIG["omdb"]).max_calls_per_turn == 10


def test_a_missing_or_extra_field_is_an_error() -> None:
    with pytest.raises(ValidationError):
        load_omdb_config({})
    with pytest.raises(ValidationError):
        load_omdb_config({"max_calls_per_turn": 2, "timeout": 5})
    with pytest.raises(ValidationError):
        load_omdb_config({"max_calls_per_turn": 0})


def test_an_override_goes_through_build_runtime_config() -> None:
    config = app_module.build_runtime_config({"omdb": {"max_calls_per_turn": 2}})

    assert load_omdb_config(config["omdb"]).max_calls_per_turn == 2


def test_a_validated_config_is_returned_as_it_is() -> None:
    config = OmdbConfig(max_calls_per_turn=3)

    assert load_omdb_config(config) is config
