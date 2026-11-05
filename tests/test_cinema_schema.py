"""Structure and integrity of the cinema schema (the real DDL, in a temp folder, with invented seed rows)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from cinema_schema_support import build_real

from cinema_db.schema import PUBLIC_VIEWS, ROLES, create_database

# Definitional vocabularies: no per-fact source.
DEFINITIONAL = {"source", "build_info", "work_kind", "role_type", "relation_type", "id_scheme", "entity"}
# Foreign keys that do not need an index of their own (tiny or definitional parents, or the provenance pointer).
NO_INDEX_NEEDED = {"entity_type", "source_id", "kind", "role", "relation", "scheme", "country_id", "birth_country_id", "parent_genre_id", "language_id"}


@pytest.fixture(scope="module")
def conn(tmp_path_factory):
    path = build_real(tmp_path_factory.mktemp("schema") / "c.sqlite3")
    c = sqlite3.connect(path)
    c.execute("PRAGMA foreign_keys = ON")
    yield c
    c.close()


def rows(c, sql, *p):
    return c.execute(sql, p).fetchall()


def test_the_database_is_consistent_and_every_table_is_strict_with_a_primary_key(conn):
    assert rows(conn, "PRAGMA foreign_key_check") == [] and rows(conn, "PRAGMA integrity_check") == [("ok",)]
    tables = [r[0] for r in rows(conn, "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'entity_name_fts%'")]
    assert len(tables) == 32  # plus the FTS5 virtual table and its five shadow tables
    for t in tables:
        assert "STRICT" in conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (t,)).fetchone()[0].upper()
        assert any(r[5] for r in rows(conn, f"PRAGMA table_info({t})")), t


def test_there_is_no_json_in_the_schema(conn):
    for name, sql in rows(conn, "SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL"):
        assert "json" not in sql.lower(), name


def test_every_fact_table_names_its_source(conn):
    for (t,) in rows(conn, "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'entity_name_fts%'"):
        if t in DEFINITIONAL:
            continue
        cols = {r[1]: r for r in rows(conn, f"PRAGMA table_info({t})")}
        assert "source_id" in cols and cols["source_id"][3] == 1, f"{t} must have a NOT NULL source_id"
        assert any(fk[2] == "source" and fk[3] == "source_id" for fk in rows(conn, f"PRAGMA foreign_key_list({t})")), t


def test_every_foreign_key_that_joins_often_has_an_index(conn):
    for (t,) in rows(conn, "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'entity_name_fts%'"):
        pk = [r[1] for r in sorted(rows(conn, f"PRAGMA table_info({t})"), key=lambda r: r[5]) if r[5]]
        leading = {pk[0]} if pk else set()
        for idx in rows(conn, f"PRAGMA index_list({t})"):
            first = rows(conn, f"PRAGMA index_xinfo({idx[1]})")[0]
            if first[2]:
                leading.add(first[2])
        for fk in rows(conn, f"PRAGMA foreign_key_list({t})"):
            if fk[3] not in NO_INDEX_NEEDED and fk[3] not in leading:
                pytest.fail(f"{t}.{fk[3]} references {fk[2]} but is not the first column of any index")


def test_foreign_keys_are_enforced(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO credit (work_id, person_id, role, source_id) VALUES (999, 10, 'cast', 1)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO credit (work_id, person_id, role, source_id) VALUES (1, 10, 'astronaut', 1)")
    conn.rollback()


def test_a_subtype_row_must_match_its_entity_type(conn):
    conn.execute("INSERT INTO entity VALUES (900, 'person')")
    with pytest.raises(sqlite3.IntegrityError):  # a work cannot hang off a person entity
        conn.execute("INSERT INTO work (work_id, kind, source_id) VALUES (900, 'film', 1)")
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO work (work_id, entity_type, kind, source_id) VALUES (901, 'person', 'film', 1)")
    conn.rollback()


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO entity VALUES (950,'work')",  # then the rows below fail on their own check
    ],
)
def test_check_constraints_on_work(conn, sql):
    conn.execute(sql)
    bad = [
        "INSERT INTO work (work_id, kind, source_id) VALUES (950, 'episode', 1)",  # episode without a parent
        "INSERT INTO work (work_id, kind, source_id) VALUES (950, 'season', 1)",  # season without a parent
        "INSERT INTO work (work_id, kind, parent_work_id, source_id) VALUES (950, 'film', 950, 1)",  # own parent
        "INSERT INTO work (work_id, kind, episode_number, source_id) VALUES (950, 'film', 3, 1)",  # episode number on a film
        "INSERT INTO work (work_id, kind, season_number, source_id) VALUES (950, 'film', 2, 1)",
        "INSERT INTO work (work_id, kind, release_year, source_id) VALUES (950, 'film', 1500, 1)",
        "INSERT INTO work (work_id, kind, release_date, source_id) VALUES (950, 'film', 'yesterday', 1)",
        "INSERT INTO work (work_id, kind, runtime_min, source_id) VALUES (950, 'film', 0, 1)",
        "INSERT INTO work (work_id, kind, status, source_id) VALUES (950, 'film', 'maybe', 1)",
        "INSERT INTO work (work_id, kind, source_id) VALUES (950, 'dessert', 1)",
    ]
    for stmt in bad:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(stmt)
    conn.rollback()


def test_names_identifiers_and_facts_are_unique_where_they_must_be(conn):
    with pytest.raises(sqlite3.IntegrityError):  # a second primary name
        conn.execute("INSERT INTO entity_name (entity_id, name, name_norm, kind, is_primary, source_id) VALUES (1,'X','x','primary',1,1)")
    with pytest.raises(sqlite3.IntegrityError):  # primary flag needs kind primary
        conn.execute("INSERT INTO entity_name (entity_id, name, name_norm, kind, is_primary, source_id) VALUES (2,'X','x','alias',1,1)")
    with pytest.raises(sqlite3.IntegrityError):  # same alias twice
        conn.execute("INSERT INTO entity_name (entity_id, name, name_norm, language, kind, source_id) VALUES (1,'Uno di prova','uno di prova','it','translated',1)")
    with pytest.raises(sqlite3.IntegrityError):  # one identifier value names one entity
        conn.execute("INSERT INTO external_id (entity_id, scheme, value, source_id) VALUES (2,'imdb_title','tt9000001',1)")
    with pytest.raises(sqlite3.IntegrityError):  # duplicate credit
        conn.execute("INSERT INTO credit (work_id, person_id, role, source_id) VALUES (1,10,'director',1)")
    with pytest.raises(sqlite3.IntegrityError):  # an unknown scheme
        conn.execute("INSERT INTO external_id (entity_id, scheme, value, source_id) VALUES (2,'myspace','1',1)")
    conn.rollback()


def test_two_works_may_share_a_title_and_have_alternative_titles(conn):
    conn.execute("INSERT INTO entity VALUES (960,'work')")
    conn.execute("INSERT INTO work (work_id, kind, release_year, source_id) VALUES (960,'film',2004,1)")
    conn.execute("INSERT INTO entity_name (entity_id, name, name_norm, kind, is_primary, source_id) VALUES (960,'Sample One','sample one','primary',1,1)")
    assert [r[0] for r in rows(conn, "SELECT year FROM v_work WHERE title = 'Sample One' ORDER BY year")] == [1982, 2004]
    conn.rollback()


def test_award_result_needs_a_work_or_a_person_and_money_needs_a_currency(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO award_result (ceremony_id, category_id, outcome, source_id) VALUES (1,1,'won',1)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO award_result (ceremony_id, category_id, work_id, outcome, source_id) VALUES (1,1,2,'tied',1)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO work_financial (work_id, kind, scope, amount, currency, source_id) VALUES (2,'budget','country',10,'USD',1)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO work_financial (work_id, kind, scope, amount, currency, source_id) VALUES (2,'budget','worldwide',10,'DOLLARS',1)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO work_relation VALUES (1,1,'based_on',1,NULL)")
    conn.rollback()


def test_the_views_answer_real_cinema_questions(conn):
    assert rows(conn, "SELECT title, year, imdb_id, tmdb_id, wikidata_id, original_title FROM v_work WHERE work_id = 1") == [
        ("Sample One", 1982, "tt9000001", "9001", "Q9000001", "Sample One (original)")]
    # who directed what
    assert rows(conn, "SELECT work_title FROM v_credit WHERE person_name = 'Ann Director' AND role = 'director' ORDER BY work_year") == [("Sample One",), ("Sample Remake",)]
    # a series, its season and episode hang from each other
    assert rows(conn, "SELECT e.title, e.episode_number, s.title FROM v_work e JOIN v_work s ON s.work_id = e.parent_work_id WHERE e.kind = 'episode'") == [("Sample Episode", 1, "Sample Show, season 1")]
    # relations are readable from both sides
    assert rows(conn, "SELECT relation_label, related_title FROM v_work_relation WHERE work_id = 1 ORDER BY direction") == [("is based on", "Sample Novel"), ("is followed by", "Sample Remake")]
    assert rows(conn, "SELECT relation_label, related_title FROM v_work_relation WHERE work_id = 6") == [("is source of", "Sample One")]
    # the source novel's author and every work of the franchise
    assert rows(conn, "SELECT person_name FROM v_credit WHERE work_title = 'Sample Novel' AND role = 'author'") == [("Ann Director",)]
    assert [r[0] for r in rows(conn, "SELECT work_title FROM v_franchise WHERE franchise = 'Sample Saga' ORDER BY position")] == ["Sample One", "Sample Remake"]
    # awards, money, releases, genres
    assert rows(conn, "SELECT award, category, outcome, person_name FROM v_award_result WHERE work_title = 'Sample One' ORDER BY category") == [
        ("Sample Awards", "Best Director", "nominated", "Ann Director"), ("Sample Awards", "Best Picture", "won", None)]
    assert rows(conn, "SELECT kind, amount, currency FROM v_work_financial WHERE work_id = 1 ORDER BY kind") == [("box_office", 20000000, "USD"), ("budget", 1500000, "USD")]
    assert rows(conn, "SELECT iso2, release_date FROM v_work_release WHERE work_id = 1 ORDER BY iso2") == [("IT", "1982-12-01"), ("US", "1982-06-25")]
    # two source labels (a Wikidata item and a plain text) map to ONE canonical genre; the unmapped label is still readable
    assert [r[0] for r in rows(conn, "SELECT genre FROM v_work_genre WHERE work_id = 1 ORDER BY genre")] == ["Drama", "Horror"]
    assert rows(conn, "SELECT label_it, genre, mapping FROM v_work_genre_label WHERE work_id = 1 ORDER BY label_id") == [
        ("film horror", "Horror", "exact"), ("film drammatico", "Drama", "exact"), ("film strano", None, None), ("horror", "Horror", "synonym")]
    # alias lookup and reverse identifier lookup
    assert rows(conn, "SELECT entity_id FROM v_name WHERE name_norm = 'uno di prova'") == [(1,)]
    assert rows(conn, "SELECT entity_id, entity_type FROM v_external_id WHERE scheme = 'imdb_name' AND value = 'nm9000001'") == [(10, "person")]


def test_the_vocabularies_are_complete_and_every_role_is_listed(conn):
    assert {r[0] for r in rows(conn, "SELECT role FROM role_type")} == {r[0] for r in ROLES}
    assert {r[0] for r in rows(conn, "SELECT kind FROM work_kind")} >= {"film", "series", "season", "episode", "literary_work"}
    assert rows(conn, "SELECT count(*) FROM relation_type") == [(4,)]


def test_every_view_selects_and_the_public_list_matches(conn):
    names = [r[0] for r in rows(conn, "SELECT name FROM sqlite_master WHERE type='view' ORDER BY name")]
    assert names == sorted(PUBLIC_VIEWS)
    for v in names:
        conn.execute(f"SELECT * FROM {v} LIMIT 1").fetchall()


def test_the_builder_refuses_to_overwrite(tmp_path: Path):
    target = create_database(tmp_path / "a.sqlite3")
    with pytest.raises(FileExistsError):
        create_database(target)


def test_genres_keep_the_source_label_the_mapping_and_the_canonical_genre_apart(conn):
    # the canonical genre is reached only through the label a source used; an unmapped label is still visible
    assert rows(conn, "SELECT genre FROM v_work_genre WHERE work_id = 2") == [("Horror",)]
    assert rows(conn, "SELECT count(*) FROM v_work_genre WHERE work_id = 1 AND genre = 'Horror'") == [(1,)]  # two labels, one row
    assert rows(conn, "SELECT label_it, genre, mapping, rule FROM v_genre_label ORDER BY label_id") == [
        ("film horror", "Horror", "exact", "test"), ("film drammatico", "Drama", "exact", "test"), ("film strano", None, None, None), ("horror", "Horror", "synonym", "test")]
    assert rows(conn, "SELECT code FROM v_genre ORDER BY code") == [("drama",), ("horror",)]


def test_genre_constraints(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO genre (code, label_en, label_it, source_id) VALUES ('Horror Film','x','x',1)")  # code is lower-case letters and _
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO genre (code, label_en, label_it, source_id) VALUES ('horror','x','x',1)")  # unique
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO genre_label (label_norm, source_id) VALUES ('x',1)")  # a label needs text
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO genre_label_map VALUES (3,1,'close','r',1)")  # mapping kinds are closed
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO genre_label (wikidata_id, label_it, label_norm, source_id) VALUES ('Q200092','dup','dup',1)")  # one row per Wikidata item
    conn.rollback()


def test_the_fts_index_is_part_of_the_schema_and_is_not_kept_by_triggers(conn):
    assert rows(conn, "SELECT count(*) FROM sqlite_master WHERE type = 'trigger'") == [(0,)]
    assert rows(conn, "SELECT count(*) FROM entity_name_fts_docsize") == rows(conn, "SELECT count(*) FROM entity_name")
