"""Fixture database and policy for the cinema SQL guard tests. Invented data; nothing here touches a real database.

Base tables hold columns the views do NOT expose (`secret_note`, `private`, `internal_flag`): they must stay unreadable.
"""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from pathlib import Path

from tool.cinema_db.connection import GuardedConnection, open_database
from tool.cinema_db.policy import Policy, ViewSpec
from tool.cinema_db.settings import QueryLimits

SCHEMA = """
CREATE TABLE film (id INTEGER PRIMARY KEY, title TEXT NOT NULL, year INTEGER, secret_note TEXT);
CREATE TABLE person (id INTEGER PRIMARY KEY, name TEXT NOT NULL, private TEXT);
CREATE TABLE credit (film_id INTEGER NOT NULL REFERENCES film(id), person_id INTEGER NOT NULL REFERENCES person(id),
                     role TEXT NOT NULL, internal_flag INTEGER);
CREATE INDEX credit_film ON credit(film_id);
CREATE TABLE hidden (x TEXT);
CREATE VIEW v_film AS SELECT id, title, year FROM film;
CREATE VIEW v_person AS SELECT id, name FROM person;
CREATE VIEW v_credit AS SELECT film_id, person_id, role FROM credit;
"""

POLICY = Policy(
    views=(
        ViewSpec("v_film", (("id", "INTEGER"), ("title", "TEXT"), ("year", "INTEGER"))),
        ViewSpec("v_person", (("id", "INTEGER"), ("name", "TEXT"))),
        ViewSpec("v_credit", (("film_id", "INTEGER"), ("person_id", "INTEGER"), ("role", "TEXT"))),
    ),
    base_columns={
        "film": frozenset({"id", "title", "year"}),
        "person": frozenset({"id", "name"}),
        "credit": frozenset({"film_id", "person_id", "role"}),
    },
    large_tables=frozenset({"credit"}),
)


def build_db(path: Path, *, extra_credits: int = 0, trigger: bool = False) -> Path:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.executemany("INSERT INTO film VALUES (?,?,?,?)", [(1, "Sample One", 1982, "S1"), (2, "Sample Two", 2004, "S2"), (3, "Other", 2004, "S3")])
    conn.executemany("INSERT INTO person VALUES (?,?,?)", [(1, "Ann Director", "P1"), (2, "Bob Actor", "P2")])
    conn.executemany("INSERT INTO credit VALUES (?,?,?,?)", [(1, 1, "director", 1), (1, 2, "cast", 0), (2, 1, "director", 0)])
    conn.executemany("INSERT INTO credit VALUES (?,?,?,?)", [(1 + i % 3, 1 + i % 2, "cast", 0) for i in range(extra_credits)])
    conn.execute("INSERT INTO hidden VALUES ('TOP-SECRET')")
    if trigger:
        conn.execute("CREATE TRIGGER t AFTER INSERT ON film BEGIN UPDATE film SET year = 0; END")
    conn.commit()
    conn.close()
    return path


def open_fixture(path: Path, policy: Policy = POLICY, **kw) -> GuardedConnection:
    return open_database(path, policy, **kw)


def with_limits(policy: Policy, **changes) -> Policy:
    return replace(policy, limits=replace(policy.limits, **changes))


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = ["POLICY", "QueryLimits", "build_db", "open_fixture", "with_limits", "file_hash"]
