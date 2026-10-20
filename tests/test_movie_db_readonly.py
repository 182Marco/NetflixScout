from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from movie_db.tool.sql.connection import ensure_db_ready, open_readonly, readonly_connection
from movie_db.tool.sql.guard import install_guard

WRITE_ATTEMPTS = [
    "INSERT INTO movies (movie_id, title, clean_title) VALUES (999, 'x', 'x')",
    "UPDATE movie_stats SET avg_rating = 5",
    "DELETE FROM ratings",
    "DROP TABLE movies",
    "CREATE TABLE evil (a)",
    "CREATE TEMP TABLE evil (a)",
    "ALTER TABLE movies ADD COLUMN evil TEXT",
    "CREATE INDEX evil ON movies(title)",
    "ATTACH DATABASE 'evil.db' AS evil",
    "PRAGMA query_only = OFF",
    "PRAGMA writable_schema = ON",
    "VACUUM INTO 'copy.db'",
    "BEGIN",
    "SELECT load_extension('evil')",
    "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT n FROM r",
    "SELECT 1; DROP TABLE movies",
]


def _sha256(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.mark.parametrize("statement", WRITE_ATTEMPTS)
def test_writes_ddl_and_escapes_are_denied(movie_db_config, statement, tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)  # nothing may be created next to the CWD either
    before = _sha256(movie_db_config.db_path)

    with readonly_connection(movie_db_config.db_path, timeout_ms=1000) as conn:
        with pytest.raises((sqlite3.DatabaseError, sqlite3.ProgrammingError, sqlite3.Warning)):
            conn.execute(statement)

    assert _sha256(movie_db_config.db_path) == before
    assert list(tmp_path.iterdir()) == []


def test_reads_of_known_tables_are_allowed(movie_db_config) -> None:
    with readonly_connection(movie_db_config.db_path, timeout_ms=1000) as conn:
        assert conn.execute("SELECT count(*) FROM movies").fetchone()[0] == 10


def test_unknown_tables_cannot_be_read(movie_db_config) -> None:
    with readonly_connection(movie_db_config.db_path, timeout_ms=1000) as conn:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("SELECT * FROM sqlite_master").fetchall()


def test_missing_db_is_not_created_and_error_has_no_path(tmp_path) -> None:
    missing = tmp_path / "missing.sqlite3"

    with pytest.raises(FileNotFoundError) as exc:
        open_readonly(missing, timeout_ms=1000)

    assert "buildMovieDb.py" in str(exc.value)
    assert str(tmp_path) not in str(exc.value)
    assert not missing.exists()


def test_timeout_interrupts_long_queries() -> None:
    conn = sqlite3.connect(":memory:")
    install_guard(conn, timeout_ms=10)
    conn.set_authorizer(None)  # isolate the progress handler: allow the recursive CTE

    with pytest.raises(sqlite3.OperationalError, match="interrupted"):
        conn.execute(
            "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT count(*) FROM r"
        ).fetchone()
    conn.close()


def test_ensure_db_ready_accepts_fixture(movie_db_config) -> None:
    ensure_db_ready(movie_db_config)


def test_ensure_db_ready_rejects_missing_db(movie_db_config, tmp_path) -> None:
    config = movie_db_config.model_copy(update={"db_path": str(tmp_path / "nope.sqlite3")})

    with pytest.raises(FileNotFoundError):
        ensure_db_ready(config)
