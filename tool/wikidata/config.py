"""Typed, validated view of `CONFIG["wikidata"]`: only the public call limit.

The value lives only in `app.py` (no defaults here, like `tool/tvmaze/config.py`). Timeout and the
other constants are internal, in `tool/wikidata/settings.py`.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WikidataConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_calls_per_turn: int = Field(
        ge=1,
        le=12,
        description=(
            "Wikidata requests allowed in one turn, shared by every run of the turn: a title costs "
            "one to identify (every film and series with that exact label; three if it falls back to the "
            "text search; an IMDb or TMDb id costs one), the relations of the work one more and the "
            "members of its franchise one more."
        ),
    )


def load_wikidata_config(config: dict[str, Any] | WikidataConfig) -> WikidataConfig:
    """Validate `CONFIG["wikidata"]` (after `build_runtime_config` overrides)."""
    if isinstance(config, WikidataConfig):
        return config
    return WikidataConfig.model_validate(config)
