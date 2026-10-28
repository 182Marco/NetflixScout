"""Explicit dependencies of one tool run (one turn)."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .auth import TmdbCredentials
from .budget import CallBudget
from .cache import CacheKey, TtlCache
from .calls import CallRecorder
from .config import TmdbConfig
from .cooldown import Cooldown

# (url, headers, timeout) -> (status, response headers, body)
Transport = Callable[[str, Mapping[str, str], float], tuple[int, Mapping[str, str], bytes]]


@dataclass(kw_only=True)
class TmdbContext:
    config: TmdbConfig
    credentials: TmdbCredentials
    cache: TtlCache
    cooldown: Cooldown
    budget: CallBudget
    transport: Transport
    api_language: str
    # The current date: what "already released" means (injected in tests).
    today: Callable[[], date] = date.today
    recorder: CallRecorder = field(default_factory=CallRecorder)
    # Responses already obtained in this turn: never requested twice, even with cache_ttl=0.
    memo: dict[CacheKey, dict[str, Any]] = field(default_factory=dict)
    # Requests that were sent and failed in this turn: never sent again (no retries).
    failures: dict[CacheKey, Exception] = field(default_factory=dict)
    # (kind, normalized text, year, department) -> resolution, for this turn.
    resolutions: dict[tuple[Any, ...], Any] = field(default_factory=dict)
    # True for the RAG enrichment: several equally good matches are refused, not ranked by popularity.
    strict_identity: bool = False
    # True for the RAG enrichment: search without the year filter (the corpus year is often off
    # by one and TMDb's filter is exact, so a year-filtered search costs a second search);
    # `_pick_work` checks the year ±1 on the results; the filtered search is the fallback.
    year_after_search: bool = False

    def limit(self, requested: int | None) -> int:
        """Items to return for a list: the request's limit, capped by `max_results`."""
        return min(requested or self.config.max_results, self.config.max_results)
