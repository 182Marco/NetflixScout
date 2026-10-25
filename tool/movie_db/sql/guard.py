"""SQLite authorizer and progress handler that make a connection read-only and bounded.

The authorizer runs inside SQLite for every statement, whatever its text: anything
that is not a SELECT reading the known tables with whitelisted functions is denied.
"""
from __future__ import annotations

import sqlite3
import time

from movie_db import schema

ALLOWED_FUNCTIONS = frozenset(
    {"avg", "coalesce", "count", "group_concat", "like", "max", "min", "round", "sum"}
)
ALLOWED_TABLES = frozenset(schema.TABLES)

# VM instructions between two progress-handler calls.
_PROGRESS_STEP = 1000


def read_only_authorizer(
    action: int,
    arg1: str | None,
    arg2: str | None,
    db_name: str | None,
    trigger: str | None,
) -> int:
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ and arg1 in ALLOWED_TABLES:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() in ALLOWED_FUNCTIONS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def install_guard(conn: sqlite3.Connection, *, timeout_ms: int) -> None:
    """Deny every non-read statement and interrupt the connection after `timeout_ms`."""
    deadline = time.monotonic() + timeout_ms / 1000

    def _past_deadline() -> int:
        return 1 if time.monotonic() > deadline else 0

    conn.set_authorizer(read_only_authorizer)
    conn.set_progress_handler(_past_deadline, _PROGRESS_STEP)
