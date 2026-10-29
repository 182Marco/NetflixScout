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

from .config import WikidataConfig
from .errors import WikidataError
from .http import get_json, urllib_transport
from .identify import AMBIGUOUS, IDENTIFIED, NOT_FOUND, UNVERIFIED, Identification, identify, parse_search
from .models import WikidataToolInput, describe_validation_errors
from .normalize import Item, parse_candidates, parse_members, parse_relations, row_count
from .queries import (
    QID,
    details_request,
    imdb_request,
    label_request,
    members_request,
    relations_request,
    search_request,
    tmdb_request,
)
from .session import PROCESS_PAUSE, HttpSession, RateLimitPause, Transport, TurnSessions
from .settings import MAX_CONTAINERS, SEARCH_LIMIT, SPARQL_ROW_LIMIT
from .trace import build_wikidata_trace

WIKIDATA_TOOL_NAME = "wikidata_search"

_DESCRIPTION = (
    "Structured relations between works, from Wikidata, for ONE film or series. operation resolve: tell "
    "works that share a title apart with year, director, IMDb id and TMDb id. operation relations: the "
    "works it is based on (literary or film source), the works based on it (remakes, adaptations, "
    "inspired works), the previous and next work in its series and the other works of its franchise. "
    "Identify the work with `title` (and `year`, `director`, `type` only when the request, the "
    "conversation or an earlier step states them), or with an IMDb or TMDb id given there; an ambiguous "
    "or unverified title returns the alternatives instead of data. Only relations Wikidata records are "
    "returned: the list can be incomplete, an empty one is not proof that none exist. Not for cast, "
    "plot, awards, scores, where to watch, trailers, recommendations or lists of films by genre or "
    "person."
)

STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_UNVERIFIED = "unverified"
STATUS_NOT_FOUND = "not_found"
STATUS_NO_RELATIONS = "no_relations"

# Errors after which another source can still answer: the planner is offered a next step.
RECOVERABLE_ERRORS = {"rate_limited", "timeout", "network_error", "http_error", "response_too_large"}

_NOTE = (
    "Wikidata lists only the relations its editors recorded, so a list can be incomplete and an empty one "
    "proves nothing. 'Based on' covers remakes, adaptations and works that are only inspired by the "
    "original: Wikidata does not say which. Previous and next give the order in a series, not whether a "
    "work is a sequel, a prequel or a reboot."
)


def planner_schema() -> dict[str, Any]:
    """`WikidataToolInput` JSON schema for the planner catalog, without the class docstring: the tool
    `description` already says what the tool does. Validation uses the model, not this dict."""
    schema = WikidataToolInput.model_json_schema()
    schema.pop("description", None)
    return schema


def _follow_up(reasons: list[str], summary: str) -> dict[str, Any]:
    return {"available": bool(reasons), "reasons": reasons, "summary": summary}


def _model_view(row: dict[str, Any]) -> dict[str, Any]:
    """A work as the model reads it: no Wikidata item id."""
    return {key: value for key, value in row.items() if key != "id"}


def _failure(
    query: str, error: str, *, calls: list[dict[str, str]] | None = None, operation: str | None = None, work: dict[str, Any] | None = None, **details: Any
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "query": query,
        "chunks": [],
        "outcome": tool_outcome(OUTCOME_ERROR, error),
        "metadata": {"wikidata": {"status": STATUS_ERROR, "error": error, **({"work": _model_view(work)} if work else {}), **details}},
        # No step when nothing was called.
        "trace": build_wikidata_trace(calls, status=STATUS_ERROR, reason=error, operation=operation, work=work) if calls else [],
    }
    if error in RECOVERABLE_ERRORS:
        result[RESULT_FOLLOW_UP] = _follow_up(
            [error],
            f"Wikidata could not be read ({error}). wikipedia_search or tmdb_search can answer part of the "
            "request if it allows it; otherwise say what is missing.",
        )
    return result


@dataclass(kw_only=True)
class WikidataTool:
    """Read-only Wikidata tool: typed input, constant requests, a work identified by title or external id.

    No cache: a session (budget and memo) lives only for the turn it belongs to.
    """

    config: WikidataConfig
    name: str = WIKIDATA_TOOL_NAME
    description: str = _DESCRIPTION
    input_schema: dict[str, Any] = field(default_factory=planner_schema)
    transport: Transport = urllib_transport
    # Shared by the whole process by default (the limit is per client); injected in tests.
    pause: RateLimitPause = field(default_factory=lambda: PROCESS_PAUSE)
    # Today, to leave out what is not yet released; injected in tests.
    clock: Callable[[], date] = date.today
    _turns: TurnSessions = field(default_factory=TurnSessions, init=False, repr=False)

    def run(
        self,
        *,
        query: str,
        params: dict[str, Any] | None = None,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        arguments = dict(params or {})
        # The data does not depend on the language of the turn.
        arguments.pop(TOOL_PARAM_TURN_LANGUAGE, None)
        turn_id = arguments.pop(TOOL_PARAM_TURN_ID, None)
        if query:
            arguments["query"] = query
        try:
            request = WikidataToolInput.model_validate(arguments)
        except ValidationError as exc:
            return _failure(query, "invalid_request", errors=describe_validation_errors(exc))

        session = self._turns.session_for(
            turn_id,
            lambda: HttpSession(transport=self.transport, max_calls=self.config.max_calls_per_turn, pause=self.pause),
        )
        # Calls of this run only: the session may hold earlier runs of the same turn.
        first_call = len(session.calls)
        try:
            return self._lookup(request, session, first_call)
        except WikidataError as exc:
            return _failure(request.query, exc.code, calls=session.calls[first_call:], operation=request.operation)

    # --- identification -------------------------------------------------------------------------------

    def _identify(self, request: WikidataToolInput, session: HttpSession, today: date) -> Identification:
        if request.imdb_id is not None:
            items = parse_candidates(get_json(session, imdb_request(request.imdb_id)))
            return identify(items, today=today, media=request.type)
        if request.tmdb_id is not None:
            assert request.type is not None  # guaranteed by the model
            items = parse_candidates(get_json(session, tmdb_request(request.tmdb_id, request.type)))
            return identify(items, today=today, media=request.type)
        assert request.title is not None  # guaranteed by the model
        # First every film and series with exactly this label, one request: the text search ranks by
        # notoriety across all kinds of items, so a lesser known film of the same title can be past its cut.
        payload = get_json(session, label_request(request.title, request.language))
        by_label = identify(
            parse_candidates(payload),
            today=today,
            media=request.type,
            search=[{"id": qid, "texts": [request.title]} for qid in parse_candidates(payload)],
            title=request.title,
            year=request.year,
            director=request.director,
            complete=row_count(payload) < SPARQL_ROW_LIMIT,
        )
        if by_label.status in (IDENTIFIED, AMBIGUOUS):
            return by_label
        # Nothing fits the exact label (another capitalization, an alias, a typo): the text search.
        return self._identify_by_search(request, session, today)

    def _identify_by_search(self, request: WikidataToolInput, session: HttpSession, today: date) -> Identification:
        assert request.title is not None
        found = parse_search(get_json(session, search_request(request.title, request.language)))
        ids = [row["id"] for row in found if QID.match(row["id"])]
        if not ids:
            return Identification(NOT_FOUND)
        items = parse_candidates(get_json(session, details_request(ids)))
        return identify(
            items,
            today=today,
            media=request.type,
            search=found,
            title=request.title,
            year=request.year,
            director=request.director,
            complete=len(found) < SEARCH_LIMIT,
        )

    def _lookup(self, request: WikidataToolInput, session: HttpSession, first_call: int) -> dict[str, Any]:
        def calls() -> list[dict[str, str]]:
            return session.calls[first_call:]

        today = self.clock()
        found = self._identify(request, session, today)
        if found.status != IDENTIFIED or found.work is None:
            return self._not_identified(request, calls(), found)
        work = found.work
        if request.operation == "resolve":
            return self._resolved(request, calls(), work)

        try:
            related = parse_relations(
                get_json(session, relations_request(work["id"])), subject=work["id"], today=today
            )
        except WikidataError as exc:
            return _failure(request.query, exc.code, calls=calls(), operation=request.operation, work=work)
        unavailable: dict[str, str] = {}
        franchises: list[dict[str, Any]] = []
        partial = False
        containers = related["containers"][:MAX_CONTAINERS]
        if containers:
            try:
                payload = get_json(session, members_request([row["id"] for row in containers]))
            except WikidataError as exc:
                unavailable["franchise"] = exc.code
            else:
                franchises = parse_members(payload, containers=containers, today=today)
                partial = row_count(payload) >= SPARQL_ROW_LIMIT
        return self._related(request, calls(), work, related, franchises, unavailable, partial)

    # --- results --------------------------------------------------------------------------------------

    def _not_identified(self, request: WikidataToolInput, calls: list[dict[str, str]], found: Identification) -> dict[str, Any]:
        status = {NOT_FOUND: STATUS_NOT_FOUND, UNVERIFIED: STATUS_UNVERIFIED}.get(found.status, STATUS_AMBIGUOUS)
        reasons = [status] if status in (STATUS_NOT_FOUND, STATUS_UNVERIFIED) else []
        summary = {
            STATUS_NOT_FOUND: "Wikidata has no released film or series with this title or id.",
            STATUS_UNVERIFIED: (
                "Wikidata has only works that resemble the title or do not match the year or the director "
                "given, none is certainly the one asked."
            ),
            STATUS_AMBIGUOUS: "Several works fit: the user must choose.",
        }[status]
        metadata: dict[str, Any] = {
            "status": status,
            "candidates": [_model_view(row) for row in found.candidates],
            "excluded_unreleased": found.excluded_unreleased,
        }
        if found.omitted:
            metadata["omitted_candidates"] = found.omitted  # found but not listed: the list shown is partial
        if found.incomplete:
            metadata["incomplete"] = True  # the list searched was cut: there may be more than the ones found
        result: dict[str, Any] = {
            "query": request.query,
            "chunks": [],
            "outcome": tool_outcome(OUTCOME_EMPTY, status),
            "metadata": {"wikidata": metadata},
            "trace": build_wikidata_trace(
                calls,
                status=status,
                reason=status,
                operation=request.operation,
                candidates=found.candidates,
                candidates_omitted=found.omitted,
                incomplete=found.incomplete,
            ),
        }
        if reasons:
            result[RESULT_FOLLOW_UP] = _follow_up(
                reasons, summary + " tmdb_search can look the title up by its localized name."
            )
        return result

    def _resolved(self, request: WikidataToolInput, calls: list[dict[str, str]], work: dict[str, Any]) -> dict[str, Any]:
        return {
            "query": request.query,
            "chunks": [],
            "outcome": tool_outcome(OUTCOME_OK),
            "metadata": {"wikidata": {"status": STATUS_OK, "operation": request.operation, "work": _model_view(work)}},
            "trace": build_wikidata_trace(calls, status=STATUS_OK, operation=request.operation, work=work),
        }

    def _related(
        self,
        request: WikidataToolInput,
        calls: list[dict[str, str]],
        work: dict[str, Any],
        related: dict[str, Any],
        franchises: list[dict[str, Any]],
        unavailable: dict[str, str],
        partial: bool,
    ) -> dict[str, Any]:
        groups = {name: related[name] for name in ("sources", "derived", "previous", "next")}
        empty = not any(groups.values()) and not any(row["members"] for row in franchises)
        data: dict[str, Any] = {
            "status": STATUS_NO_RELATIONS if empty else STATUS_OK,
            "operation": request.operation,
            "work": _model_view(work),
            "based_on": [_model_view(row) for row in groups["sources"]],
            "based_on_this": [_model_view(row) for row in groups["derived"]],
            "previous_in_series": [_model_view(row) for row in groups["previous"]],
            "next_in_series": [_model_view(row) for row in groups["next"]],
            "franchises": [
                {"title": row["title"], "works": [_model_view(m) for m in row["members"]], "omitted": row["omitted"]}
                for row in franchises
            ],
            "excluded_unreleased": related["excluded_unreleased"] + sum(row["excluded_unreleased"] for row in franchises),
            "note": _NOTE,
        }
        if related["omitted"]:
            data["omitted"] = related["omitted"]
        if partial:
            # The query hit its row limit: the franchise has more works than the ones listed.
            data["franchise_list_partial"] = True
        if unavailable:
            data["unavailable"] = unavailable
        result: dict[str, Any] = {
            "query": request.query,
            "chunks": [],
            "outcome": tool_outcome(OUTCOME_EMPTY, STATUS_NO_RELATIONS) if empty else tool_outcome(OUTCOME_OK),
            "metadata": {"wikidata": data},
            "trace": build_wikidata_trace(
                calls,
                status=STATUS_NO_RELATIONS if empty else STATUS_OK,
                reason=STATUS_NO_RELATIONS if empty else None,
                operation=request.operation,
                work=work,
                relations=groups,
                franchises=franchises,
                unavailable=unavailable,
            ),
        }
        if empty:
            result[RESULT_FOLLOW_UP] = _follow_up(
                [STATUS_NO_RELATIONS],
                "Wikidata records no relation for this work (that does not prove there are none). "
                "wikipedia_search can describe adaptations, remakes or franchise in prose.",
            )
        elif unavailable:
            result[RESULT_FOLLOW_UP] = _follow_up(
                sorted(set(unavailable.values())),
                "Part of the franchise could not be read ("
                + ", ".join(f"{part} ({code})" for part, code in sorted(unavailable.items()))
                + "). wikipedia_search can describe the rest if the request needs it.",
            )
        return result
