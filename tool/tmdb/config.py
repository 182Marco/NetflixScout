"""Typed, validated view of `CONFIG["tmdb"]`: only the three public settings.

The values live only in `app.py` (no defaults here, like `movie_db/config.py`).
Timeouts, cache size and context limits are internal constants in `tool/tmdb/settings.py`
and `tool/tmdb/prompt_budget.py`; none of them limits HTTP calls.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_UI = {"ui_exposed": True}


class TmdbConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_results: int = Field(
        ge=1,
        le=20,
        title="Risultati massimi",
        description="Elementi restituiti da ricerche, discover, trending, classifiche e liste correlate.",
        json_schema_extra=_UI,
    )
    max_calls_per_turn: int = Field(
        ge=1,
        le=20,
        title="Chiamate HTTP per turno",
        description="Tentativi HTTP verso TMDb consentiti in un turno: unico limite, applicato dal codice.",
        json_schema_extra=_UI,
    )
    cache_ttl: int = Field(
        ge=0,
        le=86_400,
        title="Durata cache (s)",
        description="Secondi per cui una risposta TMDb viene riusata tra i turni; 0 la disattiva.",
        json_schema_extra=_UI,
    )


def load_tmdb_config(config: dict[str, Any] | TmdbConfig) -> TmdbConfig:
    """Validate `CONFIG["tmdb"]` (after `build_runtime_config` overrides)."""
    if isinstance(config, TmdbConfig):
        return config
    return TmdbConfig.model_validate(config)
