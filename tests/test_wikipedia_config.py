from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

import app as app_module
from wikipedia import errors, settings
from wikipedia.config import WikipediaConfig, load_wikipedia_config


def test_config_has_exactly_the_four_public_settings() -> None:
    assert set(app_module.CONFIG["wikipedia"]) == {
        "max_results",
        "max_calls_per_turn",
        "cache_ttl",
        "context_chars_per_turn",
    }
    assert load_wikipedia_config(app_module.CONFIG["wikipedia"]) == WikipediaConfig(
        max_results=3, max_calls_per_turn=6, cache_ttl=3600, context_chars_per_turn=40_000
    )


def test_overrides_are_deep_merged_and_validated() -> None:
    merged = app_module.build_runtime_config({"wikipedia": {"context_chars_per_turn": 80_000}})

    assert load_wikipedia_config(merged["wikipedia"]).context_chars_per_turn == 80_000
    assert app_module.CONFIG["wikipedia"]["context_chars_per_turn"] == 40_000


def test_a_validated_config_is_returned_as_is() -> None:
    config = WikipediaConfig(max_results=1, max_calls_per_turn=1, cache_ttl=0, context_chars_per_turn=4000)

    assert load_wikipedia_config(config) is config


@pytest.mark.parametrize(
    "override",
    [
        {"max_results": 0},
        {"max_results": 6},
        {"max_calls_per_turn": 0},
        {"max_calls_per_turn": 9},
        {"cache_ttl": -1},
        {"cache_ttl": 86_401},
        {"context_chars_per_turn": 3_999},
        {"context_chars_per_turn": 200_001},
        {"user_agent": "x"},
        {"timeout": 5},
    ],
)
def test_invalid_or_extra_settings_are_rejected(override) -> None:
    with pytest.raises(ValidationError):
        load_wikipedia_config(app_module.build_runtime_config({"wikipedia": override})["wikipedia"])


def test_config_has_no_defaults() -> None:
    with pytest.raises(ValidationError):
        WikipediaConfig()


def test_user_agent_follows_the_wikimedia_format_with_a_contact() -> None:
    agent = settings.USER_AGENT

    assert agent.startswith("NetflixScout/") and "(" in agent and ")" in agent
    assert "https://github.com/182Marco/NetflixScout" in agent and "@" in agent
    assert "Mozilla" not in agent


def test_every_error_class_is_a_wikipedia_error_with_its_own_code() -> None:
    classes = [c for _, c in inspect.getmembers(errors, inspect.isclass) if issubclass(c, errors.WikipediaError)]
    codes = [c.code for c in classes if c is not errors.WikipediaError]

    assert len(codes) == len(set(codes)) >= 5
