"""Security of the cinema SQL guard: validator, connection, authorizer, executor. Offline, free, fixture database only."""
from __future__ import annotations

import ast
import random
import sqlite3
from pathlib import Path

import pytest
from cinema_sql_support import POLICY, build_db, file_hash, open_fixture, with_limits

from tool.cinema_db.connection import make_authorizer, open_database
from tool.cinema_db.errors import DatabaseMissing, PolicyMismatch, SqlExecutionFailed, SqlPlanRejected, SqlRejected, SqlTimeout
from tool.cinema_db.executor import execute
from tool.cinema_db.policy import Policy, ViewSpec
from tool.cinema_db.validator import validate


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    return build_db(tmp_path / "cinema.sqlite3", extra_credits=3000)


@pytest.fixture()
def guarded(db: Path):
    g = open_fixture(db)
    yield g
    g.close()


def run(guarded, sql, params=()):
    return execute(guarded, validate(sql, list(params), guarded.policy))


# --- what must work ---------------------------------------------------------------------------------------------

VALID = [
    "SELECT title FROM v_film WHERE year = 2004 ORDER BY title",
    "SELECT * FROM v_film",
    "SELECT count(*) FROM v_film",
    "SELECT f.title, p.name FROM v_film f JOIN v_credit c ON c.film_id = f.id JOIN v_person p ON p.id = c.person_id WHERE c.role = 'director'",
    "SELECT year, count(*) AS n FROM v_film GROUP BY year HAVING count(*) > 0 ORDER BY n DESC",
    "WITH d AS (SELECT film_id FROM v_credit WHERE role = 'director') SELECT title FROM v_film WHERE id IN (SELECT film_id FROM d)",
    "SELECT title FROM v_film UNION SELECT name FROM v_person",
    "SELECT lower(title), upper(title), length(title), substr(title, 1, 3), coalesce(year, 0), round(avg(year), 1), group_concat(title) FROM v_film",
    "SELECT title FROM v_film WHERE title LIKE 'Sample%' AND title GLOB 'S*'",
    "SELECT CASE WHEN year > 2000 THEN 'new' ELSE 'old' END FROM v_film",
    "SELECT cast(year AS TEXT) FROM v_film",
    "SELECT title FROM v_film;",
    "SELECT 1",
]


@pytest.mark.parametrize("sql", VALID)
def test_valid_queries_run(guarded, sql):
    result = run(guarded, sql)
    assert result.rows is not None and not result.truncated_reason == "size"


def test_parameters_are_bound_and_the_text_never_contains_them(guarded):
    validated = validate("SELECT title FROM v_film WHERE year = ? AND title LIKE ?", [2004, "Sample%"], guarded.policy)
    assert "Sample%" not in validated.sql and "?" in validated.sql
    assert execute(guarded, validated).rows == (("Sample Two",),)


def test_the_regenerated_text_is_what_runs_and_comments_vanish(guarded):
    validated = validate("SELECT title /* ; DROP TABLE film */ FROM v_film -- ; DELETE FROM film", [], guarded.policy)
    assert "DROP" not in validated.sql.upper() and "DELETE" not in validated.sql.upper() and "--" not in validated.sql
    assert len(execute(guarded, validated).rows) == 3


def test_limit_is_added_and_bounded(guarded):
    no_limit = validate("SELECT * FROM v_film", [], guarded.policy)
    assert no_limit.limit == 50 and no_limit.sql.endswith("LIMIT 51")  # one extra row tells the executor it was cut
    own = validate("SELECT * FROM v_film LIMIT 5", [], guarded.policy)
    assert own.limit == 5 and own.sql.endswith("LIMIT 5")
    huge = validate("SELECT * FROM v_film LIMIT 99999999", [], guarded.policy)
    assert huge.limit == 50 and huge.sql.endswith("LIMIT 51") and "99999999" not in huge.sql


# --- what must be refused by the validator ----------------------------------------------------------------------

FORBIDDEN = [
    ("DROP TABLE film", "statement_type"),
    ("DROP VIEW v_film", "statement_type"),
    ("DELETE FROM v_film", "statement_type"),
    ("INSERT INTO v_film VALUES (9, 'x', 1)", "statement_type"),
    ("UPDATE v_person SET name = 'x'", "statement_type"),
    ("REPLACE INTO v_film VALUES (9, 'x', 1)", "statement_type"),
    ("CREATE TABLE x (a)", "statement_type"),
    ("CREATE VIEW x AS SELECT 1", "statement_type"),
    ("CREATE TRIGGER t AFTER INSERT ON film BEGIN SELECT 1; END", "multiple_statements"),
    ("ALTER TABLE film ADD COLUMN z", "statement_type"),
    ("ATTACH DATABASE '/tmp/x' AS x", "statement_type"),
    ("DETACH DATABASE x", "statement_type"),
    ("PRAGMA writable_schema = 1", "statement_type"),
    ("PRAGMA table_info(film)", "statement_type"),
    ("VACUUM", "statement_type"),
    ("VACUUM INTO '/tmp/copy.db'", "statement_type"),
    ("REINDEX", "statement_type"),
    ("ANALYZE", "statement_type"),
    ("BEGIN", "statement_type"),
    ("COMMIT", "statement_type"),
    ("SAVEPOINT a", "statement_type"),
    ("EXPLAIN SELECT 1", "statement_type"),
    ("EXPLAIN QUERY PLAN SELECT * FROM v_film", "statement_type"),
    ("SELECT 1; DROP TABLE film", "multiple_statements"),
    ("SELECT 1; SELECT 2", "multiple_statements"),
    ("SELECT 1 /*; DROP TABLE film*/; SELECT 2", "multiple_statements"),
    ("SELECT * FROM v_film; DELETE FROM film", "multiple_statements"),
    ("SELECT * FROM film", "table_not_allowed"),
    ("SELECT * FROM hidden", "table_not_allowed"),
    ("SELECT * FROM sqlite_master", "table_not_allowed"),
    ("SELECT * FROM sqlite_schema", "table_not_allowed"),
    ("SELECT * FROM main.v_film", "qualified_name"),
    ("SELECT * FROM temp.sqlite_master", "qualified_name"),
    ("SELECT * FROM pragma_table_info('film')", "table_function"),
    ("SELECT * FROM json_each('[1]')", "table_function"),
    ("SELECT * FROM generate_series(1, 10)", "table_function"),
    ("SELECT secret_note FROM v_film", "column_not_allowed"),
    ("SELECT private FROM v_person", "column_not_allowed"),
    ("SELECT f.secret_note FROM v_film f", "column_not_allowed"),
    ("SELECT load_extension('/tmp/x.so')", "function_not_allowed"),
    ("SELECT readfile('/etc/passwd')", "function_not_allowed"),
    ("SELECT writefile('/tmp/x', 'y')", "function_not_allowed"),
    ("SELECT randomblob(1000000000)", "function_not_allowed"),
    ("SELECT zeroblob(1000000000)", "function_not_allowed"),
    ("SELECT random()", "function_not_allowed"),
    ("SELECT sqlite_version()", "function_not_allowed"),
    ("SELECT printf('%1000000d', 1)", "function_not_allowed"),
    ("SELECT json_extract('{}', '$')", "function_not_allowed"),
    ("SELECT sqlite_compileoption_used('x')", "function_not_allowed"),
    ("WITH RECURSIVE t(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM t) SELECT count(*) FROM t", "recursive"),
    ("WITH film AS (SELECT 1 AS title) SELECT * FROM film", "cte_shadows_table"),
    ("WITH v_film AS (SELECT 1 AS title) SELECT * FROM v_film", "cte_shadows_table"),
    ("SELECT a.title FROM v_film a, v_film b", "join_kind"),
    ("SELECT a.title FROM v_film a CROSS JOIN v_film b", "join_kind"),
    ("SELECT a.title FROM v_film a NATURAL JOIN v_film b", "join_kind"),
    ("SELECT a.title FROM v_film a JOIN v_film b", "join_without_condition"),
    ("SELECT * FROM (VALUES (1), (2))", "forbidden_construct"),
    ("SELECT title, row_number() OVER (ORDER BY title) FROM v_film", "forbidden_construct"),
    ("SELECT * FROM v_film WHERE id = :x", "named_parameter"),
    ("SELECT * FROM v_film LIMIT 1 OFFSET 99999999", "offset_not_allowed"),
    ("SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5", "too_many_branches"),
    ("SELECT * FROM v_film WHERE id IN (SELECT id FROM v_film WHERE id IN (SELECT id FROM v_film WHERE id IN (SELECT id FROM v_film WHERE id IN (SELECT id FROM v_film))))", "too_deep"),
    ("", "empty"),
    ("   ", "empty"),
    (";", "empty"),
    ("SELECT 'a\x00b'", "control_chars"),
    ("SELEC title FROM v_film", "syntax"),
    ("SELECT FROM", "syntax"),
]


@pytest.mark.parametrize(("sql", "code"), FORBIDDEN)
def test_forbidden_statements_are_rejected_with_a_stable_code(sql, code):
    with pytest.raises(SqlRejected) as caught:
        validate(sql, [], POLICY)
    assert caught.value.code == code


EVASIONS = [
    'SELECT * FROM "film"', "SELECT * FROM [film]", "SELECT * FROM `film`", "SELECT * FROM FiLm", 'SELECT * FROM "main"."v_film"',
    'SELECT * FROM "sqlite_master"', "SELECT * FROM [sqlite_master]", "SELECT * FROM sqlite_temp_master", "SELECT * FROM \"v_film\" , \"film\"",
    "SELECT * FROM v_film WHERE id IN (SELECT id FROM film)", "SELECT (SELECT secret_note FROM film LIMIT 1)",
    "SELECT * FROM v_film f, (SELECT * FROM hidden) h", "SELECT * FROM v_film UNION ALL SELECT x, x, x FROM hidden",
    "SELECT \u202eDROP", "SELECT lоwer(title) FROM v_film",  # Cyrillic о: not the allowed function
    "SELECT LOAD_EXTENSION('x')", "SELECT Random()", "SELECT * FROM v_film WHERE title = 'a' OR 1; DROP TABLE film",
    "SELECT * FROM v_film ORDER BY (SELECT secret_note FROM film)", "SELECT * FROM v_film GROUP BY (SELECT x FROM hidden)",
]


@pytest.mark.parametrize("sql", EVASIONS)
def test_quoting_case_and_unicode_do_not_bypass_the_whitelists(sql):
    with pytest.raises(SqlRejected):
        validate(sql, [], POLICY)


def test_quoted_and_mixed_case_names_of_approved_views_still_work(guarded):
    assert run(guarded, 'SELECT "Title" FROM "V_Film" WHERE `year` = 2004').rows
    assert run(guarded, "SELECT [title] FROM [v_film]").rows


def test_a_limit_that_is_not_a_written_number_is_rejected():
    with pytest.raises(SqlRejected) as e:
        validate("SELECT * FROM v_film LIMIT ?", [1], POLICY)
    assert e.value.code == "limit_not_literal"


def test_a_join_needs_a_condition_that_relates_two_tables():
    for sql in ("SELECT a.title FROM v_film a JOIN v_film b ON 1 = 1", "SELECT a.title FROM v_film a JOIN v_film b ON TRUE",
                "SELECT a.title FROM v_film a JOIN v_credit c ON c.role = 'cast'", "SELECT a.title FROM v_film a JOIN v_credit c ON a.id = a.id"):
        with pytest.raises(SqlRejected) as e:
            validate(sql, [], POLICY)
        assert e.value.code == "join_without_condition"
    validate("SELECT a.title FROM v_film a JOIN v_credit c USING (film_id)".replace("v_film a", "v_credit a").replace("a.title", "a.role"), [], POLICY)


def test_too_long_and_too_many_joins_and_literals_are_rejected():
    with pytest.raises(SqlRejected) as e:
        validate("SELECT " + "1," * 1500 + "1", [], POLICY)
    assert e.value.code in {"too_long", "too_complex"}
    joins = "SELECT a.title FROM v_film a " + " ".join(f"JOIN v_film b{i} ON b{i}.id = a.id" for i in range(5))
    with pytest.raises(SqlRejected) as e:
        validate(joins, [], POLICY)
    assert e.value.code == "too_many_joins"
    with pytest.raises(SqlRejected) as e:
        validate("SELECT * FROM v_film WHERE title IN (" + ",".join(f"'{i}'" for i in range(40)) + ")", [], POLICY)
    assert e.value.code == "too_many_literals"
    with pytest.raises(SqlRejected) as e:
        validate("SELECT '" + "x" * 300 + "'", [], POLICY)
    assert e.value.code == "literal_too_long"


@pytest.mark.parametrize("params", [[True], [{"a": 1}], [[1]], [float("nan")], [2**70], ["x" * 500], ["a\x00b"], [object()], "abc", {"a": 1}])
def test_invalid_parameters_are_rejected(params):
    with pytest.raises(SqlRejected) as e:
        validate("SELECT * FROM v_film WHERE title = ?", params, POLICY)
    assert e.value.code == "params"


def test_placeholder_count_must_match_the_parameters():
    for sql, params in [("SELECT * FROM v_film WHERE id = ?", []), ("SELECT * FROM v_film", [1]), ("SELECT * FROM v_film WHERE id = ? OR id = ?", [1])]:
        with pytest.raises(SqlRejected) as e:
            validate(sql, params, POLICY)
        assert e.value.code == "params"
    with pytest.raises(SqlRejected):
        validate("SELECT * FROM v_film", list(range(17)), POLICY)


def test_the_error_never_repeats_the_statement():
    marker = "MARKER_9f3a"
    for sql in (f"SELECT '{marker}'; DROP TABLE film", f"DROP TABLE {marker}", f"SELECT {marker}() FROM v_film", f"SELECT {marker} FROM v_film", f"SELECT * FROM {marker}"):
        with pytest.raises(SqlRejected) as e:
            validate(sql, [], POLICY)
        assert marker not in str(e.value)


# --- connection: independent layers -----------------------------------------------------------------------------

WRITES = [
    "INSERT INTO film VALUES (9, 'x', 1, 'y')",
    "UPDATE film SET title = 'x'",
    "DELETE FROM film",
    "DROP TABLE film",
    "CREATE TABLE z (a)",
    "ALTER TABLE film ADD COLUMN z",
    "PRAGMA writable_schema = 1",
    "ATTACH DATABASE ':memory:' AS m",
    "VACUUM",
    "CREATE TEMP TABLE z (a)",
]


@pytest.mark.parametrize("sql", WRITES)
def test_no_write_works_on_the_guarded_connection(guarded, db, sql):
    before = file_hash(db)
    with pytest.raises(sqlite3.DatabaseError):
        guarded.conn.execute(sql)
    assert file_hash(db) == before and guarded.conn.total_changes == 0


@pytest.mark.parametrize("sql", WRITES[:5])
@pytest.mark.parametrize("immutable", [True, False])
def test_the_file_is_read_only_even_without_the_authorizer(db, sql, immutable):
    """Layer check: mode=ro (+ immutable, + query_only) stops a write when the authorizer is removed."""
    g = open_fixture(db, immutable=immutable)
    try:
        g.conn.set_authorizer(None)
        before = file_hash(db)
        with pytest.raises(sqlite3.DatabaseError):
            g.conn.execute(sql)
            g.conn.commit()
        assert file_hash(db) == before
    finally:
        g.close()


def test_a_missing_file_is_never_created(tmp_path):
    with pytest.raises(DatabaseMissing):
        open_database(tmp_path / "nope.sqlite3", POLICY)
    assert not (tmp_path / "nope.sqlite3").exists()


def test_extensions_cannot_be_loaded(guarded):
    if hasattr(guarded.conn, "enable_load_extension"):
        with pytest.raises(sqlite3.DatabaseError):
            guarded.conn.load_extension("/tmp/does-not-exist")
    with pytest.raises(sqlite3.DatabaseError):
        guarded.conn.execute("SELECT load_extension('/tmp/x')").fetchall()


def test_sqlite_limits_are_set(guarded):
    assert guarded.conn.getlimit(sqlite3.SQLITE_LIMIT_ATTACHED) == 0
    assert guarded.conn.getlimit(sqlite3.SQLITE_LIMIT_FUNCTION_ARG) == POLICY.limits.sqlite_function_args
    assert guarded.conn.getlimit(sqlite3.SQLITE_LIMIT_LIKE_PATTERN_LENGTH) == POLICY.limits.sqlite_like_pattern


# --- authorizer: deny by default -------------------------------------------------------------------------------


def test_every_action_code_is_denied_except_select_read_and_function():
    authorizer = make_authorizer(POLICY)
    allowed = {code for code in range(0, 200) if authorizer(code, "v_film", "title", "main", None) == sqlite3.SQLITE_OK}
    assert allowed <= {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ}
    assert authorizer(sqlite3.SQLITE_FUNCTION, None, "lower", None, None) == sqlite3.SQLITE_OK
    assert authorizer(sqlite3.SQLITE_FUNCTION, None, "randomblob", None, None) == sqlite3.SQLITE_DENY
    for name, code in vars(sqlite3).items():
        if name.startswith("SQLITE_") and isinstance(code, int) and 0 <= code < 100 and name not in {"SQLITE_SELECT", "SQLITE_READ", "SQLITE_FUNCTION"}:
            # Result codes (SQLITE_OK, SQLITE_MISMATCH = 20, ...) share numbers with action codes: only actions count.
            if code in {sqlite3.SQLITE_READ, sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION} or name.startswith(("SQLITE_LIMIT", "SQLITE_DBCONFIG")):
                continue
            assert authorizer(code, "v_film", "title", "main", None) == sqlite3.SQLITE_DENY, name


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT title FROM film",  # base table from the top level
        "SELECT secret_note FROM film",
        "SELECT * FROM hidden",
        "SELECT x FROM hidden",
        "SELECT * FROM sqlite_master",
        "SELECT private FROM person",
        "WITH v_film AS (SELECT secret_note AS title FROM film) SELECT * FROM v_film",  # shadowing a view with a CTE
        "WITH v_film AS (SELECT x AS title FROM hidden) SELECT * FROM v_film",
        "SELECT randomblob(4)",
        "SELECT sqlite_version()",
        "SELECT * FROM pragma_table_info('film')",
        "SELECT * FROM v_film WHERE id IN (SELECT rowid FROM film)",
    ],
)
def test_the_authorizer_blocks_what_the_validator_would_have_blocked(guarded, sql):
    with pytest.raises(sqlite3.DatabaseError):
        guarded.conn.execute(sql).fetchall()


def test_the_authorizer_lets_the_views_work(guarded):
    assert guarded.conn.execute("SELECT count(*) FROM v_film").fetchone() == (3,)
    assert guarded.conn.execute("SELECT lower(title) FROM v_film WHERE title LIKE 'S%'").fetchall()


# --- policy is verified against the real database --------------------------------------------------------------


def test_a_policy_that_declares_a_missing_column_is_refused(db):
    bad = Policy(views=(ViewSpec("v_film", (("id", "INTEGER"), ("title", "TEXT"), ("nope", "TEXT"))),), base_columns={"film": frozenset({"id", "title", "year"})})
    with pytest.raises(PolicyMismatch):
        open_database(db, bad)


def test_a_view_reading_an_undeclared_base_column_is_refused(db):
    narrow = Policy(views=POLICY.views, base_columns={**POLICY.base_columns, "film": frozenset({"id", "title"})})
    with pytest.raises(PolicyMismatch):
        open_database(db, narrow)


def test_a_missing_view_or_a_trigger_is_refused(tmp_path):
    with pytest.raises(PolicyMismatch):
        open_database(build_db(tmp_path / "a.sqlite3"), Policy(views=(ViewSpec("v_ghost", (("a", "TEXT"),)),), base_columns={}))
    with pytest.raises(PolicyMismatch):
        open_database(build_db(tmp_path / "b.sqlite3", trigger=True), POLICY)


# --- executor --------------------------------------------------------------------------------------------------


def test_rows_are_capped_and_flagged(db):
    g = open_fixture(db, with_limits(POLICY, max_rows=5))
    try:
        result = execute(g, validate("SELECT * FROM v_credit", [], g.policy))
        assert len(result.rows) == 5 and result.truncated and result.truncated_reason == "rows"
        assert not execute(g, validate("SELECT * FROM v_person", [], g.policy)).truncated
    finally:
        g.close()


def test_a_slow_query_times_out_and_the_connection_survives(db):
    g = open_fixture(db, with_limits(POLICY, timeout_ms=30, max_nodes=900))
    try:
        slow = "SELECT count(*) FROM v_credit a JOIN v_credit b ON b.role = a.role JOIN v_credit c ON c.role = b.role"
        with pytest.raises(SqlTimeout):
            execute(g, validate(slow, [], g.policy))
        assert execute(g, validate("SELECT count(*) FROM v_film", [], g.policy)).rows == ((3,),)
    finally:
        g.close()


def test_big_results_are_cut_by_size_and_cells_are_clipped(db):
    g = open_fixture(db, with_limits(POLICY, max_result_chars=40, max_cell_chars=6))
    try:
        result = execute(g, validate("SELECT title FROM v_film", [], g.policy))
        assert all(len(r[0]) <= 7 for r in result.rows)
        big = execute(g, validate("SELECT title, title, title, title FROM v_film", [], g.policy))
        assert big.truncated and big.truncated_reason == "size"
    finally:
        g.close()


def test_a_scan_of_a_large_table_that_needs_a_sort_is_refused_but_a_selective_one_runs(guarded):
    with pytest.raises(SqlPlanRejected):
        execute(guarded, validate("SELECT role, count(*) FROM v_credit GROUP BY role", [], guarded.policy))
    with pytest.raises(SqlPlanRejected):
        execute(guarded, validate("SELECT person_id FROM v_credit ORDER BY role", [], guarded.policy))
    assert execute(guarded, validate("SELECT person_id FROM v_credit WHERE film_id = 1", [], guarded.policy)).rows
    assert execute(guarded, validate("SELECT person_id FROM v_credit LIMIT 3", [], guarded.policy)).rows


def test_a_runtime_error_is_reported_without_the_engine_text(guarded):
    with pytest.raises(SqlExecutionFailed) as e:
        execute(guarded, validate("SELECT abs(-9223372036854775808) FROM v_film", [], guarded.policy))
    assert "overflow" not in str(e.value).lower()


# --- deterministic fuzzing --------------------------------------------------------------------------------------

_NASTY = [
    "'; DROP TABLE film; --", "/* */", "‮", "\u0000", "\\", '"', "`", "[", ";", " UNION SELECT secret_note FROM film",
    "/*!50000 DROP*/", "--\n", "\n", "\t", "%", "?", ":a", "@a", "$a", "0x1", "ESCAPE", "ATTACH", "PRAGMA", "sqlite_master",
]


def _mutations(rng: random.Random, sql: str) -> str:
    words = sql.split(" ")
    for _ in range(rng.randint(1, 4)):
        kind = rng.choice(["case", "insert", "append", "comment", "swap", "dup"])
        i = rng.randrange(len(words))
        if kind == "case":
            words[i] = words[i].swapcase()
        elif kind == "insert":
            words.insert(i, rng.choice(_NASTY))
        elif kind == "append":
            words.append(rng.choice(_NASTY))
        elif kind == "comment":
            words[i] = f"/*{rng.choice(_NASTY)}*/" + words[i]
        elif kind == "swap" and len(words) > 1:
            j = rng.randrange(len(words))
            words[i], words[j] = words[j], words[i]
        else:
            words.insert(i, words[i])
    return " ".join(words)


def test_fuzzed_statements_never_write_and_never_leak(db):
    rng = random.Random(20261105)
    g = open_fixture(db)
    before, accepted = file_hash(db), 0
    try:
        for _ in range(1500):
            sql = _mutations(rng, rng.choice(VALID + [s for s, _ in FORBIDDEN]))
            try:
                validated = validate(sql, [], g.policy)
            except SqlRejected:
                continue
            accepted += 1
            assert validated.sql.lstrip().upper().startswith(("SELECT", "WITH")) and ";" not in validated.sql.replace("';'", "")
            try:
                result = execute(g, validated)
            except (SqlTimeout, SqlExecutionFailed, SqlPlanRejected):
                continue
            assert all("TOP-SECRET" not in str(v) and not str(v).startswith(("S1", "S2", "P1")) for row in result.rows for v in row)
        assert g.conn.total_changes == 0 and file_hash(db) == before
    finally:
        g.close()
    assert accepted > 50  # the fuzzer actually exercised the accepted path


# --- static guarantees ------------------------------------------------------------------------------------------


def test_the_sql_guard_imports_no_network_or_process_modules():
    banned = {"socket", "urllib", "http", "requests", "subprocess", "os", "shutil", "ctypes", "importlib", "pickle"}
    for path in Path("tool/cinema_db").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) and not node.level else []
            assert not {n.split(".")[0] for n in names} & banned, (path, names)


def test_no_function_is_registered_on_the_connection():
    for path in Path("tool/cinema_db").glob("*.py"):
        text = path.read_text()
        assert "create_function" not in text and "create_aggregate" not in text and "create_collation" not in text
