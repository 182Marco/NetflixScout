"""SQL security on the REAL schema: approved views, hidden columns, CTE, JOIN, plans, fuzzing. Invented seed data, temp files."""
from __future__ import annotations

import random
import sqlite3
import time
from pathlib import Path

import pytest
from cinema_schema_support import build_real

from cinema_db.schema import rebuild_fts

from tool.cinema_db.approved_views import POLICY
from tool.cinema_db.connection import open_database
from tool.cinema_db.errors import PolicyMismatch, SqlExecutionFailed, SqlPlanRejected, SqlRejected, SqlTimeout
from tool.cinema_db.executor import execute
from tool.cinema_db.validator import validate

HIDDEN = "SECRET-HASH"  # the snapshot hash of the seeded second source: no view exposes it


@pytest.fixture(scope="module")
def db(tmp_path_factory) -> Path:
    return build_real(tmp_path_factory.mktemp("real") / "cinema.sqlite3")


@pytest.fixture()
def g(db):
    conn = open_database(db, POLICY)
    yield conn
    conn.close()


def run(g, sql, params=()):
    return execute(g, validate(sql, list(params), g.policy))


def test_the_committed_policy_matches_the_real_database(db):
    open_database(db, POLICY).close()  # verify_policy: view columns, base columns, no triggers
    assert POLICY.view_names == {
        "v_work", "v_person", "v_name", "v_external_id", "v_credit", "v_work_genre", "v_work_country", "v_work_language",
        "v_work_release", "v_work_company", "v_work_genre_label", "v_genre_label", "v_title_search", "v_work_relation", "v_franchise", "v_award_result", "v_work_financial",
        "v_genre", "v_role_type", "v_source",
    }


def test_internal_columns_are_never_readable_base_columns():
    for table, cols in POLICY.base_columns.items():
        assert "source_ref" not in cols and "snapshot_sha256" not in cols and "acquired_at" not in cols, table
    assert "field_provenance" not in POLICY.base_columns and "build_info" not in POLICY.base_columns


@pytest.mark.parametrize("view", sorted(POLICY.view_names))
def test_select_star_of_every_view_runs_through_the_guard(g, view):
    result = run(g, f"SELECT * FROM {view}")
    assert list(result.columns) == [c for c, _ in POLICY.view(view).columns]


QUESTIONS = [
    ("films directed by a person", "SELECT work_title FROM v_credit WHERE person_name = ? AND role = 'director' ORDER BY work_year", ["Ann Director"], [("Sample One",), ("Sample Remake",)]),
    ("who wrote the source novel", "SELECT person_name FROM v_credit WHERE work_title = ? AND role = 'author'", ["Sample Novel"], [("Ann Director",)]),
    ("what a film is based on", "SELECT related_title FROM v_work_relation WHERE work_id = (SELECT work_id FROM v_work WHERE imdb_id = ?) AND relation = 'based_on'", ["tt9000001"], [("Sample Novel",)]),
    ("remake order via follows, both directions", "SELECT related_title, direction FROM v_work_relation WHERE work_title = 'Sample One' AND relation = 'follows'", [], [("Sample Remake", "inverse")]),
    ("titles that share a name", "SELECT count(*) FROM v_work WHERE title = ?", ["Sample One"], [(1,)]),
    ("all works of a franchise in order", "SELECT work_title FROM v_franchise WHERE franchise = ? ORDER BY position", ["Sample Saga"], [("Sample One",), ("Sample Remake",)]),
    ("awards won by a film", "SELECT category FROM v_award_result WHERE work_title = ? AND outcome = 'won'", ["Sample One"], [("Best Picture",)]),
    ("nominees by person", "SELECT work_title, category FROM v_award_result WHERE person_name = ? AND outcome = 'nominated'", ["Ann Director"], [("Sample One", "Best Director")]),
    ("budget and box office", "SELECT kind, amount, currency FROM v_work_financial WHERE work_title = ? ORDER BY kind", ["Sample One"], [("box_office", 20000000, "USD"), ("budget", 1500000, "USD")]),
    ("release date in a country", "SELECT release_date FROM v_work_release WHERE work_id = 1 AND iso2 = ?", ["IT"], [("1982-12-01",)]),
    ("episodes of a season", "SELECT title, episode_number FROM v_work WHERE parent_work_id = 4 ORDER BY episode_number", [], [("Sample Episode", 1)]),
    ("find by an alias", "SELECT entity_id FROM v_name WHERE name_norm = ?", ["uno di prova"], [(1,)]),
    ("reverse id lookup", "SELECT entity_type, entity_id FROM v_external_id WHERE scheme = 'imdb_title' AND value = ?", ["tt9000002"], [("work", 2)]),
    ("genre counts", "SELECT genre, count(*) AS n FROM v_work_genre GROUP BY genre ORDER BY n DESC, genre", [], [("Horror", 2), ("Drama", 1)]),
    ("films by country and genre", "SELECT DISTINCT c.work_title FROM v_work_country c JOIN v_work_genre g ON g.work_id = c.work_id WHERE c.iso2 = 'US' AND c.role = 'origin' AND g.genre = 'Horror' ORDER BY 1", [], [("Sample One",), ("Sample Remake",)]),
    ("a person's collaborators (CTE)", "WITH d AS (SELECT work_id FROM v_credit WHERE person_name = ? AND role = 'director') SELECT person_name FROM v_credit WHERE work_id IN (SELECT work_id FROM d) AND role = 'cast'", ["Ann Director"], [("Bob Actor",)]),
    ("the terms of a source", "SELECT name, license, usage_scope, attribution_required FROM v_source ORDER BY source_id", [], [("test-wikidata", "CC0", "open_public_domain", 0), ("test-wikipedia", "CC BY-SA 4.0", "open_share_alike", 1)]),
    ("where a credit comes from", "SELECT source, count(*) FROM v_credit GROUP BY source", [], [("test-wikidata", 4)]),
]


@pytest.mark.parametrize(("label", "sql", "params", "expected"), QUESTIONS, ids=[q[0] for q in QUESTIONS])
def test_real_cinema_questions_work_through_the_whole_guard(g, label, sql, params, expected):
    assert list(run(g, sql, params).rows) == expected


@pytest.mark.parametrize(
    ("sql", "code"),
    [
        ("SELECT * FROM work", "table_not_allowed"),
        ("SELECT * FROM credit", "table_not_allowed"),
        ("SELECT * FROM entity_name", "table_not_allowed"),
        ("SELECT * FROM external_id", "table_not_allowed"),
        ("SELECT * FROM source", "table_not_allowed"),
        ("SELECT * FROM field_provenance", "table_not_allowed"),
        ("SELECT * FROM build_info", "table_not_allowed"),
        ("SELECT * FROM sqlite_master", "table_not_allowed"),
        ("SELECT * FROM main.v_work", "qualified_name"),
        ("SELECT snapshot_sha256 FROM v_source", "column_not_allowed"),
        ("SELECT source_ref FROM v_work", "column_not_allowed"),
        ("SELECT w.source_id FROM v_work w", "column_not_allowed"),
        ("SELECT work_id FROM v_work, v_person", "join_kind"),
        ("SELECT a.title FROM v_work a JOIN v_work b ON 1 = 1", "join_without_condition"),
        ("SELECT a.title FROM v_work a JOIN v_person p ON p.birth_year = 1948", "join_without_condition"),
        ("SELECT a.title FROM v_work a JOIN v_credit c ON c.work_id = a.work_id JOIN v_person p ON p.person_id = c.person_id JOIN v_work_genre g ON g.work_id = a.work_id JOIN v_work_country k ON k.work_id = a.work_id JOIN v_franchise f ON f.work_id = a.work_id", "too_many_joins"),
        ("WITH credit AS (SELECT 1 AS role) SELECT * FROM credit", "cte_shadows_table"),
        ("WITH v_work AS (SELECT 1 AS title) SELECT * FROM v_work", "cte_shadows_table"),
        ("WITH RECURSIVE t(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM t) SELECT * FROM t", "recursive"),
        ("SELECT title FROM v_work WHERE work_id IN (SELECT entity_id FROM entity)", "table_not_allowed"),
        ("SELECT * FROM pragma_table_info('work')", "table_function"),
        ("SELECT sqlite_version()", "function_not_allowed"),
        ("SELECT json_extract(title, '$') FROM v_work", "function_not_allowed"),
        ("INSERT INTO v_work (work_id) VALUES (1)", "statement_type"),
        ("DELETE FROM v_source", "statement_type"),
        ("UPDATE v_source SET license = 'x'", "statement_type"),
        ("DROP VIEW v_work", "statement_type"),
        ("ATTACH DATABASE 'movie_db/data/movielens32m.sqlite3' AS ml", "statement_type"),
        ("SELECT 1; SELECT snapshot_sha256 FROM source", "multiple_statements"),
    ],
)
def test_forbidden_queries_on_the_real_schema(sql, code):
    with pytest.raises(SqlRejected) as e:
        validate(sql, [], POLICY)
    assert e.value.code == code


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT snapshot_sha256 FROM source",
        "SELECT source_ref FROM work",
        "SELECT kind FROM work",  # an exposed column, but never from the top level of a base table
        "SELECT value FROM build_info",
        "SELECT * FROM field_provenance",
        "WITH v_work AS (SELECT source_ref AS title FROM work) SELECT * FROM v_work",  # CTE posing as a view
        "WITH v_source AS (SELECT snapshot_sha256 AS name FROM source) SELECT * FROM v_source",
        "SELECT randomblob(8)",
        "SELECT name FROM sqlite_master",
    ],
)
def test_the_authorizer_alone_blocks_hidden_data_on_the_real_connection(g, sql):
    with pytest.raises(sqlite3.DatabaseError):
        g.conn.execute(sql).fetchall()


def test_the_hidden_hash_never_appears_in_any_result(g):
    for view in POLICY.view_names:
        assert HIDDEN not in str(run(g, f"SELECT * FROM {view}").rows)


def test_writes_fail_on_the_real_connection_at_every_layer(g, db):
    before = db.read_bytes()
    for stmt in ["INSERT INTO source (name) VALUES ('x')", "UPDATE work SET kind = 'film'", "DROP TABLE credit", "DROP VIEW v_work",
                 "CREATE TABLE z (a)", "ATTACH ':memory:' AS m", "PRAGMA writable_schema = 1", "DELETE FROM v_source"]:
        with pytest.raises(sqlite3.DatabaseError):
            g.conn.execute(stmt)
    g.conn.set_authorizer(None)  # even without the authorizer the file is read-only
    with pytest.raises(sqlite3.DatabaseError):
        g.conn.execute("DELETE FROM credit")
    assert db.read_bytes() == before


def test_a_tampered_database_is_refused(tmp_path):
    for label, stmt in [
        ("a view that exposes a hidden column", "DROP VIEW v_source; CREATE VIEW v_source AS SELECT source_id AS source_id, name AS name, kind AS kind, url AS url, license AS license, license_url AS license_url, usage_scope AS usage_scope, attribution_required AS attribution_required, attribution_text AS attribution_text, terms_note AS terms_note, snapshot_label AS snapshot_label, snapshot_sha256 AS retrieved_at FROM source"),
        ("a trigger", "CREATE TRIGGER t AFTER INSERT ON source BEGIN DELETE FROM source; END"),
        ("a view with another column", "DROP VIEW v_genre; CREATE VIEW v_genre AS SELECT genre_id AS genre_id, label_en AS genre FROM genre"),
        ("a missing view", "DROP VIEW v_role_type"),
    ]:
        path = build_real(tmp_path / f"{abs(hash(label))}.sqlite3")
        c = sqlite3.connect(path)
        c.executescript(stmt)
        c.close()
        with pytest.raises(PolicyMismatch):
            open_database(path, POLICY)


# --- a larger synthetic database: plans and speed ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def big(tmp_path_factory):
    path = build_real(tmp_path_factory.mktemp("big") / "big.sqlite3", seed=False)
    c = sqlite3.connect(path)
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("INSERT INTO source VALUES (1,'bulk','dataset',NULL,'test',NULL,'unverified',0,NULL,NULL,NULL,NULL,NULL)")
    c.executemany("INSERT INTO entity VALUES (?,?)", [(i, "work") for i in range(1, 5001)] + [(i, "person") for i in range(10001, 12001)])
    c.executemany("INSERT INTO work (work_id, kind, release_year, source_id) VALUES (?,'film',?,1)", [(i, 1950 + i % 70) for i in range(1, 5001)])
    c.executemany("INSERT INTO person (person_id, birth_year, source_id) VALUES (?,?,1)", [(i, 1900 + i % 90) for i in range(10001, 12001)])
    c.executemany("INSERT INTO entity_name (entity_id, name, name_norm, kind, is_primary, source_id) VALUES (?,?,?,'primary',1,1)",
                  [(i, f"Film {i}", f"film {i}") for i in range(1, 5001)] + [(i, f"Person {i}", f"person {i}") for i in range(10001, 12001)])
    rnd = random.Random(7)
    credits = {(rnd.randint(1, 5000), rnd.randint(10001, 12000), rnd.choice(["director", "cast", "cast", "cast", "writer"])) for _ in range(60000)}
    c.executemany("INSERT INTO credit (work_id, person_id, role, source_id) VALUES (?,?,?,1)", sorted(credits))
    c.execute("INSERT INTO genre VALUES (1,'ga','G1','G1',NULL,NULL,1),(2,'gb','G2','G2',NULL,NULL,1)")
    c.execute("INSERT INTO genre_label (label_id, label_it, label_norm, source_id) VALUES (1,'g1','g1',1),(2,'g2','g2',1)")
    c.execute("INSERT INTO genre_label_map VALUES (1,1,'exact','t',1),(2,2,'exact','t',1)")
    c.executemany("INSERT INTO work_genre VALUES (?,?,1,NULL)", [(i, 1 + i % 2) for i in range(1, 5001)])
    rebuild_fts(c)
    c.execute("ANALYZE")
    c.commit()
    c.close()
    return path


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT person_name, count(*) AS n FROM v_credit WHERE role = 'director' GROUP BY person_id ORDER BY n DESC LIMIT 10",
        "SELECT work_title FROM v_credit WHERE person_id = 10500 AND role = 'director'",
        "SELECT person_name, count(*) AS n FROM v_credit GROUP BY person_id ORDER BY n DESC LIMIT 10",  # one linear scan of the biggest table
        "SELECT genre, count(*) FROM v_work_genre GROUP BY genre",
        "SELECT title, year FROM v_work WHERE year BETWEEN 1990 AND 1999 ORDER BY year, title LIMIT 20",
        "SELECT title FROM v_work WHERE imdb_id = 'tt0000001'",
        "SELECT c1.person_name, count(*) FROM v_credit c1 JOIN v_credit c2 ON c2.work_id = c1.work_id AND c2.person_id <> c1.person_id WHERE c1.role = 'director' AND c2.role = 'director' GROUP BY c1.person_id LIMIT 5",
    ],
)
def test_real_queries_on_a_large_database_are_fast_and_not_refused(big, sql):
    g = open_database(big, POLICY)
    try:
        started = time.monotonic()
        execute(g, validate(sql, [], POLICY))
        assert time.monotonic() - started < 1.5
    finally:
        g.close()


def test_a_quadratic_query_is_stopped_by_the_plan_or_the_deadline(big):
    g = open_database(big, POLICY)
    try:
        with pytest.raises((SqlPlanRejected, SqlTimeout)):
            execute(g, validate("SELECT count(*) FROM v_credit a JOIN v_credit b ON length(b.role) = length(a.role)", [], POLICY))
        assert execute(g, validate("SELECT count(*) FROM v_work", [], POLICY)).rows == ((5000,),)  # the connection is still usable
    finally:
        g.close()


def test_fuzzing_the_real_views_never_writes_and_never_leaks(db):
    rng = random.Random(1105)
    from test_cinema_sql_security import _mutations  # same deterministic mutator as the fixture fuzz

    seeds = [q[1] for q in QUESTIONS] + ["SELECT * FROM v_source", "SELECT * FROM v_work", "SELECT * FROM source", "SELECT snapshot_sha256 FROM v_source"]
    before = db.read_bytes()
    g = open_database(db, POLICY)
    accepted = 0
    try:
        for _ in range(1200):
            sql = _mutations(rng, rng.choice(seeds))
            try:
                validated = validate(sql, [], POLICY)
            except SqlRejected:
                continue
            if validated.sql.count("?"):
                continue
            accepted += 1
            try:
                result = execute(g, validated)
            except (SqlTimeout, SqlExecutionFailed, SqlPlanRejected):
                continue
            assert HIDDEN not in str(result.rows)
        assert g.conn.total_changes == 0
    finally:
        g.close()
    assert db.read_bytes() == before and accepted > 30


# --- FTS5 title search through the public view -----------------------------------------------------------------------


def titles(g, match, extra=""):
    return [r[0] for r in run(g, f"SELECT DISTINCT entity_id FROM v_title_search WHERE search MATCH ? {extra}", [match]).rows]


def test_full_text_search_finds_titles_aliases_prefixes_and_ignores_accents(g):
    assert titles(g, "sample") == [1, 2, 3, 4, 5, 6] or set(titles(g, "sample")) >= {1, 2, 3}
    assert set(titles(g, "remak*")) == {2}
    assert titles(g, "prova") == [1]  # the Italian alias "Uno di prova"
    assert titles(g, '"sample one"') == [1]
    assert set(titles(g, "novel OR remake")) == {2, 6}
    assert titles(g, "name:ann") == [10]
    # relevance order and the work's kind and year ride along, so a title can be told from a homonym without a second query
    rows = run(g, "SELECT name, work_kind, work_year FROM v_title_search WHERE search MATCH ? ORDER BY rank LIMIT 3", ["sample"]).rows
    assert rows and all(len(r) == 3 for r in rows)


def test_accents_and_case_do_not_matter_in_full_text_search(tmp_path):
    path = build_real(tmp_path / "acc.sqlite3", seed=False)
    c = sqlite3.connect(path)
    c.execute("INSERT INTO source VALUES (1,'t','dataset',NULL,'t',NULL,'unverified',0,NULL,NULL,NULL,NULL,NULL)")
    c.execute("INSERT INTO entity VALUES (1,'work')")
    c.execute("INSERT INTO work (work_id, kind, source_id) VALUES (1,'film',1)")
    c.execute("INSERT INTO entity_name (entity_id, name, name_norm, kind, is_primary, source_id) VALUES (1,'Così è la vita — L''été','così è la vita','primary',1,1)")
    rebuild_fts(c)
    c.commit()
    c.close()
    g = open_database(path, POLICY)
    try:
        for term in ("cosi", "COSÌ", "ete", "été", "vit*"):
            assert titles(g, term) == [1], term
    finally:
        g.close()


def test_exact_lookup_by_identifier_and_by_normalised_name_still_works(g):
    assert run(g, "SELECT entity_id FROM v_external_id WHERE scheme = 'imdb_title' AND value = ?", ["tt9000001"]).rows == ((1,),)
    assert run(g, "SELECT entity_id FROM v_name WHERE name_norm = ?", ["sample one"]).rows == ((1,),)


@pytest.mark.parametrize(
    ("sql", "code"),
    [
        ("SELECT * FROM entity_name_fts WHERE entity_name_fts MATCH 'x'", "table_not_allowed"),
        ("SELECT * FROM entity_name_fts_data", "table_not_allowed"),
        ("SELECT * FROM entity_name_fts_idx", "table_not_allowed"),
        ("SELECT bm25(v_title_search) FROM v_title_search WHERE search MATCH 'x'", "function_not_allowed"),
        ("SELECT highlight(v_title_search, 0, '<', '>') FROM v_title_search WHERE search MATCH 'x'", "function_not_allowed"),
        ("SELECT snippet(v_title_search, 0, '<', '>', '.', 5) FROM v_title_search WHERE search MATCH 'x'", "function_not_allowed"),
        ("INSERT INTO entity_name_fts(entity_name_fts) VALUES ('rebuild')", "statement_type"),
        ("INSERT INTO entity_name_fts(entity_name_fts, rank) VALUES ('delete-all', 1)", "statement_type"),
        ("SELECT rowid FROM v_title_search", "column_not_allowed"),
        ("SELECT name_id FROM v_title_search", "column_not_allowed"),
    ],
)
def test_the_fts_internals_are_not_reachable_from_model_sql(sql, code):
    with pytest.raises(SqlRejected) as e:
        validate(sql, [], POLICY)
    assert e.value.code == code


def test_fts_cannot_be_written_or_reconfigured_even_on_the_raw_connection(g, db):
    before = db.read_bytes()
    for stmt in ["INSERT INTO entity_name_fts(entity_name_fts) VALUES ('rebuild')", "INSERT INTO entity_name_fts(entity_name_fts, rank) VALUES ('rank', 'bm25(10.0)')",
                 "DELETE FROM entity_name_fts", "DROP TABLE entity_name_fts", "INSERT INTO entity_name_fts_data VALUES (1, x'00')",
                 "PRAGMA user_version = 7", "PRAGMA data_version = 1", "PRAGMA writable_schema = 1", "PRAGMA table_info(entity_name)"]:
        with pytest.raises(sqlite3.DatabaseError):
            g.conn.execute(stmt)
    assert db.read_bytes() == before


def test_the_only_pragma_the_engine_may_issue_is_data_version():
    from tool.cinema_db.connection import make_authorizer

    auth = make_authorizer(POLICY)
    assert auth(sqlite3.SQLITE_PRAGMA, "data_version", None, None, None) == sqlite3.SQLITE_OK
    for name, arg in [("data_version", "1"), ("user_version", None), ("writable_schema", "1"), ("journal_mode", None), ("table_info", "work")]:
        assert auth(sqlite3.SQLITE_PRAGMA, name, arg, None, None) == sqlite3.SQLITE_DENY


def test_a_bad_full_text_query_fails_cleanly_without_the_engine_text(g):
    for bad in ('"unterminated', "AND OR", "name:", "NEAR(", "*"):
        with pytest.raises(SqlExecutionFailed) as e:
            run(g, "SELECT entity_id FROM v_title_search WHERE search MATCH ?", [bad])
        assert "fts5" not in str(e.value).lower() and "syntax" not in str(e.value).lower()


def test_a_stale_fts_index_is_detected(tmp_path):
    from cinema_db.schema import check_fts

    path = build_real(tmp_path / "stale.sqlite3")
    c = sqlite3.connect(path)
    assert check_fts(c) == []
    c.execute("INSERT INTO entity_name (entity_id, name, name_norm, kind, source_id) VALUES (1,'Late alias','late alias','alias',1)")
    assert any("rebuild" in p for p in check_fts(c))
    rebuild_fts(c)
    assert check_fts(c) == []
    c.close()


def test_full_text_search_on_a_large_database_is_fast(big):
    g = open_database(big, POLICY)
    try:
        for match in ("film", "film 4*", "person 10*", '"film 1234"', "film OR person"):
            started = time.monotonic()
            result = execute(g, validate("SELECT entity_id, name FROM v_title_search WHERE search MATCH ? ORDER BY rank LIMIT 20", [match], POLICY))
            assert result.rows and time.monotonic() - started < 1.0, match
    finally:
        g.close()
