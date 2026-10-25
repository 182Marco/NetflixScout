"""Read-only connections to the movie DB."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from movie_db import schema
from movie_db.config import MovieDbConfig

from .guard import install_guard

BUILD_HINT = "Run `python buildMovieDb.py` (see README) before querying."


def open_readonly(path: str | Path, *, timeout_ms: int) -> sqlite3.Connection:
    """Open `path` read-only: `mode=ro` URI, `PRAGMA query_only` and the authorizer guard.

    The file is never created: `mode=ro` fails if it is missing.
    """
    db_file = Path(path)
    if not db_file.is_file():
        raise FileNotFoundError(f"Movie DB not found. {BUILD_HINT}")
    conn = sqlite3.connect(f"{db_file.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    # Before the guard: the authorizer denies every PRAGMA.
    conn.execute("PRAGMA query_only = ON")
    install_guard(conn, timeout_ms=timeout_ms)
    return conn


@contextmanager
def readonly_connection(path: str | Path, *, timeout_ms: int) -> Iterator[sqlite3.Connection]:
    """One connection per call, always closed: nothing is shared between tool runs."""
    conn = open_readonly(path, timeout_ms=timeout_ms)
    try:
        yield conn
    finally:
        conn.close()


def ensure_db_ready(config: MovieDbConfig) -> None:
    with readonly_connection(config.db_path, timeout_ms=config.query.timeout_ms) as conn:
        try:
            count = conn.execute(f"SELECT count(*) FROM {schema.MOVIES}").fetchone()[0]
        except sqlite3.DatabaseError as exc:
            raise RuntimeError(f"Movie DB is not valid ({exc}). {BUILD_HINT}") from exc
    if count == 0:
        raise RuntimeError(f"Movie DB is empty. {BUILD_HINT}")
