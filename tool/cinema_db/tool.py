"""`cinema_sql`: questions about films, series, people, credits, awards, relations, companies and series structure, answered from the LOCAL
read-only cinema database. No network, no LLM, no credentials.

Not wired into the orchestrator yet (`app.py`, the planner rules, the presenters and the user settings are untouched): this module only
satisfies the `Tool` protocol so that wiring it in later is registration, not work.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
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

from .approved_views import POLICY
from .config import CinemaDbConfig
from .connection import open_database
from .constants import DEFAULT_LIMIT, MAX_LIMIT, NOTES
from .errors import CinemaSqlError, DatabaseMissing, SqlRejected
from .models import CinemaSqlInput, describe_validation_errors
from .operations import ERROR, OPERATIONS, OpResult
from .policy import Policy
from .session import Session, TurnBudgets
from .trace import build_trace

CINEMA_SQL_TOOL_NAME = "cinema_sql"
OK_STATUS = "ok"
ROOT = Path(__file__).resolve().parents[2]

# The user setting this tool will serve ("Preferred sources"), to register in `preferences/behavior.py:SOURCE_TOOLS["cinema_sql"]` WHEN the tool is wired (not
# done: the settings are unchanged). Verified on the real data: structured encyclopedic facts (credits, relations, companies, awards, series structure) from
# Wikipedia and Wikidata, like `wikipedia_search` and `tmdb_search`. It carries NO audience rating (that is `user ratings`) and NO critic score or review
# (that is `reviews`: awards are industry recognitions, not reviews), no interview, no plot (so no spoilers) and covers films and series.
SOURCE_CATEGORY = "official information"

# Where a local gap can be looked at once, online (the planner decides; the tool only suggests).
FALLBACKS = {
    "find_work": "tmdb_search", "work_card": "tmdb_search", "cast": "tmdb_search", "crew": "tmdb_search", "find_person": "tmdb_search",
    "filmography": "tmdb_search", "collaborations": "tmdb_search", "awards": "wikipedia_search", "series": "tvmaze_search",
    "companies": "tmdb_search", "franchise": "wikidata_search", "relations": "wikidata_search", "sql": "tmdb_search",
}

FINAL_INSTRUCTIONS = (
    "Se il tool usato è cinema_sql, riporta titoli, anni, ruoli, premi e relazioni esattamente come stanno nei metadata, senza nominare la "
    "provenienza dei dati e senza codici tecnici (id interni, IMDb, TMDb, Wikidata) a meno che l'utente li chieda. I dati sono quelli di un "
    "catalogo locale incompleto, soprattutto per le opere dopo il 2019: ciò che non compare non prova che non esista, quindi di' «tra quelli "
    "registrati» o simili e non presentare un elenco come completo. Se total è maggiore di shown (o truncated è vero) di' che mostri solo una "
    "parte e quanti ce ne sono in tutto. Leggi le note in notes e rispettale (per esempio il cast non ha un ordine di rilievo; «basato su» "
    "comprende remake, adattamenti e opere solo ispirate; «segue» è l'ordine in una serie, non dice se è un sequel o un prequel; gli importi "
    "restano nella valuta indicata, mai convertiti). Se status è ambiguous elenca le alternative (titolo o nome, anno, regista o ruoli) e "
    "chiedi quale intende, dicendo quante non hai elencato se omitted_candidates è maggiore di zero; se è unverified, sono solo nomi simili, non la "
    "risposta: dillo senza scegliere; se è not_found o empty dillo senza inventare e senza dedurre che l'opera, la persona o il dato non esistano. "
    "I conteggi di episodi per stagione non sono affidabili: riporta le cifre come registrate (episodes e numbered_episodes), dicendo che il numero "
    "reale può differire, e non dichiararle certe. Non aggiungere opere, persone o premi che non compaiono nei dati."
)


def views_summary(policy: Policy = POLICY) -> str:
    """The approved views and their columns, from the policy (the one source of truth), for `operation: sql`."""
    return "; ".join(f"{v.name}({', '.join(c for c, _ in v.columns)})" for v in policy.views if v.name not in {"v_source", "v_role_type", "v_genre_label", "v_work_genre_label"})


_DESCRIPTION = (
    "Answer from the LOCAL cinema database (films, series, seasons, episodes, people, credits, awards, relations, companies, franchises; no "
    "scores, plots, streaming or recent releases). Pick an `operation` and identify things by name or, better, by the ids an earlier step "
    "returned (work_id, person_id, imdb_id, wikidata_id): no new search is made when an id is given. Ambiguous or similar names return "
    "alternatives, not data. The catalogue is incomplete (recent works especially): an empty result does not prove absence. "
    "operation=sql runs ONE SELECT with ? placeholders and a LIMIT on these views only: " + views_summary()
)


def planner_schema() -> dict[str, Any]:
    """`CinemaSqlInput` JSON schema for the planner, compacted (no field titles, no `anyOf null`, no null defaults): validation uses the model."""
    schema = CinemaSqlInput.model_json_schema()
    schema.pop("description", None)
    schema.pop("title", None)
    props = {}
    for name, prop in schema["properties"].items():
        drop = {"title", "minimum", "maximum", "minLength", "maxLength", "maxItems", "exclusiveMinimum"}  # the model validates these; the planner need not read them
        prop = {k: v for k, v in prop.items() if k not in drop and (k != "default" or v is not None)}
        if "anyOf" in prop:
            options = [o for o in prop["anyOf"] if o != {"type": "null"}]
            prop.pop("anyOf")
            if len(options) == 1:
                prop.update(options[0])
        props[name] = prop
    schema["properties"] = props
    return _without_titles(schema)


def _without_titles(node: Any) -> Any:
    """Drop the `title` ANNOTATIONS (a string) at every depth; a property that is itself called `title` (a dict) stays."""
    if isinstance(node, dict):
        return {k: _without_titles(v) for k, v in node.items() if not (k == "title" and isinstance(v, str))}
    if isinstance(node, list):
        return [_without_titles(v) for v in node]
    return node


def _public(entity: dict[str, Any] | None) -> dict[str, Any] | None:
    """What the model sees of an entity: without the Wikipedia page title (it is for the link the interface shows, not for the answer)."""
    return {k: v for k, v in entity.items() if k != "wikipedia_it"} if entity else entity


def _note_list(codes: list[str]) -> list[dict[str, str]]:
    seen: list[str] = []
    for c in codes:
        if c in NOTES and c not in seen:
            seen.append(c)
    return [{"code": c, "text": NOTES[c]} for c in seen]


def _summary(operation: str, status: str, reason: str | None) -> str:
    return (f"cinema_sql {operation}: {status}" + (f" ({reason})" if reason else "") + ". The local catalogue is incomplete, so this does not prove "
            f"the entity or the data do not exist; one step to {FALLBACKS.get(operation, 'tmdb_search')} can check.")


def _failure(query: str, error: str, *, operation: str | None = None, calls: list[dict[str, Any]] | None = None, **details: Any) -> dict[str, Any]:
    result = {
        "query": query,
        "chunks": [],
        "outcome": tool_outcome(OUTCOME_ERROR, error),
        "metadata": {"cinema_db": {"status": "error", "error": error, **details}},
        "trace": build_trace(operation=operation or "unknown", status="error", reason=error, calls=calls or [], subject=None, rows=None),
    }
    if error in {"db_missing", "policy_mismatch"}:  # the local tool cannot work at all: an online tool can still answer
        result[RESULT_FOLLOW_UP] = {"available": True, "reasons": [error], "summary": _summary(operation or "unknown", "error", error)}
    return result


@dataclass(kw_only=True)
class CinemaSqlTool:
    """Read-only local cinema database tool. A connection lives only for one run (it is opened read-only and immutable, ~10 ms), so threads never share one."""

    config: CinemaDbConfig
    policy: Policy = POLICY
    name: str = CINEMA_SQL_TOOL_NAME
    description: str = _DESCRIPTION
    input_schema: dict[str, Any] = field(default_factory=planner_schema)
    _budgets: TurnBudgets = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._budgets = TurnBudgets(self.config.max_queries_per_turn)

    @property
    def db_path(self) -> Path:
        path = Path(self.config.db_path)
        return path if path.is_absolute() else ROOT / path

    def run(
        self,
        *,
        query: str,
        params: dict[str, Any] | None = None,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        arguments = dict(params or {})
        arguments.pop(TOOL_PARAM_TURN_LANGUAGE, None)  # ids and names do not depend on the language of the turn
        turn_id = arguments.pop(TOOL_PARAM_TURN_ID, None)
        if query:
            arguments["query"] = query
        try:
            request = CinemaSqlInput.model_validate(arguments)
        except ValidationError as exc:
            return _failure(query, "invalid_request", errors=describe_validation_errors(exc))
        limit = min(request.limit or self.config.default_limit, MAX_LIMIT)
        try:
            guarded = open_database(self.db_path, self.policy)
        except CinemaSqlError as exc:
            return _failure(request.query, exc.code, operation=request.operation)
        session = Session(guarded, self._budgets.for_turn(turn_id))
        try:
            outcome = OPERATIONS[request.operation](request, session, limit)
        except SqlRejected as exc:  # the rule that failed, never the SQL: the planner may fix it once
            return _failure(request.query, f"rejected:{exc.code}", operation=request.operation, calls=session.calls, message=str(exc))
        except CinemaSqlError as exc:
            return _failure(request.query, exc.code, operation=request.operation, calls=session.calls)
        finally:
            session.close()
        return self._result(request, outcome, session.calls)

    def _result(self, request: CinemaSqlInput, op: OpResult, calls: list[dict[str, Any]]) -> dict[str, Any]:
        if op.status == ERROR:
            return _failure(request.query, op.reason or "error", operation=request.operation, calls=calls)
        body: dict[str, Any] = {"status": op.status, "operation": request.operation, "queries": len(calls)}
        if op.reason:
            body["reason"] = op.reason
        if op.subject:
            body["subject"] = _public(op.subject)
        if op.candidates:
            body["candidates"] = [_public(c) for c in op.candidates]
            body["omitted_candidates"] = op.omitted
        if op.data:
            body.update(op.data)
        if op.total is not None:
            body["total"] = op.total
        if op.status == OK_STATUS and (op.total is not None or op.shown or op.truncated):  # identification returns no list
            body["shown"] = op.shown
            body["truncated"] = op.truncated
        body["notes"] = _note_list(op.notes)
        result: dict[str, Any] = {
            "query": request.query,
            "chunks": [],
            "outcome": tool_outcome(OUTCOME_OK) if op.status == OK_STATUS else tool_outcome(OUTCOME_EMPTY, op.reason or op.status),
            "metadata": {"cinema_db": body},
            "trace": build_trace(operation=request.operation, status=op.status, reason=op.reason, calls=calls, subject=op.subject, rows=op.shown if op.status == OK_STATUS else 0,
                                 candidates=op.candidates, omitted=op.omitted, total=op.total, truncated=op.truncated, notes=[n["code"] for n in body["notes"]]),
        }
        if op.status in {"empty", "not_found", "unverified"}:  # an ambiguous request is for the user to settle, not for another tool
            result[RESULT_FOLLOW_UP] = {"available": True, "reasons": [op.reason or op.status], "summary": _summary(request.operation, op.status, op.reason)}
        return result

