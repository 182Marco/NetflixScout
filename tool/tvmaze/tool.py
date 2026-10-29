from __future__ import annotations

from dataclasses import dataclass, field
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

from .config import TvmazeConfig
from .errors import TvmazeError
from .http import get_json, urllib_transport
from .identify import IDENTIFIED, NOT_FOUND, UNVERIFIED, identify
from .models import TvmazeToolInput, describe_validation_errors
from .normalize import (
    cast_rows,
    episode_rows,
    next_episode_row,
    season_rows,
    show_info,
    show_url,
)
from .queries import episodes_request, search_request, seasons_request, show_request
from .session import PROCESS_PAUSE, HttpSession, RateLimitPause, Transport, TurnSessions
from .trace import build_tvmaze_trace

TVMAZE_TOOL_NAME = "tvmaze_search"

_DESCRIPTION = (
    "Structured data of ONE identified TV series from TVmaze: status (running or ended), network or "
    "web channel, premiere and end dates, runtime, language, genres, a short summary (info); cast "
    "with character names (cast); seasons with episode counts and dates (seasons); the episodes of "
    "one season with numbering and air dates (episodes); the upcoming episode (next). Identify the "
    "series with `title` (and `year` only when the request or the conversation states it); an "
    "ambiguous or unverified title returns the alternatives instead of data. A field TVmaze lacks "
    "is reported as missing, never estimated. Not for recommendations or lists of series, where to "
    "watch, trailers, reviews or scores, creators, films, or in-depth plot and production history."
)

STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_UNVERIFIED = "unverified"
STATUS_NOT_FOUND = "not_found"

# Errors after which another source (tmdb_search) can still answer: the planner is offered a next step.
RECOVERABLE_ERRORS = {"rate_limited", "timeout", "network_error", "http_error", "response_too_large"}


def planner_schema() -> dict[str, Any]:
    """`TvmazeToolInput` JSON schema for the planner catalog, without the class docstring: the
    tool `description` already says what the tool does. Validation uses the model, not this dict."""
    schema = TvmazeToolInput.model_json_schema()
    schema.pop("description", None)
    return schema


def _follow_up(reasons: list[str], summary: str) -> dict[str, Any]:
    return {"available": bool(reasons), "reasons": reasons, "summary": summary}


def _trace_show(info: dict[str, Any] | None, url: str | None) -> dict[str, Any] | None:
    if not info:
        return None
    return {
        "name": info["name"],
        "url": url,
        "status": info["status"],
        "premiered": info["premiered"],
        "network": info["network"] or info["web_channel"],
    }


def _failure(query: str, error: str, *, calls: list[dict[str, str]] | None = None, **details: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "query": query,
        "chunks": [],
        "outcome": tool_outcome(OUTCOME_ERROR, error),
        "metadata": {"tvmaze": {"status": STATUS_ERROR, "error": error, **details}},
        # No step when nothing was called.
        "trace": build_tvmaze_trace(calls, status=STATUS_ERROR, reason=error) if calls else [],
    }
    if error in RECOVERABLE_ERRORS:
        result[RESULT_FOLLOW_UP] = _follow_up(
            [error],
            f"TVmaze could not be read ({error}). tmdb_search (tv_details, tv_season, tv_episode) can "
            "answer series data if the request allows it; otherwise say what is missing.",
        )
    return result


@dataclass(kw_only=True)
class TvmazeTool:
    """Read-only TVmaze tool: typed input, constant requests, data of a series identified by title.

    No cache: a session (budget and memo) lives only for the turn it belongs to.
    """

    config: TvmazeConfig
    name: str = TVMAZE_TOOL_NAME
    description: str = _DESCRIPTION
    input_schema: dict[str, Any] = field(default_factory=planner_schema)
    transport: Transport = urllib_transport
    # Shared by the whole process by default (the limit is per IP); injected in tests.
    pause: RateLimitPause = field(default_factory=lambda: PROCESS_PAUSE)
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
            request = TvmazeToolInput.model_validate(arguments)
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
        except TvmazeError as exc:
            return _failure(request.query, exc.code, calls=session.calls[first_call:])

    def _lookup(self, request: TvmazeToolInput, session: HttpSession, first_call: int) -> dict[str, Any]:
        def calls() -> list[dict[str, str]]:
            return session.calls[first_call:]

        found = identify(get_json(session, search_request(request.title)), title=request.title, year=request.year)
        if found.status != IDENTIFIED or found.show is None:
            status = {NOT_FOUND: STATUS_NOT_FOUND, UNVERIFIED: STATUS_UNVERIFIED}.get(found.status, STATUS_AMBIGUOUS)
            return self._not_identified(request, calls(), status, found.candidates)

        show = found.show
        facets = request.facets
        unavailable: dict[str, str] = {}
        embedded: dict[str, Any] = {}
        if "cast" in facets or "next" in facets:
            try:
                card = get_json(session, show_request(show["id"], cast="cast" in facets, next_episode="next" in facets))
            except TvmazeError as exc:
                for facet in ("cast", "next"):
                    if facet in facets:
                        unavailable[facet] = exc.code
            else:
                if isinstance(card, dict):
                    show = card
                    embedded = card.get("_embedded") if isinstance(card.get("_embedded"), dict) else {}
                else:
                    for facet in ("cast", "next"):
                        if facet in facets:
                            unavailable[facet] = "not_found"

        info = show_info(show)
        data: dict[str, Any] = {"status": STATUS_OK, "show": info}
        if "cast" in facets and "cast" not in unavailable:
            data["cast"] = cast_rows(embedded.get("cast"))
        if "next" in facets and "next" not in unavailable:
            data["next_episode"] = next_episode_row(embedded.get("nextepisode"))
            if data["next_episode"] is None:
                data["next_episode_note"] = "TVmaze lists no upcoming episode."
        if "seasons" in facets:
            self._section(data, unavailable, "seasons", session, seasons_request(show["id"]), season_rows)
        if "episodes" in facets and request.season is not None:
            self._section(
                data,
                unavailable,
                "episodes",
                session,
                episodes_request(show["id"]),
                lambda payload: self._episodes(payload, request),
            )
        if unavailable:
            data["unavailable"] = unavailable
        return self._result(request, calls(), data, show=show, unavailable=unavailable)

    @staticmethod
    def _episodes(payload: Any, request: TvmazeToolInput) -> dict[str, Any]:
        assert request.season is not None  # guaranteed by the model
        rows, total = episode_rows(payload, season=request.season, episode=request.episode)
        return {"season": request.season, "total_in_season": total, "episodes": rows}

    @staticmethod
    def _section(data: dict[str, Any], unavailable: dict[str, str], key: str, session: HttpSession, request, build) -> None:
        try:
            payload = get_json(session, request)
        except TvmazeError as exc:
            unavailable[key] = exc.code
            return
        if payload is None:
            unavailable[key] = "not_found"
            return
        data[key] = build(payload)

    def _not_identified(
        self, request: TvmazeToolInput, calls: list[dict[str, str]], status: str, candidates: list[dict[str, str]]
    ) -> dict[str, Any]:
        reasons = [status] if status in (STATUS_NOT_FOUND, STATUS_UNVERIFIED) else []
        summary = {
            STATUS_NOT_FOUND: "TVmaze has no series with this title (it knows mostly original or English titles).",
            STATUS_UNVERIFIED: "TVmaze has only series that resemble the title, none is certainly the one asked.",
            STATUS_AMBIGUOUS: "Several TVmaze series fit the title: the user must choose.",
        }[status]
        result: dict[str, Any] = {
            "query": request.query,
            "chunks": [],
            "outcome": tool_outcome(OUTCOME_EMPTY, status),
            "metadata": {"tvmaze": {"status": status, "candidates": candidates}},
            "trace": build_tvmaze_trace(calls, status=status, reason=status, facets=request.facets, candidates=candidates),
        }
        if reasons:
            result[RESULT_FOLLOW_UP] = _follow_up(
                reasons, summary + " tmdb_search (tv_details) can look the series up by its localized title."
            )
        return result

    def _result(
        self,
        request: TvmazeToolInput,
        calls: list[dict[str, str]],
        data: dict[str, Any],
        *,
        show: dict[str, Any],
        unavailable: dict[str, str],
    ) -> dict[str, Any]:
        info = data["show"]
        result: dict[str, Any] = {
            "query": request.query,
            "chunks": [],
            "outcome": tool_outcome(OUTCOME_OK),
            # Everything the model reads is in metadata; URLs and the licence are in the trace.
            "metadata": {"tvmaze": data},
            "trace": build_tvmaze_trace(
                calls,
                status=STATUS_OK,
                show=_trace_show(info, show_url(show)),
                facets=request.facets,
            ),
        }
        if unavailable:
            result[RESULT_FOLLOW_UP] = _follow_up(
                sorted(set(unavailable.values())),
                "Some TVmaze data could not be read: "
                + ", ".join(f"{facet} ({code})" for facet, code in sorted(unavailable.items()))
                + ". tmdb_search can answer series data if the request allows it.",
            )
        return result
