from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pydantic import ValidationError

from turn import (
    OUTCOME_EMPTY,
    OUTCOME_ERROR,
    OUTCOME_OK,
    RESULT_FOLLOW_UP,
    TOOL_PARAM_TURN_ID,
    TOOL_PARAM_TURN_LANGUAGE,
    tool_outcome,
)

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
from .trace import build_tmdb_trace, tmdb_cards

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
        "outcome": tool_outcome(OUTCOME_ERROR, error),
        "metadata": {"tmdb": {"status": "error", "error": error, **details}},
        # No step: nothing was called.
        "trace": [],
    }


# Errors that mean "TMDb has nothing for this": the answer may be elsewhere, so the planner is asked
# (`turn.RESULT_FOLLOW_UP`) instead of the turn ending on the failure. Other errors (limits, keys,
# network) have no other place to look and are not offered.
UNRESOLVED_ERRORS = ("not_found", "unverified_match", "unresolved_filter")

FILTER_NAME_HINT = (
    " Un filtro per nome (per esempio un genere) non corrisponde a niente in TMDb: i nomi dei generi "
    "di film e serie sono diversi; controlla quelli validi con l'operazione genres (media giusto) e riprova."
)


def _request_label(request: Any) -> str:
    subject = getattr(request, "title", None) or getattr(request, "name", None) or getattr(request, "search_query", None) or ""
    return f"{request.operation.value} «{str(subject)[:60]}»"


def _unresolved_follow_up(requests: list[Any], outcomes: list[Any], *, empty: bool) -> dict[str, Any] | None:
    """The offer to look elsewhere when a request found nothing on TMDb (or all returned empty)."""
    failed = [o for o in outcomes if o.error in UNRESOLVED_ERRORS]
    if not failed and not empty:
        return None
    # `RequestOutcome.index` counts from 1 (runner.py).
    labels = [_request_label(requests[o.index - 1]) + f" ({o.error})" for o in failed if 0 < o.index <= len(requests)]
    resolved = sum(o.status == "ok" for o in outcomes)
    summary = (
        "TMDb non ha trovato dati per: " + (", ".join(labels) or "la richiesta") + f". Richieste risolte: {resolved}. "
        "Se l'informazione può stare altrove (un'opera, una trilogia o una serie di film che non è una raccolta "
        "TMDb, un dettaglio di trama o di struttura), scegli un altro tool con i dati già ottenuti; altrimenti ritorna done."
        + (FILTER_NAME_HINT if any(o.error == "unresolved_filter" for o in failed) else "")
    )
    return {"available": True, "reasons": [o.error for o in failed] or ["empty"], "summary": summary}


def _first_error(outcomes: list[Any]) -> str | None:
    return next((outcome.error for outcome in outcomes if outcome.error), None)


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
    # The current date, for "already released" filters; injected in tests.
    today: Callable[[], date] = date.today
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
            today=self.today,
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
        status = overall_status(outcomes)
        if status == "error":
            outcome = tool_outcome(OUTCOME_ERROR, _first_error(outcomes))
        else:
            outcome = tool_outcome(OUTCOME_OK if packed.chunks else OUTCOME_EMPTY)
        result = {
            "query": payload.query,
            "chunks": packed.chunks,
            "outcome": outcome,
            "metadata": {"tmdb": packed.metadata},
            # Outside "metadata": the orchestrator puts metadata in the LLM prompt.
            "trace": build_tmdb_trace(ctx.recorder.calls, packed.attributions, tmdb_cards(outcomes)),
        }
        follow_up = _unresolved_follow_up(payload.requests, outcomes, empty=outcome["status"] == OUTCOME_EMPTY)
        if follow_up is not None:
            result[RESULT_FOLLOW_UP] = follow_up
        return result
