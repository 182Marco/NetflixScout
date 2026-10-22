"""Typed, validated view of `CONFIG["you_tube"]`: only the two public settings.

The values live only in `app.py` (no defaults here, like `tmdb/config.py`). Timeouts,
fetch sizes and quota pauses are internal constants in `youtube/settings.py`.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_UI = {"ui_exposed": True}


class YoutubeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_results: int = Field(
        ge=1,
        le=10,
        title="Video per categoria",
        description="Video restituiti al massimo per ogni categoria cercata (trailer, interviste, ...).",
        json_schema_extra=_UI,
    )
    max_searches_per_turn: int = Field(
        ge=1,
        le=3,
        title="Ricerche YouTube per turno",
        description=(
            "Chiamate search.list consentite in un turno (una per categoria); la quota di ricerca "
            "del progetto Google è di 100 chiamate al giorno."
        ),
        json_schema_extra=_UI,
    )


def load_youtube_config(config: dict[str, Any] | YoutubeConfig) -> YoutubeConfig:
    """Validate `CONFIG["you_tube"]` (after `build_runtime_config` overrides)."""
    if isinstance(config, YoutubeConfig):
        return config
    return YoutubeConfig.model_validate(config)
