from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

import app as app_module
from tmdb.config import TmdbConfig, load_tmdb_config

ROOT = Path(__file__).resolve().parents[1]


def test_config_has_exactly_the_three_public_settings() -> None:
    assert set(app_module.CONFIG["tmdb"]) == {"max_results", "max_calls_per_turn", "cache_ttl"}
    assert load_tmdb_config(app_module.CONFIG["tmdb"]) == TmdbConfig(max_results=5, max_calls_per_turn=6, cache_ttl=3600)


def test_overrides_are_deep_merged_and_validated() -> None:
    merged = app_module.build_runtime_config({"tmdb": {"max_results": 3}})

    assert load_tmdb_config(merged["tmdb"]).model_dump() == {"max_results": 3, "max_calls_per_turn": 6, "cache_ttl": 3600}
    assert app_module.CONFIG["tmdb"]["max_results"] == 5


@pytest.mark.parametrize(
    "override",
    [
        {"max_results": 0},
        {"max_results": 21},
        {"max_calls_per_turn": 0},
        {"max_calls_per_turn": 21},
        {"cache_ttl": -1},
        {"cache_ttl": 86_401},
        {"timeout": 5},
    ],
)
def test_invalid_or_extra_settings_are_rejected(override) -> None:
    with pytest.raises(ValidationError):
        load_tmdb_config(app_module.build_runtime_config({"tmdb": override})["tmdb"])


def test_only_the_budget_reads_the_call_limit() -> None:
    """No second HTTP limit: `max_calls_per_turn` is read only where the budget is created."""
    readers = set()
    for path in sorted((ROOT / "tmdb").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and node.attr == "max_calls_per_turn":
                readers.add(path.relative_to(ROOT).as_posix())
    assert readers == {"tmdb/tool.py"}
