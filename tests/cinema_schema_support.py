"""Builds the REAL cinema schema in a temp folder and seeds it with a few INVENTED rows (tests only; the product database
never contains invented data). Ids are small integers; names are obviously fake."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from cinema_db.schema import create_database, rebuild_fts


def build_real(path: Path, *, seed: bool = True) -> Path:
    create_database(path)
    if seed:
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA foreign_keys = ON")
        seed_rows(conn)
        conn.commit()
        conn.close()
    return path


def _entity(conn, eid: int, etype: str, name: str, *, language: str | None = None):
    conn.execute("INSERT INTO entity VALUES (?,?)", (eid, etype))
    conn.execute(
        "INSERT INTO entity_name (entity_id, name, name_norm, language, kind, is_primary, source_id) VALUES (?,?,?,?, 'primary', 1, 1)",
        (eid, name, name.lower(), language),
    )


def seed_rows(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO source VALUES (1,'test-wikidata','wikidata','https://example.test','CC0','https://example.test/cc0','open_public_domain',0,NULL,'invented test row','snap-1','00','2026-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO source VALUES (2,'test-wikipedia','wikipedia','https://example.test','CC BY-SA 4.0','https://example.test/sa','open_share_alike',1,'Text from Wikipedia','invented test row','snap-2','SECRET-HASH','2026-01-02T00:00:00Z')"
    )
    conn.execute("INSERT INTO country VALUES (1,'US','United States','Stati Uniti','Q30',1),(2,'IT','Italy','Italia','Q38',1)")
    conn.execute("INSERT INTO language VALUES (1,'en','eng','English','inglese','Q1860',1)")
    conn.execute("INSERT INTO genre VALUES (1,'horror','Horror','Horror',NULL,'Fear-driven films.',1),(2,'drama','Drama','Drammatico',NULL,'Serious narrative films.',1)")
    conn.execute("INSERT INTO genre_label (label_id, wikidata_id, label_it, label_en, label_norm, source_id) VALUES (1,'Q200092','film horror','horror film','film horror',1),(2,'Q130232','film drammatico','drama film','film drammatico',1),(3,'Q9999','film strano',NULL,'film strano',1),(4,NULL,'horror',NULL,'horror',1)")
    conn.execute("INSERT INTO genre_label_map VALUES (1,1,'exact','test',1),(2,2,'exact','test',1),(4,1,'synonym','test',1)")
    _entity(conn, 1, "work", "Sample One")
    _entity(conn, 2, "work", "Sample Remake")
    _entity(conn, 3, "work", "Sample Show")
    _entity(conn, 4, "work", "Sample Show, season 1")
    _entity(conn, 5, "work", "Sample Episode")
    _entity(conn, 6, "work", "Sample Novel")
    _entity(conn, 10, "person", "Ann Director")
    _entity(conn, 11, "person", "Bob Actor")
    _entity(conn, 20, "company", "Sample Pictures")
    _entity(conn, 30, "franchise", "Sample Saga")
    _entity(conn, 40, "award", "Sample Awards")
    w = "INSERT INTO work (work_id, kind, parent_work_id, season_number, episode_number, release_date, release_year, runtime_min, status, source_id, source_ref) VALUES (?,?,?,?,?,?,?,?,?,1,'Q-test')"
    conn.execute(w, (1, "film", None, None, None, "1982-06-25", 1982, 109, "released"))
    conn.execute(w, (2, "film", None, None, None, "2017", 2017, 117, "released"))
    conn.execute(w, (3, "series", None, None, None, "2016-07-15", 2016, None, "ended"))
    conn.execute(w, (4, "season", 3, 1, None, "2016-07-15", 2016, None, None))
    conn.execute(w, (5, "episode", 4, 1, 1, "2016-07-15", 2016, 48, None))
    conn.execute(w, (6, "literary_work", None, None, None, "1938", 1938, None, None))
    conn.execute("INSERT INTO person (person_id, birth_date, birth_year, birth_country_id, source_id) VALUES (10,'1948-01-02',1948,1,1),(11,'1960',1960,2,1)")
    conn.execute("INSERT INTO company (company_id, country_id, source_id) VALUES (20,1,1)")
    conn.execute("INSERT INTO franchise (franchise_id, source_id) VALUES (30,1)")
    conn.execute("INSERT INTO award (award_id, country_id, source_id) VALUES (40,1,1)")
    n = "INSERT INTO entity_name (entity_id, name, name_norm, language, kind, is_primary, source_id) VALUES (?,?,?,?,?,0,1)"
    conn.execute(n, (1, "Uno di prova", "uno di prova", "it", "translated"))
    conn.execute(n, (1, "Sample One (original)", "sample one (original)", "en", "original"))
    ext = "INSERT INTO external_id (entity_id, scheme, value, is_primary, source_id) VALUES (?,?,?,1,1)"
    for row in [(1, "imdb_title", "tt9000001"), (1, "tmdb_movie", "9001"), (1, "wikidata", "Q9000001"), (1, "wikipedia_it", "Sample_One"),
                (2, "imdb_title", "tt9000002"), (3, "tvmaze_show", "77"), (10, "imdb_name", "nm9000001"), (10, "wikidata", "Q9000010")]:
        conn.execute(ext, row)
    c = "INSERT INTO credit (work_id, person_id, role, character_name, billing_order, source_id) VALUES (?,?,?,?,?,1)"
    conn.execute(c, (1, 10, "director", None, None))
    conn.execute(c, (1, 11, "cast", "Hero", 1))
    conn.execute(c, (2, 10, "director", None, None))
    conn.execute(c, (6, 10, "author", None, None))
    conn.execute("INSERT INTO work_genre VALUES (1,1,1,NULL),(1,4,1,NULL),(1,2,1,NULL),(1,3,1,NULL),(2,1,1,NULL)")  # work 1: horror twice (two labels), drama, one unmapped label
    conn.execute("INSERT INTO work_country VALUES (1,1,'origin',1,NULL),(2,1,'origin',1,NULL),(1,2,'production',1,NULL)")
    conn.execute("INSERT INTO work_language VALUES (1,1,'original',1,NULL)")
    conn.execute("INSERT INTO work_company VALUES (1,20,'production',1,NULL)")
    conn.execute("INSERT INTO work_franchise VALUES (1,30,1,'wikidata_franchise',1,NULL),(2,30,2,'wikidata_franchise',1,NULL)")
    conn.execute("INSERT INTO work_relation VALUES (1,6,'based_on',1,NULL),(2,1,'follows',1,NULL)")
    conn.execute("INSERT INTO work_release (work_id, country_id, release_date, kind, source_id) VALUES (1,1,'1982-06-25','theatrical',1),(1,2,'1982-12-01','theatrical',1)")
    conn.execute("INSERT INTO work_financial (work_id, kind, scope, country_id, amount, currency, reference_year, source_id) VALUES (1,'budget','unspecified',NULL,1500000,'USD',1982,1),(1,'box_office','worldwide',NULL,20000000,'USD',NULL,1)")
    conn.execute("INSERT INTO award_category (category_id, award_id, name, name_norm, scope, source_id) VALUES (1,40,'Best Picture','best picture','work',1),(2,40,'Best Director','best director','person_for_work',1)")
    conn.execute("INSERT INTO ceremony (ceremony_id, award_id, year, edition, source_id) VALUES (1,40,1983,'1st',1)")
    conn.execute("INSERT INTO award_result (ceremony_id, category_id, work_id, person_id, outcome, source_id) VALUES (1,1,1,NULL,'won',1),(1,2,1,10,'nominated',1)")
    rebuild_fts(conn)
