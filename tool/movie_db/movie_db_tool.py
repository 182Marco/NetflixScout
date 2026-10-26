from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from movie_db.config import MovieDbConfig
from turn import OUTCOME_EMPTY, OUTCOME_ERROR, OUTCOME_OK, tool_outcome

from .models import ExecutedQuery, MovieDbOperation, MovieDbQuery, MovieDbToolInput
from .parser import MovieDbParseError, parse_query
from .results import row_to_chunk
from .sql.connection import readonly_connection
from .sql.repository import effective_limit, run_query
from .trace import build_db_query_trace
from .work_type import WORK_MOVIE, WorkTypeChecker, filter_series

MOVIE_DB_TOOL_NAME = "movie_db_search"

# MovieLens has no work type: TV series and miniseries (e.g. "Planet Earth II") are in the
# catalog, and `links.tmdb_id` always points at TMDb's movie namespace, so no reliable
# filter exists. Movie rows carry this flag instead, and the final answer must not call
# them verified films.
WORK_TYPE_UNVERIFIED = {
    "work_type_verified": False,
    "work_type_note": "MovieLens non distingue film e serie TV: un titolo può essere una serie o una miniserie.",
}

# Rankings list films, so series are filtered out of them when a checker is available.
RANKING_OPERATIONS = frozenset(
    {MovieDbOperation.top_rated, MovieDbOperation.most_rated, MovieDbOperation.by_genre_year}
)
# Candidates read per row requested (clamped to `max_limit`): room for the series dropped.
RANKING_FETCH_FACTOR = 3

SERIES_EXCLUDED_NOTE = (
    "Il tipo è stato verificato su TMDb dove possibile e le serie TV riconosciute sono escluse; "
    "i titoli con work_type \"unverified\" non sono verificabili e potrebbero essere serie."
)


@dataclass(kw_only=True)
class MovieDbTool:
    """Read-only MovieLens tool: rankings, ratings, genres by year and user tags."""

    name: str = MOVIE_DB_TOOL_NAME
    description: str = (
        "Query the local MovieLens database for ratings, number of ratings, rankings, "
        "movies by genre and year and user tags. Read-only; returns structured rows."
    )
    input_schema: dict[str, Any] = field(
        default_factory=lambda: MovieDbToolInput.model_json_schema()
    )
    config: MovieDbConfig
    # OpenAI-compatible client for the parser; created on first use.
    client: Any = None
    # Tells films from series for the rankings (TMDb, injected by `app.py`); None = no filtering.
    work_type_checker: WorkTypeChecker | None = None

    def _client(self) -> Any:
        if self.client is None:
            from openai import OpenAI

            self.client = OpenAI()
        return self.client

    def _result(
        self,
        query: str,
        *,
        parsed: MovieDbQuery | None,
        executed: list[ExecutedQuery],
        rows: list[dict[str, Any]],
        error: str | None = None,
        error_kind: str | None = None,
        excluded_series: int | None = None,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "operation": parsed.operation.value if parsed else None,
            "row_count": len(rows),
        }
        if any("movie_id" in row for row in rows):
            metadata.update(WORK_TYPE_UNVERIFIED)
            if excluded_series is not None:
                metadata["excluded_series"] = excluded_series
                if all(row.get("work_type") == WORK_MOVIE for row in rows):
                    metadata = {**metadata, "work_type_verified": True}
                    metadata.pop("work_type_note")
                else:
                    metadata["work_type_note"] = SERIES_EXCLUDED_NOTE
        if error:
            metadata["error"] = error
        if error_kind:
            metadata["error_kind"] = error_kind
        if error or error_kind:
            outcome = tool_outcome(OUTCOME_ERROR, error_kind or "error")
        else:
            outcome = tool_outcome(OUTCOME_OK if rows else OUTCOME_EMPTY)
        return {
            "query": query,
            "chunks": [row_to_chunk(row) for row in rows],
            "outcome": outcome,
            "metadata": metadata,
            # Outside "metadata": the orchestrator puts metadata in the LLM prompt.
            "trace": build_db_query_trace(executed),
        }

    def run(
        self,
        *,
        query: str,
        params: dict[str, Any] | None = None,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        arguments = dict(params or {})
        if query:
            arguments["query"] = query
        payload = MovieDbToolInput(**arguments)

        try:
            parsed = parse_query(payload.query, self.config.parser, self._client())
        except MovieDbParseError as exc:
            return self._result(
                payload.query, parsed=None, executed=[], rows=[], error=str(exc), error_kind=exc.kind
            )

        try:
            with readonly_connection(self.config.db_path, timeout_ms=self.config.query.timeout_ms) as conn:
                ranking = parsed.operation in RANKING_OPERATIONS
                limit = effective_limit(parsed, self.config.query)
                executed, rows = run_query(
                    conn,
                    parsed,
                    self.config.query,
                    fetch_limit=limit * RANKING_FETCH_FACTOR if ranking and self.work_type_checker else None,
                )
                excluded = None
                if ranking and self.work_type_checker:
                    rows, excluded = filter_series(rows, limit=limit, checker=self.work_type_checker)
        except (sqlite3.Error, FileNotFoundError) as exc:
            return self._result(payload.query, parsed=parsed, executed=[], rows=[], error=str(exc))

        return self._result(
            payload.query, parsed=parsed, executed=executed, rows=rows, excluded_series=excluded
        )
