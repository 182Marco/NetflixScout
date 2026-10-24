from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from turn import TOOL_PARAM_TURN_ID, TOOL_PARAM_TURN_LANGUAGE

from .auth import TmdbCredentials, load_credentials
from .budget import CallBudget
from .cache import TtlCache
from .config import TmdbConfig
from .context import TmdbContext, Transport
from .cooldown import Cooldown
from .errors import TmdbConfigError
from .http import urllib_transport
from .models.operation_rules import describe_operations
from .models.requests import TmdbToolInput, describe_validation_errors
from .prompt_budget import pack_context
from .runner import overall_status, run_requests
from .settings import API_LANGUAGES, DEFAULT_API_LANGUAGE
from .trace import build_tmdb_trace

TMDB_TOOL_NAME = "tmdb_search"

_DESCRIPTION = (
    "Query The Movie Database (TMDb) for up-to-date facts: cast and crew, release dates, "
    "streaming availability, trailers, images, reviews, recommendations and similar titles, "
    "TV series, seasons and episodes, people and filmographies, collections (sagas), "
    "companies, discover by filters, trending and current charts. Put 1-4 operations in "
    "`requests`; never URLs. Use English names for genres and keywords. A title, name or "
    "external ID is resolved to a TMDb ID by the tool. Operations:\n"
)


def api_language_for(turn_language: Any) -> str:
    return API_LANGUAGES.get(turn_language, DEFAULT_API_LANGUAGE)


def _failure(query: str, error: str, **details: Any) -> dict[str, Any]:
    return {
        "query": query,
        "chunks": [],
        "metadata": {"tmdb": {"status": "error", "error": error, **details}},
        # No step: nothing was called.
        "trace": [],
    }


@dataclass(kw_only=True)
class TmdbTool:
    """Read-only TMDb tool: typed operations, per-turn call budget, TTL cache."""

    config: TmdbConfig
    name: str = TMDB_TOOL_NAME
    description: str = field(default_factory=lambda: _DESCRIPTION + describe_operations())
    input_schema: dict[str, Any] = field(default_factory=lambda: TmdbToolInput.model_json_schema())
    # Loaded from `.env` on first use; injected in tests.
    credentials: TmdbCredentials | None = None
    transport: Transport = urllib_transport
    # Shared across turns (one tool per app); created from `cache_ttl` when not given.
    cache: TtlCache | None = None
    cooldown: Cooldown = field(default_factory=Cooldown)
    _budget: CallBudget | None = field(default=None, init=False, repr=False)
    _budget_turn_id: str | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.cache is None:
            self.cache = TtlCache(self.config.cache_ttl)

    def _credentials(self) -> TmdbCredentials:
        if self.credentials is None:
            self.credentials = load_credentials()
        return self.credentials

    def _turn_budget(self, turn_id: str | None) -> CallBudget:
        """The budget of the turn: shared by every run (and RAG enrichment) with the same id."""
        if turn_id is None or turn_id != self._budget_turn_id:
            self._budget = CallBudget(self.config.max_calls_per_turn)
            self._budget_turn_id = turn_id
        return self._budget

    def new_context(
        self,
        credentials: TmdbCredentials,
        *,
        api_language: str,
        turn_id: str | None = None,
    ) -> TmdbContext:
        """Context of one run: the only reader of the call limit. Runs of the same turn
        (same `turn_id`) draw on one budget; without an id the run gets a fresh one."""
        return TmdbContext(
            config=self.config,
            credentials=credentials,
            cache=self.cache,
            cooldown=self.cooldown,
            budget=self._turn_budget(turn_id),
            transport=self.transport,
            api_language=api_language,
        )

    def run(
        self,
        *,
        query: str,
        params: dict[str, Any] | None = None,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        arguments = dict(params or {})
        turn_language = arguments.pop(TOOL_PARAM_TURN_LANGUAGE, None)
        turn_id = arguments.pop(TOOL_PARAM_TURN_ID, None)
        if query:
            arguments["query"] = query
        try:
            payload = TmdbToolInput.model_validate(arguments)
        except ValidationError as exc:
            return _failure(query, "invalid_request", errors=describe_validation_errors(exc))
        try:
            credentials = self._credentials()
        except TmdbConfigError as exc:
            return _failure(payload.query, exc.code, detail=str(exc))

        ctx = self.new_context(credentials, api_language=api_language_for(turn_language), turn_id=turn_id)
        outcomes = run_requests(ctx, payload.requests)
        packed = pack_context(outcomes, api_language=ctx.api_language, status=overall_status(outcomes))
        return {
            "query": payload.query,
            "chunks": packed.chunks,
            "metadata": {"tmdb": packed.metadata},
            # Outside "metadata": the orchestrator puts metadata in the LLM prompt.
            "trace": build_tmdb_trace(ctx.recorder.calls, packed.attributions),
        }
