"""Typed, validated view of `CONFIG["omdb"]`: only the public call limit.

The value lives only in `app.py` (no defaults here, like `tool/youtube/config.py`). Timeout and the
other constants are internal, in `tool/omdb/settings.py`.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OmdbConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_calls_per_turn: int = Field(
        ge=1,
        le=10,
        description=(
            "OMDb requests allowed in one turn, shared by every run of the turn: a title lookup "
            "costs two (search, then the record by IMDb ID), an IMDb ID given directly costs one."
        ),
    )


def load_omdb_config(config: dict[str, Any] | OmdbConfig) -> OmdbConfig:
    """Validate `CONFIG["omdb"]` (after `build_runtime_config` overrides)."""
    if isinstance(config, OmdbConfig):
        return config
    return OmdbConfig.model_validate(config)
