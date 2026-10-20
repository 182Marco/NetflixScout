"""Typed, validated view of `CONFIG["movie_db"]`.

The values live only in `app.py`: these models have no defaults, so a missing key is
an error instead of a silently duplicated value. `MovieDbConfig.model_json_schema()`
is the schema a future web form can be generated from; `ui_exposed` marks the fields
that make sense to edit from a UI (limits yes, paths and prompts no).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _ui(exposed: bool) -> dict[str, Any]:
    return {"ui_exposed": exposed}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QueryConfig(_Strict):
    default_limit: int = Field(
        ge=1,
        title="Risultati predefiniti",
        description="Numero di film restituiti quando la richiesta non ne indica uno.",
        json_schema_extra=_ui(True),
    )
    max_limit: int = Field(
        ge=1,
        le=500,
        title="Risultati massimi",
        description="Tetto massimo di righe per query, applicato sempre dal codice.",
        json_schema_extra=_ui(True),
    )
    min_ratings: int = Field(
        ge=0,
        title="Voti minimi",
        description="Numero minimo di voti perché un film entri nelle classifiche.",
        json_schema_extra=_ui(True),
    )
    timeout_ms: int = Field(
        ge=10,
        le=60_000,
        title="Timeout query (ms)",
        description="Tempo massimo di una chiamata al database prima dell'interruzione.",
        json_schema_extra=_ui(True),
    )

    @model_validator(mode="after")
    def _limits_are_consistent(self) -> QueryConfig:
        if self.max_limit < self.default_limit:
            raise ValueError("max_limit must be >= default_limit.")
        return self


class ParserConfig(_Strict):
    model: str = Field(
        min_length=1,
        title="Modello del parser",
        description="Modello LLM che converte la richiesta in un'operazione whitelistata.",
        json_schema_extra=_ui(False),
    )
    instructions: str = Field(
        min_length=1,
        title="Istruzioni del parser",
        description="Prompt di sistema del parser; il segnaposto {genres} riceve i generi validi.",
        json_schema_extra=_ui(False),
    )


class IngestionConfig(_Strict):
    batch_size: int = Field(
        ge=1,
        title="Batch di ingestion",
        description="Righe CSV inserite per transazione durante la build offline.",
        json_schema_extra=_ui(False),
    )
    include_ratings: bool = Field(
        title="Includi voti grezzi",
        description="Salva la tabella ratings completa (circa 32M righe) oltre alle statistiche.",
        json_schema_extra=_ui(False),
    )
    include_tags: bool = Field(
        title="Includi tag",
        description="Importa i tag degli utenti.",
        json_schema_extra=_ui(False),
    )


class MovieDbConfig(_Strict):
    enabled: bool = Field(
        title="Abilitato",
        description="Registra il tool movie_db_search nell'orchestratore.",
        json_schema_extra=_ui(False),
    )
    db_path: str = Field(
        min_length=1,
        title="File del database",
        description="Percorso del file SQLite, relativo alla root del repository.",
        json_schema_extra=_ui(False),
    )
    source_dir: str = Field(
        min_length=1,
        title="Cartella dei CSV",
        description="Cartella con i CSV di MovieLens 32M usati dalla build offline.",
        json_schema_extra=_ui(False),
    )
    query: QueryConfig
    parser: ParserConfig
    ingestion: IngestionConfig


def load_movie_db_config(config: dict[str, Any] | MovieDbConfig) -> MovieDbConfig:
    """Validate `CONFIG["movie_db"]` (after `build_runtime_config` overrides)."""
    if isinstance(config, MovieDbConfig):
        return config
    return MovieDbConfig.model_validate(config)
