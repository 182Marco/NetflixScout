"""The only way to open the cinema database: read-only at every layer, deny-by-default authorizer.

Order matters: PRAGMAs and limits are set BEFORE the final authorizer (which denies every PRAGMA), and the policy
is verified against the real schema with a recording authorizer before the final one is installed.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path

from .errors import DatabaseMissing, PolicyMismatch
from .policy import Policy

_SQLITE_RECURSIVE = getattr(sqlite3, "SQLITE_RECURSIVE", 33)
# VM instructions between two progress-handler calls.
_PROGRESS_STEP = 1000


def make_authorizer(policy: Policy) -> Callable[[int, str | None, str | None, str | None, str | None], int]:
    """Deny by default. Allowed: SELECT; READ of the approved view columns from the top level; READ of the base
    columns that the views declare, and only on behalf of a view; the approved functions."""
    views = {v.name.casefold(): v.column_names for v in policy.views}
    views_cf = {name: {c.casefold() for c in cols} for name, cols in views.items()}
    base = {t.casefold(): {c.casefold() for c in cols} for t, cols in policy.base_columns.items()}
    functions = frozenset(f.casefold() for f in policy.functions) | frozenset(f.casefold() for f in policy.engine_functions)
    engine_tables = frozenset(t.casefold() for t in policy.engine_tables)
    engine_pragmas = frozenset(p.casefold() for p in policy.engine_pragmas)
    engine_columns = frozenset(c.casefold() for c in policy.engine_columns)

    def authorizer(action: int, arg1: str | None, arg2: str | None, db_name: str | None, source: str | None) -> int:
        if action == sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            table, column = (arg1 or "").casefold(), (arg2 or "").casefold()
            if db_name not in (None, "main"):
                return sqlite3.SQLITE_DENY
            if table in engine_tables:  # FTS5 index and its shadow tables: they hold only the text of entity_name
                return sqlite3.SQLITE_OK
            if table in views_cf:
                # `count(*)` reads no column (empty name); a named column must belong to the view.
                return sqlite3.SQLITE_OK if column == "" or column in views_cf[table] else sqlite3.SQLITE_DENY
            if table in base:
                if column == "":  # count(*) over a view: no column is read
                    return sqlite3.SQLITE_OK
                # A base column is readable only for a view and only if the view declares it. A top-level read
                # (`source` None) of a base table, or a column the views do not use, is denied.
                if source is None and f"{table}.{column}" in engine_columns:  # FTS5 content scan: public name text only
                    return sqlite3.SQLITE_OK
                return sqlite3.SQLITE_OK if source is not None and column in base[table] else sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION:
            return sqlite3.SQLITE_OK if (arg2 or "").casefold() in functions else sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_PRAGMA:
            # FTS5 asks for `data_version` itself; no other pragma, and none with an argument.
            return sqlite3.SQLITE_OK if (arg1 or "").casefold() in engine_pragmas and not arg2 else sqlite3.SQLITE_DENY
        # SQLITE_RECURSIVE, INSERT/UPDATE/DELETE, CREATE_*/DROP_*/ALTER_TABLE, PRAGMA, ATTACH/DETACH, TRANSACTION,
        # SAVEPOINT, REINDEX, ANALYZE, CREATE_VTABLE/DROP_VTABLE and every future code.
        return sqlite3.SQLITE_DENY

    return authorizer


class GuardedConnection:
    """A connection that cannot write and stops running after the deadline set by `arm()`."""

    def __init__(self, conn: sqlite3.Connection, policy: Policy) -> None:
        self.conn = conn
        self.policy = policy
        self._deadline = float("inf")
        conn.set_authorizer(make_authorizer(policy))
        conn.set_progress_handler(self._past_deadline, _PROGRESS_STEP)

    def _past_deadline(self) -> int:
        return 1 if time.monotonic() > self._deadline else 0

    def arm(self, timeout_ms: int) -> threading.Timer:
        """Set the deadline of the next statement; the timer interrupts a step that never reaches the handler."""
        self._deadline = time.monotonic() + timeout_ms / 1000
        timer = threading.Timer(timeout_ms / 1000 + 0.25, self.conn.interrupt)
        timer.daemon = True
        timer.start()
        return timer

    def disarm(self) -> None:
        self._deadline = float("inf")

    def close(self) -> None:
        self.conn.close()


def open_database(path: str | Path, policy: Policy, *, immutable: bool = True) -> GuardedConnection:
    """Open `path` read-only. The file is never created. `immutable=True` (default) also tells SQLite the file never
    changes: no journal, no lock, no write path at all; use False only for a database being rebuilt in parallel."""
    db_file = Path(path)
    if not db_file.is_file():
        raise DatabaseMissing("The cinema database was not found.")
    query = "mode=ro" + ("&immutable=1" if immutable else "")
    conn = sqlite3.connect(f"{db_file.resolve().as_uri()}?{query}", uri=True, check_same_thread=True)
    try:
        if hasattr(conn, "enable_load_extension"):
            conn.enable_load_extension(False)
        conn.execute("PRAGMA query_only = ON")
        conn.execute("PRAGMA trusted_schema = OFF")
        conn.execute("PRAGMA temp_store = MEMORY")
        conn.execute("PRAGMA cache_size = -8192")
        _set_limits(conn, policy)
        verify_policy(conn, policy)
        return GuardedConnection(conn, policy)
    except BaseException:
        conn.close()
        raise


def _set_limits(conn: sqlite3.Connection, policy: Policy) -> None:
    lim = policy.limits
    conn.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, lim.max_sql_chars * 4)
    conn.setlimit(sqlite3.SQLITE_LIMIT_COMPOUND_SELECT, lim.max_set_branches + 1)
    conn.setlimit(sqlite3.SQLITE_LIMIT_FUNCTION_ARG, lim.sqlite_function_args)
    conn.setlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH, lim.sqlite_expr_depth)
    conn.setlimit(sqlite3.SQLITE_LIMIT_LIKE_PATTERN_LENGTH, lim.sqlite_like_pattern)
    conn.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, lim.max_params)
    conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, lim.sqlite_value_length)
    conn.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, lim.sqlite_columns)
    conn.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)


def verify_policy(conn: sqlite3.Connection, policy: Policy) -> None:
    """The policy must describe the database exactly: same view columns, and the views read nothing outside
    `base_columns`. A mismatch is a configuration error (fail at start, never at query time)."""
    reads: set[tuple[str, str]] = set()

    def record(action: int, arg1: str | None, arg2: str | None, db_name: str | None, source: str | None) -> int:
        if action == sqlite3.SQLITE_READ and source is not None and (arg1 or "").casefold() not in policy.view_names:
            reads.add(((arg1 or "").casefold(), (arg2 or "").casefold()))
        return sqlite3.SQLITE_OK

    conn.set_authorizer(record)
    try:
        existing = {r[0].casefold() for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'view'")}
        for view in policy.views:
            if view.name.casefold() not in existing:
                raise PolicyMismatch(f"View {view.name} does not exist.")
            actual = [(r[1], (r[2] or "").upper()) for r in conn.execute(f'PRAGMA table_info("{view.name}")')]
            declared = [(c, t.upper()) for c, t in view.columns]
            if [a[0] for a in actual] != [d[0] for d in declared]:
                raise PolicyMismatch(f"Columns of {view.name} differ from the policy.")
            conn.execute(f'SELECT * FROM "{view.name}" LIMIT 0').fetchall()
        allowed = {(t.casefold(), c.casefold()) for t, cols in policy.base_columns.items() for c in cols}
        if (stray := reads - allowed - {(t, "") for t, _ in allowed}):
            raise PolicyMismatch(f"Views read base columns that the policy does not declare: {sorted(stray)}")
        if conn.execute("SELECT count(*) FROM sqlite_master WHERE type = 'trigger'").fetchone()[0]:
            raise PolicyMismatch("The database contains triggers.")
    finally:
        conn.set_authorizer(None)
