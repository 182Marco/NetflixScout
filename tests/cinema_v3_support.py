"""A miniature schema-3 cinema database (invented data) built on the real v3 structure, to test `cinema_sql` against the views that only the v3 file has."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from cinema_db import schema as S2
from cinema_db.schema_v3 import create_v3_schema_only


def build_v3(path: Path, *, movielens: bool = False) -> Path:
    create_v3_schema_only(path, movielens=movielens)
    c = sqlite3.connect(path)
    c.execute("PRAGMA foreign_keys = OFF")
    for sid, name, kind in ((1, "wikidata-snapshot", "wikidata"), (2, "imdb-datasets", "imdb"), (3, "movielens-32m-aggregates", "dataset")):
        c.execute("INSERT INTO source (source_id, name, kind, license, usage_scope, attribution_required) VALUES (?,?,?,'x','unverified',0)", (sid, name, kind))

    def entity(eid, typ):
        c.execute("INSERT INTO entity VALUES (?,?)", (eid, typ))

    def name(eid, text, kind="primary", prim=1):
        c.execute("INSERT INTO entity_name (entity_id, name, name_norm, kind, is_primary, source_id) VALUES (?,?,?,?,?,1)", (eid, text, " ".join(text.casefold().split()), kind, prim))

    def work(wid, title, kind, year, level, imdb=None, parent=None, season=None, number=None, route="catalogue", ident="catalogue", runtime=None):
        entity(wid, "work")
        c.execute("INSERT INTO work (work_id, kind, parent_work_id, season_number, episode_number, release_year, runtime_min, source_id) VALUES (?,?,?,?,?,?,?,1)", (wid, kind, parent, season, number, year, runtime))
        name(wid, title)
        for i, (t, prim) in enumerate(imdb or []):
            c.execute("INSERT INTO external_id (entity_id, scheme, value, is_primary, source_id) VALUES (?, 'imdb_title', ?, ?, 2)", (wid, t, prim))
        c.execute("INSERT INTO work_status VALUES (?,?,?,NULL,'basic')", (wid, route, ident))

    def person(pid, text, birth=None):
        entity(pid, "person")
        c.execute("INSERT INTO person (person_id, birth_year, source_id) VALUES (?,?,1)", (pid, birth))
        name(pid, text)

    def credit(w, p, role, order=None, character=None):
        c.execute("INSERT INTO credit (work_id, person_id, role, character_name, billing_order, source_id) VALUES (?,?,?,?,?,2)", (w, p, role, character, order))

    work(101, "Alpha Film", "film", 2000, "verified", [("tt0000101", 1)], runtime=100)
    work(102, "Beta Film", "film", 2001, "uncertain", [("tt0000102", 1)], route="imdb_itwiki_page_rule", ident="imdb_title_year_unique_director_mismatch")
    work(103, "Gamma Film", "film", 2002, "rule_based", [("tt0000103", 1)], route="imdb_itwiki_page_rule", ident="imdb_title_year_unique")
    work(104, "Dup Film", "film", 2010, "verified", [("tt0000104", 1), ("tt0000105", 0)])
    work(105, "Homonym", "film", 1990, "verified", [("tt0000106", 1)])
    work(106, "Homonym", "film", 1991, "uncertain", [("tt0000107", 1)], route="imdb_itwiki_page_rule", ident="imdb_title_year_unique_director_mismatch")
    work(110, "Show", "series", 2010, "verified", [("tt0000110", 1)])
    work(111, "Show S1", "season", 2010, "verified", parent=110, season=1)
    work(112, "Pilot", "episode", 2010, "verified", [("tt0000112", 1)], parent=111, season=1, number=1, route="imdb_episode", ident="imdb_episode_parent_id")
    for pid, text, birth in ((201, "Ann Director", 1950), (202, "Bob Actor", 1960), (203, "Cy Merged", None), (204, "Cy Merged", 1970), (205, "Dee Newcomer", None)):
        person(pid, text, birth)
    credit(101, 201, "director")
    credit(101, 202, "cast", 1, "Hero")
    credit(101, 203, "cast", 2, "Friend")   # the merged person and the canonical one both have a credit on the same film and role
    credit(101, 204, "cast", 2, "Friend")
    credit(103, 204, "cast")
    credit(104, 205, "director")
    c.execute("INSERT INTO entity_canonical VALUES (203, 204, 'same_person_confirmed_by_imdb_id_and_consistent_dates', '{\"imdb\":\"nm1\"}', 2)")
    c.execute("INSERT INTO external_id (entity_id, scheme, value, is_primary, source_id) VALUES (204, 'imdb_name', 'nm1', 1, 2)")
    c.execute("INSERT INTO external_id (entity_id, scheme, value, is_primary, source_id) VALUES (203, 'wikidata', 'Q203', 1, 1)")
    for w, src, val, scale, votes in ((101, 2, 7.5, 10, 5000), (101, 3, 4.0, 5, 900), (104, 2, 8.0, 10, 1000), (103, 2, 6.0, 10, 50), (102, 2, 9.0, 10, 20)):
        c.execute("INSERT INTO work_rating VALUES (?,?,?,?,?,'audience','2026-11-08','ref')", (w, src, val, scale, votes))
    for field, value, ref in (("imdb_alt_title_type", "short", "tt0000105"), ("imdb_alt_release_year", "1999", "tt0000105"), ("imdb_title_previous_primary", "tt0000105", "tt0000105")):
        c.execute("INSERT INTO entity_claim VALUES (104,?,?,2,?,NULL)", (field, value, ref))
    c.execute("INSERT INTO entity_claim VALUES (102,'wikipedia_it_page_director_conflict','Zed Q',2,'page_id=9',NULL)")
    c.execute("INSERT INTO external_id_candidate VALUES (204,'imdb_name','nm9','weak_single_title','title matches: 1; birth cinema 1970 imdb None',2)")
    if movielens:  # schema 4: MovieLens films 1-6 = works 101, 103, 104, 110 (a series), 112 (an episode); 7 = a MovieLens film that is not in the catalogue
        c.execute("UPDATE build_info SET value = '4' WHERE key = 'schema_version'")
        c.executemany("INSERT INTO ml_movie VALUES (?,?,?,?,?,?,?,?)", [
            (1, "tt0000101", "Alpha Film", 2000, 900, 4.0, 101, None), (2, "tt0000103", "Film, The Gamma", 2002, 60, 3.5, 103, None),
            (3, "tt0000104", "Dup Film", 2010, 40, 4.5, 104, None), (4, "tt0000110", "Show", 2010, 500, 4.8, 110, None),
            (5, "tt0000112", "Pilot", 2010, 70, 3.0, 112, None), (6, "tt0000199", "Gone_Film 100%", 2005, 200, 3.9, None, "outside_entry_rule:video")])
        c.executemany("INSERT INTO ml_genre VALUES (?,?)", [(1, "Comedy"), (2, "Drama"), (3, "Sci-Fi")])
        c.executemany("INSERT INTO work_ml_genre VALUES (?,?)", [(101, 1), (101, 2), (103, 2), (104, 3), (110, 2)])
        c.executemany("INSERT INTO work_tag VALUES (?,?,?)", [("funny", 101, 5), ("funny", 104, 7), ("funny", 110, 9), ("twist", 103, 2)])
    S2.rebuild_fts(c)
    c.commit()
    c.close()
    return path
