"""Runs a ValidatedQuery on a GuardedConnection with a deadline, row and size caps and a plan check."""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from typing import Any

from .connection import GuardedConnection
from .errors import SqlExecutionFailed, SqlPlanRejected, SqlTimeout
from .policy import Policy
from .validator import ValidatedQuery


@dataclass(frozen=True)
class QueryResult:
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    truncated: bool
    truncated_reason: str | None  # "rows" | "size" | None
    elapsed_ms: int
    sql: str
    params: tuple[Any, ...]
    views: tuple[str, ...]


def execute(guarded: GuardedConnection, query: ValidatedQuery) -> QueryResult:
    policy, conn = guarded.policy, guarded.conn
    limits = policy.limits
    started = time.monotonic()
    timer = guarded.arm(limits.timeout_ms)
    try:
        if policy.large_tables:
            _check_plan(conn, query, policy)
        cursor = conn.execute(query.sql, query.params)
        fetched = cursor.fetchmany(query.limit + 1)
        columns = tuple(d[0] for d in cursor.description or ())
    except sqlite3.OperationalError as exc:
        if "interrupt" in str(exc).lower():
            raise SqlTimeout(f"The query exceeded {limits.timeout_ms} ms.") from None
        raise SqlExecutionFailed("The database refused the query.") from None
    except sqlite3.DatabaseError:
        # Includes authorizer denials ("not authorized"): the engine's text is never shown.
        raise SqlExecutionFailed("The database refused the query.") from None
    finally:
        timer.cancel()
        guarded.disarm()
    if conn.total_changes != 0:  # cannot happen on a read-only connection; asserted as a last line of defence
        raise SqlExecutionFailed("The connection reported a change.")
    truncated, reason = len(fetched) > query.limit, "rows" if len(fetched) > query.limit else None
    rows, size = [], 0
    for row in fetched[: query.limit]:
        clipped = tuple(_clip(v, limits.max_cell_chars) for v in row)
        size += sum(len(str(v)) for v in clipped)
        if size > limits.max_result_chars:
            truncated, reason = True, "size"
            break
        rows.append(clipped)
    return QueryResult(columns, tuple(rows), truncated, reason, int((time.monotonic() - started) * 1000),
                       query.sql, query.params, query.views)


def _clip(value: Any, max_chars: int) -> Any:
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    if isinstance(value, str) and len(value) > max_chars:
        return value[:max_chars] + "…"
    return value


def _check_plan(conn: sqlite3.Connection, query: ValidatedQuery, policy: Policy) -> None:
    """Refuse a full SCAN of a large base table when the result needs a sort or grouping (the whole table would be
    read) . A bounded, ordered-by-index scan with LIMIT is fine. Plans use base-table names, never the views'."""
    try:
        plan = [str(r[3]) for r in conn.execute("EXPLAIN QUERY PLAN " + query.sql, query.params).fetchall()]
    except sqlite3.DatabaseError:
        raise SqlExecutionFailed("The database refused the query.") from None
    heavy = any("TEMP B-TREE" in line or "USE TEMP" in line for line in plan)
    for line in plan:
        parts = line.split()
        if parts and parts[0] == "SCAN":
            table = parts[1].casefold() if len(parts) > 1 else ""
            if table in {t.casefold() for t in policy.large_tables} and heavy:
                raise SqlPlanRejected("The query would scan a large table to sort or group it; add a selective filter.")
