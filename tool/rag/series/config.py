"""Typed, validated view of `CONFIG["series_rag"]`. The values live only in `app.py` (no defaults here)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SeriesRagConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(description="Feature flag: the tool is registered (and its routing rule given to the planner) only when true.")
    url: str = Field(min_length=1, description="Qdrant server.")
    collection: str = Field(min_length=1, description="Series collection (read only).")
    embedding_model: str = Field(min_length=1)
    embedding_dimensions: int = Field(ge=1)
    parser_model: str = Field(min_length=1)
    k_final: int = Field(ge=1, le=10, description="Results returned when the request gives no number.")
    pool: int = Field(ge=10, le=50, description="K-wide: candidates read from Qdrant before exclusions and penalty (hard cap 50).")
    penalty_lambda: float = Field(ge=0, le=2)
    rerank_enabled: bool
    rerank_model: str = Field(min_length=1)
    rerank_pool: int = Field(ge=2, le=50)
    rerank_plot_chars: int = Field(ge=100, le=3000)
    plot_chars_to_answer: int = Field(ge=200, le=3000, description="Plot characters per result that reach the final answer.")

    @model_validator(mode="after")
    def _rerank_within_pool(self) -> "SeriesRagConfig":
        if self.rerank_pool > self.pool:
            raise ValueError("rerank_pool cannot exceed pool (the K-wide)")
        return self


def load_series_rag_config(config: dict[str, Any] | SeriesRagConfig) -> SeriesRagConfig:
    """Validate `CONFIG["series_rag"]` (after `build_runtime_config` overrides)."""
    if isinstance(config, SeriesRagConfig):
        return config
    return SeriesRagConfig.model_validate(config)
