from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from turn import (
    OUTCOME_EMPTY,
    OUTCOME_ERROR,
    OUTCOME_OK,
    TOOL_PARAM_TURN_ID,
    TOOL_PARAM_TURN_LANGUAGE,
    tool_outcome,
)

from .auth import OmdbCredentials, load_credentials
from .config import OmdbConfig
from .errors import OmdbConfigError, OmdbError, OmdbIdMismatch
from .http import HttpSession, Transport, get_json, urllib_transport
from .identify import IDENTIFIED, NOT_FOUND, UNVERIFIED, identify, normalize_title
from .models import OmdbToolInput, describe_validation_errors
from .ratings import any_available, extract_ratings
from .responses import NOT_FOUND as RESPONSE_NOT_FOUND
from .responses import OK, TOO_MANY, response_kind
from .trace import build_omdb_trace
from .turns import TurnSessions

OMDB_TOOL_NAME = "omdb_search"
SOURCE = "OMDb"

_DESCRIPTION = (
    "Look up the scores of ONE identified film or series on OMDb: the IMDb rating (voted by the "
    "audience), the Metascore and the Rotten Tomatoes score (aggregates of professional critics' "
    "reviews: scores only, never the text of reviews). Identify the work with `imdb_id` when the "
    "user, the conversation or a step already done in this turn gives one; otherwise with `title` "
    "(and `year` or `type` only when the request or the conversation states them). An ambiguous or "
    "unverified title returns the alternatives instead of scores, so the user can choose. A score may "
    "be not_available: it is reported as such, never estimated. Not for rankings or lists of "
    "titles, cast, plot, streaming or review texts."
)

STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_ERROR = "error"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_UNVERIFIED = "unverified"
STATUS_NOT_FOUND = "not_found"
STATUS_NO_RATINGS = "no_ratings"


def planner_schema() -> dict[str, Any]:
    """`OmdbToolInput` JSON schema for the planner catalog, without the class docstring: the
    tool `description` already says what the tool does. Validation uses the model, not this dict."""
    schema = OmdbToolInput.model_json_schema()
    schema.pop("description", None)
    return schema


def _failure(query: str, error: str, *, calls: list[dict[str, str]] | None = None, **details: Any) -> dict[str, Any]:
    return {
        "query": query,
        "chunks": [],
        "outcome": tool_outcome(OUTCOME_ERROR, error),
        "metadata": {"omdb": {"status": STATUS_ERROR, "source": SOURCE, "error": error, **details}},
        # No step when nothing was called.
        "trace": build_omdb_trace(calls, status=STATUS_ERROR, reason=error) if calls else [],
    }


def _result(
    request: OmdbToolInput,
    calls: list[dict[str, str]],
    *,
    status: str,
    reason: str | None = None,
    record: dict[str, Any] | None = None,
    ratings: list[dict[str, Any]] | None = None,
    candidates: list[dict[str, str]] | None = None,
    imdb_id: str | None = None,
) -> dict[str, Any]:
    record = record or {}
    title, year, work_type = record.get("Title"), record.get("Year"), record.get("Type")
    if status == STATUS_OK:
        outcome = tool_outcome(OUTCOME_OK)
    else:
        outcome = tool_outcome(OUTCOME_EMPTY, reason or status)
    metadata: dict[str, Any] = {
        "status": status,
        "source": SOURCE,
        "imdb_id": imdb_id,
        "title": title if isinstance(title, str) else None,
        "year": year if isinstance(year, str) else None,
        "type": work_type if isinstance(work_type, str) else None,
        "ratings": ratings or [],
        "candidates": candidates or [],
    }
    return {
        "query": request.query,
        "chunks": [],
        "outcome": outcome,
        # Everything is in metadata (all of it reaches the prompt; no URL or key is in it).
        "metadata": {"omdb": metadata},
        # Outside "metadata": the orchestrator puts metadata in the LLM prompt.
        "trace": build_omdb_trace(
            calls,
            status=status,
            reason=reason,
            title=metadata["title"],
            year=metadata["year"],
            work_type=metadata["type"],
            imdb_id=imdb_id,
            ratings=ratings,
            candidates=candidates,
        ),
    }


@dataclass(kw_only=True)
class OmdbTool:
    """Read-only OMDb tool: typed input, constant requests, scores of a work identified by IMDb ID.

    No cache: a session (budget and memo) lives only for the turn it belongs to.
    """

    config: OmdbConfig
    name: str = OMDB_TOOL_NAME
    description: str = _DESCRIPTION
    input_schema: dict[str, Any] = field(default_factory=planner_schema)
    # Loaded from `.env` on first use; injected in tests.
    credentials: OmdbCredentials | None = None
    transport: Transport = urllib_transport
    _turns: TurnSessions = field(default_factory=TurnSessions, init=False, repr=False)

    def _credentials(self) -> OmdbCredentials:
        if self.credentials is None:
            self.credentials = load_credentials()
        return self.credentials

    def run(
        self,
        *,
        query: str,
        params: dict[str, Any] | None = None,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        arguments = dict(params or {})
        # Scores do not depend on the language of the turn.
        arguments.pop(TOOL_PARAM_TURN_LANGUAGE, None)
        turn_id = arguments.pop(TOOL_PARAM_TURN_ID, None)
        if query:
            arguments["query"] = query
        try:
            request = OmdbToolInput.model_validate(arguments)
        except ValidationError as exc:
            return _failure(query, "invalid_request", errors=describe_validation_errors(exc))
        try:
            credentials = self._credentials()
        except OmdbConfigError as exc:
            return _failure(request.query, exc.code, detail=str(exc))

        session = self._turns.session_for(
            turn_id,
            lambda: HttpSession(
                credentials=credentials,
                transport=self.transport,
                max_calls=self.config.max_calls_per_turn,
            ),
        )
        # Calls of this run only: the session may hold earlier runs of the same turn.
        first_call = len(session.recorder.calls)
        try:
            return self._lookup(request, session, first_call)
        except OmdbError as exc:
            return _failure(request.query, exc.code, calls=session.recorder.calls[first_call:])

    def _lookup(self, request: OmdbToolInput, session: HttpSession, first_call: int) -> dict[str, Any]:
        def calls() -> list[dict[str, str]]:
            return session.recorder.calls[first_call:]

        imdb_id, expected_title = request.imdb_id, None
        if imdb_id is None:
            assert request.title is not None  # guaranteed by the model
            search = {"s": request.title, "r": "json", **({"type": request.type} if request.type else {})}
            payload = get_json(session, search)
            kind = response_kind(payload)
            if kind == TOO_MANY:
                return _result(request, calls(), status=STATUS_UNVERIFIED, reason="too_many_results")
            if kind == RESPONSE_NOT_FOUND:
                return _result(request, calls(), status=STATUS_NOT_FOUND)
            found = identify(payload.get("Search"), title=request.title, year=request.year, type=request.type)
            if found.status != IDENTIFIED:
                status = {NOT_FOUND: STATUS_NOT_FOUND, UNVERIFIED: STATUS_UNVERIFIED}.get(found.status, STATUS_AMBIGUOUS)
                return _result(request, calls(), status=status, candidates=found.candidates)
            imdb_id, expected_title = found.imdb_id, found.title

        record = get_json(session, {"i": imdb_id, "r": "json"})
        if response_kind(record) != OK:
            return _result(request, calls(), status=STATUS_NOT_FOUND, imdb_id=imdb_id)
        returned = record.get("imdbID")
        if not isinstance(returned, str) or returned.lower() != imdb_id:
            raise OmdbIdMismatch("OMDb returned a different record than the one identified.")
        if expected_title is not None and normalize_title(record.get("Title")) != normalize_title(expected_title):
            raise OmdbIdMismatch("OMDb returned a different record than the one identified.")
        ratings = extract_ratings(record)
        if any_available(ratings):
            return _result(request, calls(), status=STATUS_OK, record=record, ratings=ratings, imdb_id=imdb_id)
        return _result(
            request, calls(), status=STATUS_EMPTY, reason=STATUS_NO_RATINGS, record=record, ratings=ratings, imdb_id=imdb_id
        )
