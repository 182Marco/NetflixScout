"""FASE 21: `provenance` read `v_external_id` with `entity_id = ?` and SQLite scanned the whole identifier table (~420 ms for one work). The view is now written in two
branches. This file proves, BEFORE any new build, that (1) the new definition returns exactly the rows of the old one, merged people included, (2) it uses the index on
`entity_id`, (3) it is fast; and that the adopted candidate (candidate6, built after the fix) answers `provenance` within the target (it was an xfail while candidate5 was the target)."""
from __future__ import annotations

import sqlite3
import statistics
import time
from pathlib import Path

import pytest

from cinema_db import schema_v3 as V3
from cinema_v3_support import build_v3  # noqa: F401  (tests/ is on the path)
from tool.cinema_db.config import CinemaDbConfig
from tool.cinema_db.tool import CinemaSqlTool

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "cinema_db/data/cinema.v4.candidate6.sqlite3"

OLD_VIEW = """CREATE TEMP VIEW v_external_id_old AS
    SELECT COALESCE(ec.canonical_entity_id, x.entity_id) AS entity_id, e.entity_type AS entity_type, x.scheme AS scheme, i.label AS scheme_label,
           x.value AS value, CASE WHEN ec.entity_id IS NULL THEN x.is_primary ELSE 0 END AS is_primary
    FROM external_id x JOIN entity e ON e.entity_id = x.entity_id JOIN id_scheme i ON i.scheme = x.scheme LEFT JOIN entity_canonical ec ON ec.entity_id = x.entity_id"""
NEW_VIEW = V3.VIEWS_V3["v_external_id"].replace("CREATE VIEW v_external_id AS", "CREATE TEMP VIEW v_external_id_new AS", 1)
COLS = "entity_id, entity_type, scheme, scheme_label, value, is_primary"
QUERY = "SELECT scheme, value, is_primary FROM {view} WHERE entity_id = ? ORDER BY scheme, is_primary DESC, value LIMIT 40"


def _both(conn: sqlite3.Connection) -> None:
    conn.execute(OLD_VIEW)
    conn.execute(NEW_VIEW)


def test_the_new_definition_is_two_branches_with_the_same_columns() -> None:
    sql = V3.VIEWS_V3["v_external_id"]
    assert "UNION ALL" in sql and "COALESCE" not in sql
    assert [c.strip().split(" AS ")[-1] for c in NEW_VIEW.split("SELECT")[1].split("FROM")[0].split(",")] == [c.strip() for c in COLS.split(",")]


def test_on_the_miniature_database_the_two_views_return_the_same_rows(tmp_path) -> None:
    path = build_v3(tmp_path / "v3.sqlite3")
    conn = sqlite3.connect(path)
    _both(conn)
    old = sorted(conn.execute(f"SELECT {COLS} FROM v_external_id_old").fetchall(), key=repr)
    new = sorted(conn.execute(f"SELECT {COLS} FROM v_external_id_new").fetchall(), key=repr)
    assert old == new and old
    merged = {r[0] for r in conn.execute("SELECT entity_id FROM entity_canonical")} | {r[0] for r in conn.execute("SELECT canonical_entity_id FROM entity_canonical")}
    assert merged, "the miniature has a merged person"
    for eid in sorted(merged | {r[0] for r in conn.execute("SELECT work_id FROM work")}):
        assert conn.execute(QUERY.format(view="v_external_id_old"), (eid,)).fetchall() == conn.execute(QUERY.format(view="v_external_id_new"), (eid,)).fetchall(), eid
    # the identifiers of a merged person show under the canonical one, never as preferred
    assert all(p == 0 for _, _, p in conn.execute(QUERY.format(view="v_external_id_new"), (204,)).fetchall() if _ == "wikidata")


# --------------------------------------------------------------------------------------------------------------------- the real file
needs_file = pytest.mark.skipif(not CANDIDATE.is_file(), reason="needs the schema-4 candidate")


@pytest.fixture(scope="module")
def real():
    conn = sqlite3.connect(f"file:{CANDIDATE}?mode=ro&immutable=1", uri=True)  # read only: the new view lives in the TEMP schema
    _both(conn)
    works = [r[0] for r in conn.execute("SELECT work_id FROM work ORDER BY work_id % 7919 LIMIT 40")]
    merged = [r[0] for r in conn.execute("SELECT entity_id FROM entity_canonical")] + [r[0] for r in conn.execute("SELECT canonical_entity_id FROM entity_canonical")]
    return conn, works + merged


@needs_file
def test_on_the_real_file_the_new_view_returns_exactly_the_rows_of_the_old_one(real) -> None:
    conn, _ = real
    assert conn.execute("SELECT count(*) FROM v_external_id_old").fetchone()[0] == conn.execute("SELECT count(*) FROM v_external_id_new").fetchone()[0] > 1_000_000
    assert conn.execute(f"SELECT count(*) FROM (SELECT {COLS} FROM v_external_id_old EXCEPT SELECT {COLS} FROM v_external_id_new)").fetchone()[0] == 0
    assert conn.execute(f"SELECT count(*) FROM (SELECT {COLS} FROM v_external_id_new EXCEPT SELECT {COLS} FROM v_external_id_old)").fetchone()[0] == 0


@needs_file
def test_on_the_real_file_the_new_view_uses_the_entity_index_and_is_fast(real) -> None:
    conn, ids = real
    plan = " | ".join(r[3] for r in conn.execute("EXPLAIN QUERY PLAN " + QUERY.format(view="v_external_id_new"), (ids[0],)))
    assert "SEARCH x USING INDEX external_id_entity (entity_id=?)" in plan and "SCAN x" not in plan
    old_plan = " | ".join(r[3] for r in conn.execute("EXPLAIN QUERY PLAN " + QUERY.format(view="v_external_id_old"), (ids[0],)))
    assert "SCAN x" in old_plan, "the old definition must still be the one that scans (this is what is being fixed)"
    for eid in ids[:12]:
        assert conn.execute(QUERY.format(view="v_external_id_old"), (eid,)).fetchall() == conn.execute(QUERY.format(view="v_external_id_new"), (eid,)).fetchall()
    times = []
    for eid in ids:
        t = time.perf_counter()
        conn.execute(QUERY.format(view="v_external_id_new"), (eid,)).fetchall()
        times.append((time.perf_counter() - t) * 1000)
    assert statistics.median(times) < 10 and max(times) < 100


@needs_file
def test_the_deployed_candidate_answers_provenance_within_the_target() -> None:
    tool = CinemaSqlTool(config=CinemaDbConfig(enabled=True, db_path=str(CANDIDATE), max_queries_per_turn=40, default_limit=10))
    params = {"operation": "provenance", "imdb_id": "tt1375666"}
    tool.run(query="x", params=dict(params))
    times = []
    for _ in range(3):
        t = time.perf_counter()
        body = tool.run(query="x", params=dict(params))["metadata"]["cinema_db"]
        times.append((time.perf_counter() - t) * 1000)
    assert body["status"] == "ok"
    assert statistics.median(times) < 150
