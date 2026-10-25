from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

import app as app_module
from tool.youtube import errors
from tool.youtube.config import YoutubeConfig, load_youtube_config


def test_config_has_exactly_the_two_public_settings() -> None:
    assert set(app_module.CONFIG["you_tube"]) == {"max_results", "max_searches_per_turn"}
    assert load_youtube_config(app_module.CONFIG["you_tube"]) == YoutubeConfig(max_results=3, max_searches_per_turn=2)


def test_overrides_are_deep_merged_and_validated() -> None:
    merged = app_module.build_runtime_config({"you_tube": {"max_results": 5}})

    assert load_youtube_config(merged["you_tube"]).model_dump() == {"max_results": 5, "max_searches_per_turn": 2}
    assert app_module.CONFIG["you_tube"]["max_results"] == 3


def test_a_validated_config_is_returned_as_is() -> None:
    config = YoutubeConfig(max_results=1, max_searches_per_turn=1)

    assert load_youtube_config(config) is config


@pytest.mark.parametrize(
    "override",
    [
        {"max_results": 0},
        {"max_results": 11},
        {"max_searches_per_turn": 0},
        {"max_searches_per_turn": 4},
        # No cross-turn cache and no geographic restriction (plan rev. 2, points 2 and 3).
        {"cache_ttl": 3600},
        {"region_code": "IT"},
    ],
)
def test_invalid_or_extra_settings_are_rejected(override) -> None:
    with pytest.raises(ValidationError):
        load_youtube_config(app_module.build_runtime_config({"you_tube": override})["you_tube"])


def test_config_has_no_defaults() -> None:
    with pytest.raises(ValidationError):
        YoutubeConfig()


def test_error_codes_are_distinct_and_messages_default_to_the_code() -> None:
    codes = [
        cls.code
        for _, cls in inspect.getmembers(errors, inspect.isclass)
        if issubclass(cls, errors.YoutubeError) and cls is not errors.YoutubeError
    ]

    assert len(codes) == len(set(codes))
    assert set(codes) == {
        "not_configured",
        "unauthorized",
        "api_not_enabled",
        "quota_exceeded",
        "rate_limited",
        "timeout",
        "network_error",
        "http_error",
    }
    assert str(errors.YoutubeQuotaExceeded()) == "quota_exceeded"
