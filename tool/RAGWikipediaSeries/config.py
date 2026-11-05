"""Configuration models of this package (own copy; nothing imported from the film project)."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WikidataConfig(_Section):
    api_url: str
    sparql_url: str
    site: str
    contact: str
    user_agent_name: str
    batch_size: int
    min_interval_seconds: float
    timeout_seconds: float
    sparql_timeout_seconds: float
    label_batch_size: int
    max_retries: int
    retry_backoff_seconds: float
    maxlag: int
    languages: list[str]
    mode: str
    snapshot_id: str
    snapshot_root: str
    max_actors: int
