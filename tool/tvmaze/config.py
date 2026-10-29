"""Typed, validated view of `CONFIG["tvmaze"]`: only the public call limit.

The value lives only in `app.py` (no defaults here, like `tool/omdb/config.py`). Timeout and the
other constants are internal, in `tool/tvmaze/settings.py`.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TvmazeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_calls_per_turn: int = Field(
        ge=1,
        le=10,
        description=(
            "TVmaze requests allowed in one turn, shared by every run of the turn: identifying a "
            "series costs one, each other piece of data (card with cast or next episode, seasons, "
            "episodes) one more."
        ),
    )


def load_tvmaze_config(config: dict[str, Any] | TvmazeConfig) -> TvmazeConfig:
    """Validate `CONFIG["tvmaze"]` (after `build_runtime_config` overrides)."""
    if isinstance(config, TvmazeConfig):
        return config
    return TvmazeConfig.model_validate(config)
