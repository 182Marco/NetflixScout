"""Typed view of the future `CONFIG["cinema_db"]` (not registered: the tool is not wired into `app.py` yet).

Like the other tools there are no defaults here: the values live in `app.py`. `SUGGESTED_CONFIG` is what to put there when the tool is wired.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CinemaDbConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    db_path: str = Field(min_length=1, description="Path of the SQLite file (relative to the repository root, or absolute).")
    max_queries_per_turn: int = Field(ge=1, le=40, description="SQL queries allowed in one turn, shared by every run of the turn.")
    default_limit: int = Field(ge=1, le=50, description="Rows listed when the request gives no limit.")


SUGGESTED_CONFIG = {"db_path": "cinema_db/data/cinema.sqlite3", "max_queries_per_turn": 12, "default_limit": 25}


def load_cinema_db_config(config: dict[str, Any] | CinemaDbConfig) -> CinemaDbConfig:
    if isinstance(config, CinemaDbConfig):
        return config
    return CinemaDbConfig.model_validate(config)
