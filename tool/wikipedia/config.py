"""Typed, validated view of `CONFIG["wikipedia"]`: only the five public settings.

The values live only in `app.py` (no defaults here, like `tool/tmdb/config.py`). Timeouts, the
User-Agent, response and cache sizes are internal constants in `tool/wikipedia/settings.py`.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

_UI = {"ui_exposed": True}


class WikipediaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_language: Literal["it", "en"] = Field(
        title="Edizione predefinita",
        description=(
            "Edizione di Wikipedia in cui si cerca quando il planner non ne sceglie una, qualunque sia la "
            "lingua della risposta. L'altra edizione si consulta solo con un passo successivo, deciso dal planner."
        ),
        json_schema_extra=_UI,
    )
    max_results: int = Field(
        ge=1,
        le=5,
        title="Pagine per ricerca",
        description="Pagine candidate restituite al massimo da una ricerca.",
        json_schema_extra=_UI,
    )
    max_calls_per_turn: int = Field(
        ge=1,
        le=8,
        title="Chiamate HTTP per turno",
        description=(
            "Tentativi HTTP verso Wikipedia consentiti in un turno (ricerca, fallback di lingua, "
            "articolo). Le risposte servite dalla cache non contano."
        ),
        json_schema_extra=_UI,
    )
    cache_ttl: int = Field(
        ge=0,
        le=86_400,
        title="Durata cache (s)",
        description="Secondi per cui una risposta (anche l'articolo intero) viene riusata; 0 la disattiva.",
        json_schema_extra=_UI,
    )
    context_chars_per_turn: int = Field(
        ge=4_000,
        le=200_000,
        title="Testo Wikipedia per turno (caratteri)",
        description=(
            "Budget di testo che può entrare nel prompt in un turno, condiviso dai passi dello stesso "
            "turno. Non limita il recupero: il resto resta elencato e richiedibile finché c'è budget."
        ),
        json_schema_extra=_UI,
    )


def load_wikipedia_config(config: dict[str, Any] | WikipediaConfig) -> WikipediaConfig:
    """Validate `CONFIG["wikipedia"]` (after `build_runtime_config` overrides)."""
    if isinstance(config, WikipediaConfig):
        return config
    return WikipediaConfig.model_validate(config)
