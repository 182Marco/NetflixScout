"""Schema v3: the ADDITIVE tables of the phase-9 layer. Applied by `cinema_db/harness/build/imdb_layer.py` to a COPY of the v2 database.

Nothing here changes a v2 table, view or column. The v3 file is not read by the runtime tool: the approved-views policy
(`tool/cinema_db/approved_views.py`) is generated from the runtime file and must be regenerated, with the new views, before
`cinema_sql` may open a v3 file (phase F of the plan).

Why these four tables and no more:
- `work_rating`   one row per (work, source): several ratings of one film stay side by side, each with its own scale, vote count,
                  kind of voters and date. Never averaged, converted or overwritten.
- `entity_claim`  the alternative value that LOST a priority decision (year, runtime, kind, release date): the winner is in the
                  main column, the loser is kept here with its source, so no valid information is deleted.
- `external_id_candidate` an identifier that is suspected but NOT attached (weak match, conflict, shared by several entities):
                  visible and queryable, never used as a join key.
- `entity_canonical` (added by the reconciliation build) reversible merge map of persons, resolved by the public views.
- `work_status`   what the owner asked to always distinguish: how the work entered, how reliably it was identified, whether a plot
                  exists, how complete its data are.
"""
from __future__ import annotations

SCHEMA_VERSION_V3 = 3

TABLES_V3 = [
    """CREATE TABLE work_rating (
        work_id INTEGER NOT NULL REFERENCES work(work_id),
        source_id INTEGER NOT NULL REFERENCES source(source_id),
        value REAL NOT NULL CHECK (value >= 0),
        scale_max REAL NOT NULL CHECK (scale_max > 0),
        vote_count INTEGER CHECK (vote_count IS NULL OR vote_count >= 0),
        audience TEXT NOT NULL CHECK (audience IN ('audience','critics')),
        as_of TEXT NOT NULL CHECK (as_of GLOB '[0-9][0-9][0-9][0-9]*'),
        source_ref TEXT,
        PRIMARY KEY (work_id, source_id),
        CHECK (value <= scale_max)
    ) STRICT""",
    """CREATE TABLE entity_claim (
        entity_id INTEGER NOT NULL REFERENCES entity(entity_id),
        field TEXT NOT NULL CHECK (length(field) > 0),
        value TEXT NOT NULL,
        source_id INTEGER NOT NULL REFERENCES source(source_id),
        source_ref TEXT,
        retrieved_at TEXT,
        PRIMARY KEY (entity_id, field, source_id, value, source_ref)
    ) STRICT""",
    """CREATE TABLE external_id_candidate (
        entity_id INTEGER NOT NULL REFERENCES entity(entity_id),
        scheme TEXT NOT NULL REFERENCES id_scheme(scheme),
        value TEXT NOT NULL CHECK (length(value) > 0),
        tier TEXT NOT NULL CHECK (tier IN ('weak_single_title','conflict_birth_year','conflict_several_candidates','shared_by_several_entities',
                                           'name_and_birth_year_only','ids_reliable_false_unconfirmed','episode_number_only')),
        evidence TEXT,
        source_id INTEGER NOT NULL REFERENCES source(source_id),
        PRIMARY KEY (entity_id, scheme, value)
    ) STRICT""",
    """CREATE TABLE work_status (
        work_id INTEGER PRIMARY KEY REFERENCES work(work_id),
        entry_route TEXT NOT NULL CHECK (entry_route IN ('catalogue','imdb_movielens','imdb_itwiki_page','imdb_itwiki_page_rule','imdb_recovered_mixed_page','imdb_episode')),
        identification TEXT NOT NULL CHECK (identification IN ('catalogue','imdb_id_given_by_movielens','imdb_title_year_director_confirmed',
                                                                'imdb_title_year_unique','imdb_title_year_unique_director_mismatch','imdb_title_year_type_confirmed',
                                                                'imdb_episode_parent_id')),
        plot_status TEXT CHECK (plot_status IS NULL OR plot_status IN ('with_plot','without_plot')),
        completeness TEXT NOT NULL CHECK (completeness IN ('rich','basic','skeleton'))
    ) STRICT""",
    """CREATE TABLE entity_canonical (
        entity_id INTEGER PRIMARY KEY REFERENCES entity(entity_id),
        canonical_entity_id INTEGER NOT NULL REFERENCES entity(entity_id),
        reason TEXT NOT NULL,
        evidence TEXT,
        source_id INTEGER NOT NULL REFERENCES source(source_id),
        CHECK (entity_id <> canonical_entity_id)
    ) STRICT""",
]

INDEXES_V3 = [
    "CREATE INDEX work_rating_rank ON work_rating(source_id, value, vote_count)",
    "CREATE INDEX entity_claim_field ON entity_claim(field, entity_id)",
    "CREATE INDEX external_id_candidate_value ON external_id_candidate(scheme, value)",
    "CREATE INDEX work_status_route ON work_status(entry_route, completeness)",
    "CREATE INDEX entity_canonical_target ON entity_canonical(canonical_entity_id)",
]

# Descriptions for the schema documentation (kept next to the DDL so they cannot drift).
NOTES_V3 = {
    "work_rating": "One rating of a work by one source (IMDb users, MovieLens users, later critics): value on its own scale, number of votes, date. Several rows per work, never merged.",
    "entity_claim": "A valid value that lost a priority decision (for example a year or runtime from the catalogue where IMDb is primary). The winner stays in the main column.",
    "external_id_candidate": "An identifier suspected but not attached to the entity (weak match, conflict, shared). Never a join key.",
    "entity_canonical": "Reversible identity map: a row says this entity is the same real person as canonical_entity_id. Nothing is deleted or moved; the public views resolve credits, names and identifiers to the canonical entity. Deleting the row undoes the merge.",
    "work_status": "How a work entered the catalogue, how reliably it was identified, whether a plot exists and how complete its data are.",
}


# Public views redefined in v3 so that a merged person appears ONCE (as the canonical entity). Same names and columns as the v2 views: the
# approved-views policy is unaffected. Each is created by the layer after DROP VIEW of the v2 definition.
_CANON = "LEFT JOIN entity_canonical ec ON ec.entity_id = {key}"
_MEMBER_ID = ("COALESCE({own}, (SELECT x.value FROM external_id x JOIN entity_canonical m ON m.entity_id = x.entity_id "
              "WHERE m.canonical_entity_id = p.person_id AND x.scheme = '{scheme}' ORDER BY x.is_primary DESC, x.value LIMIT 1))")

VIEWS_V3: dict[str, str] = {
    "v_person": f"""CREATE VIEW v_person AS
        SELECT p.person_id AS person_id, n.name AS name, p.birth_date AS birth_date, p.birth_year AS birth_year,
               p.death_date AS death_date, p.death_year AS death_year, c.label_en AS birth_country,
               {_MEMBER_ID.format(own='imdb.value', scheme='imdb_name')} AS imdb_id,
               {_MEMBER_ID.format(own='tmdb.value', scheme='tmdb_person')} AS tmdb_id,
               {_MEMBER_ID.format(own='wd.value', scheme='wikidata')} AS wikidata_id,
               {_MEMBER_ID.format(own='wpit.value', scheme='wikipedia_it')} AS wikipedia_it,
               {_MEMBER_ID.format(own='wpen.value', scheme='wikipedia_en')} AS wikipedia_en, s.name AS source
        FROM person p
        LEFT JOIN entity_name n ON n.entity_id = p.person_id AND n.is_primary = 1
        LEFT JOIN country c ON c.country_id = p.birth_country_id
        LEFT JOIN external_id imdb ON imdb.entity_id = p.person_id AND imdb.scheme = 'imdb_name' AND imdb.is_primary = 1
        LEFT JOIN external_id tmdb ON tmdb.entity_id = p.person_id AND tmdb.scheme = 'tmdb_person' AND tmdb.is_primary = 1
        LEFT JOIN external_id wd ON wd.entity_id = p.person_id AND wd.scheme = 'wikidata' AND wd.is_primary = 1
        LEFT JOIN external_id wpit ON wpit.entity_id = p.person_id AND wpit.scheme = 'wikipedia_it' AND wpit.is_primary = 1
        LEFT JOIN external_id wpen ON wpen.entity_id = p.person_id AND wpen.scheme = 'wikipedia_en' AND wpen.is_primary = 1
        LEFT JOIN source s ON s.source_id = p.source_id
        WHERE p.person_id NOT IN (SELECT entity_id FROM entity_canonical)""",
    "v_name": f"""CREATE VIEW v_name AS
        SELECT COALESCE(ec.canonical_entity_id, e.entity_id) AS entity_id, e.entity_type AS entity_type, n.name AS name, n.name_norm AS name_norm,
               n.language AS language, n.kind AS name_kind, CASE WHEN ec.entity_id IS NULL THEN n.is_primary ELSE 0 END AS is_primary
        FROM entity_name n JOIN entity e ON e.entity_id = n.entity_id {_CANON.format(key='e.entity_id')}""",
    # Two branches, like v_credit (FASE 21): with COALESCE(canonical, entity_id) in the select list SQLite could not use `entity_id = ?` and scanned the whole table
    # (about 420 ms for ONE work, the cost of `provenance`). Branch 1: the identifiers of entities that are not merged. Branch 2: those of the merged entities, shown under
    # the canonical one and never as preferred. Same rows, same columns as the single-branch definition (compared row by row on the real file before adopting it).
    "v_external_id": """CREATE VIEW v_external_id AS
        SELECT x.entity_id AS entity_id, e.entity_type AS entity_type, x.scheme AS scheme, i.label AS scheme_label, x.value AS value, x.is_primary AS is_primary
        FROM external_id x JOIN entity e ON e.entity_id = x.entity_id JOIN id_scheme i ON i.scheme = x.scheme
        WHERE x.entity_id NOT IN (SELECT entity_id FROM entity_canonical)
        UNION ALL
        SELECT ec.canonical_entity_id, e.entity_type, x.scheme, i.label, x.value, 0
        FROM entity_canonical ec JOIN external_id x ON x.entity_id = ec.entity_id JOIN entity e ON e.entity_id = x.entity_id JOIN id_scheme i ON i.scheme = x.scheme""",
    # Two branches (not a COALESCE in the select list): `person_id = ?` then uses the credit_person index in each branch. With COALESCE(canonical, person_id) SQLite
    # scanned every work (2-4 s for a well-known person). Branch 1: credits of people who are not merged. Branch 2: credits of the merged people, shown under the
    # canonical person, unless that person already has the same credit (same work and role, same or no character).
    "v_credit": """CREATE VIEW v_credit AS
        SELECT c.credit_id AS credit_id, c.work_id AS work_id, wn.name AS work_title, w.release_year AS work_year,
               w.kind AS work_kind, c.person_id AS person_id, pn.name AS person_name, c.role AS role,
               r.department AS department, r.is_cast AS is_cast, c.character_name AS character_name,
               c.billing_order AS billing_order, c.credit_note AS credit_note, s.name AS source
        FROM credit c JOIN work w ON w.work_id = c.work_id JOIN role_type r ON r.role = c.role
        LEFT JOIN entity_name wn ON wn.entity_id = c.work_id AND wn.is_primary = 1
        LEFT JOIN entity_name pn ON pn.entity_id = c.person_id AND pn.is_primary = 1
        LEFT JOIN source s ON s.source_id = c.source_id
        WHERE c.person_id NOT IN (SELECT entity_id FROM entity_canonical)
        UNION ALL
        SELECT c.credit_id, c.work_id, wn.name, w.release_year, w.kind, ec.canonical_entity_id, pn.name, c.role,
               r.department, r.is_cast, c.character_name, c.billing_order, c.credit_note, s.name
        FROM entity_canonical ec JOIN credit c ON c.person_id = ec.entity_id
        JOIN work w ON w.work_id = c.work_id JOIN role_type r ON r.role = c.role
        LEFT JOIN entity_name wn ON wn.entity_id = c.work_id AND wn.is_primary = 1
        LEFT JOIN entity_name pn ON pn.entity_id = ec.canonical_entity_id AND pn.is_primary = 1
        LEFT JOIN source s ON s.source_id = c.source_id
        WHERE NOT EXISTS (
              SELECT 1 FROM credit k WHERE k.person_id = ec.canonical_entity_id AND k.work_id = c.work_id AND k.role = c.role
                 AND (c.character_name IS NULL OR COALESCE(k.character_name, '') = c.character_name))""",
    "v_award_result": """CREATE VIEW v_award_result AS
        SELECT r.result_id AS result_id, an.name AS award, ac.name AS category, ac.scope AS category_scope,
               ce.year AS ceremony_year, ce.edition AS ceremony_edition, r.outcome AS outcome,
               r.work_id AS work_id, wn.name AS work_title, w.release_year AS work_year, COALESCE(ec.canonical_entity_id, r.person_id) AS person_id,
               pn.name AS person_name, r.note AS note, s.name AS source
        FROM award_result r JOIN ceremony ce ON ce.ceremony_id = r.ceremony_id JOIN award_category ac ON ac.category_id = r.category_id
        LEFT JOIN entity_name an ON an.entity_id = ac.award_id AND an.is_primary = 1
        LEFT JOIN work w ON w.work_id = r.work_id LEFT JOIN entity_name wn ON wn.entity_id = r.work_id AND wn.is_primary = 1
        LEFT JOIN entity_canonical ec ON ec.entity_id = r.person_id
        LEFT JOIN entity_name pn ON pn.entity_id = COALESCE(ec.canonical_entity_id, r.person_id) AND pn.is_primary = 1
        LEFT JOIN source s ON s.source_id = r.source_id""",
    "v_title_search": f"""CREATE VIEW v_title_search AS
        SELECT COALESCE(ec.canonical_entity_id, n.entity_id) AS entity_id, e.entity_type AS entity_type, n.name AS name, n.kind AS name_kind, n.language AS language,
               CASE WHEN ec.entity_id IS NULL THEN n.is_primary ELSE 0 END AS is_primary, w.kind AS work_kind, w.release_year AS work_year,
               entity_name_fts.rank AS rank, entity_name_fts.name AS search
        FROM entity_name_fts JOIN entity_name n ON n.name_id = entity_name_fts.rowid JOIN entity e ON e.entity_id = n.entity_id
        {_CANON.format(key='n.entity_id')}
        LEFT JOIN work w ON w.work_id = n.entity_id""",
}

# NEW public views (created, not redefined). v_work_status: how reliably each work was identified, so a query can separate verified identities from the rest.
#   verified   : the catalogue, an IMDb id given by MovieLens, title+year+director confirmed, type confirmed, or an episode linked by IMDb ids
#   rule_based : entered by the unique-title rule (one IMDb title within a year); measured precision 99.8 % films / 98.3 % shorts, on pages WITH a known id
#   uncertain  : same rule, but the Italian page names a director IMDb does not list for that title
NEW_VIEWS_V3: dict[str, str] = {
    "v_work_status": """CREATE VIEW v_work_status AS
        SELECT s.work_id AS work_id, n.name AS work_title, w.release_year AS work_year, w.kind AS work_kind, s.entry_route AS entry_route,
               s.identification AS identification,
               CASE s.identification WHEN 'imdb_title_year_unique' THEN 'rule_based' WHEN 'imdb_title_year_unique_director_mismatch' THEN 'uncertain' ELSE 'verified' END AS identity_level,
               s.plot_status AS plot_status, s.completeness AS completeness
        FROM work_status s JOIN work w ON w.work_id = s.work_id
        LEFT JOIN entity_name n ON n.entity_id = s.work_id AND n.is_primary = 1""",
    "v_work_rating": """CREATE VIEW v_work_rating AS
        SELECT r.work_id AS work_id, n.name AS work_title, w.release_year AS work_year, w.kind AS work_kind, s.name AS source, r.audience AS audience,
               r.value AS rating, r.scale_max AS scale_max, r.vote_count AS vote_count, r.as_of AS as_of
        FROM work_rating r JOIN work w ON w.work_id = r.work_id
        LEFT JOIN entity_name n ON n.entity_id = r.work_id AND n.is_primary = 1 LEFT JOIN source s ON s.source_id = r.source_id""",
    "v_entity_claim": """CREATE VIEW v_entity_claim AS
        SELECT k.entity_id AS entity_id, e.entity_type AS entity_type, n.name AS name, k.field AS field, k.value AS value, s.name AS source,
               k.source_ref AS source_ref, k.retrieved_at AS retrieved_at
        FROM entity_claim k JOIN entity e ON e.entity_id = k.entity_id
        LEFT JOIN entity_name n ON n.entity_id = k.entity_id AND n.is_primary = 1 LEFT JOIN source s ON s.source_id = k.source_id""",
    "v_external_id_candidate": """CREATE VIEW v_external_id_candidate AS
        SELECT c.entity_id AS entity_id, e.entity_type AS entity_type, n.name AS name, c.scheme AS scheme, c.value AS value, c.tier AS tier,
               c.evidence AS evidence, s.name AS source
        FROM external_id_candidate c JOIN entity e ON e.entity_id = c.entity_id
        LEFT JOIN entity_name n ON n.entity_id = c.entity_id AND n.is_primary = 1 LEFT JOIN source s ON s.source_id = c.source_id""",
    "v_entity_canonical": """CREATE VIEW v_entity_canonical AS
        SELECT m.entity_id AS merged_entity_id, mn.name AS merged_name, m.canonical_entity_id AS canonical_entity_id, cn.name AS canonical_name,
               m.reason AS reason, m.evidence AS evidence, s.name AS source
        FROM entity_canonical m
        LEFT JOIN entity_name mn ON mn.entity_id = m.entity_id AND mn.is_primary = 1
        LEFT JOIN entity_name cn ON cn.entity_id = m.canonical_entity_id AND cn.is_primary = 1 LEFT JOIN source s ON s.source_id = m.source_id""",
}


SCHEMA_VERSION_ML = 4  # the v3 layer plus the MovieLens tables below (a different policy: approved_views_v4.py); a file of schema 3 is untouched

# Schema 4 = schema 3 + MovieLens (decision of the owner, 2026-11-09): films, genres and tags of MovieLens 32M, so the separate MovieLens database is no longer needed
# to answer rankings, title search, tag search and genre statistics. Source rows (individual ratings, users, dates) stay in the MovieLens file.
TABLES_ML = [
    """CREATE TABLE ml_movie (
        movie_id INTEGER PRIMARY KEY,
        imdb_id TEXT,
        ml_title TEXT NOT NULL,
        ml_year INTEGER,
        n_ratings INTEGER NOT NULL CHECK (n_ratings >= 0),
        avg_rating REAL CHECK (avg_rating IS NULL OR (avg_rating >= 0 AND avg_rating <= 5)),
        work_id INTEGER REFERENCES work(work_id),
        reason TEXT,
        CHECK ((work_id IS NULL) = (reason IS NOT NULL)),
        CHECK ((n_ratings = 0) = (avg_rating IS NULL))
    ) STRICT""",
    """CREATE TABLE ml_genre (
        ml_genre_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE
    ) STRICT""",
    """CREATE TABLE work_ml_genre (
        work_id INTEGER NOT NULL REFERENCES work(work_id),
        ml_genre_id INTEGER NOT NULL REFERENCES ml_genre(ml_genre_id),
        PRIMARY KEY (ml_genre_id, work_id)
    ) STRICT""",
    """CREATE TABLE work_tag (
        tag_norm TEXT NOT NULL CHECK (length(tag_norm) > 0),
        work_id INTEGER NOT NULL REFERENCES work(work_id),
        n_users INTEGER NOT NULL CHECK (n_users > 0),
        PRIMARY KEY (tag_norm, work_id)
    ) STRICT""",
]

# Each index below was added because a measurement showed the gain (2026-11-09, candidate4, 7 runs each): most_rated 108 -> 0.2 ms with ml_movie_count; top_rated with the default
# minimum (50 ratings) 108 -> 0.1 ms with the partial ml_movie_top (the query writes the minimum as a literal so the planner can use it). Others (genre, years, title, tag) did not gain.
INDEXES_ML = [
    "CREATE UNIQUE INDEX ml_movie_work ON ml_movie(work_id) WHERE work_id IS NOT NULL",
    "CREATE INDEX ml_movie_count ON ml_movie(n_ratings DESC, avg_rating DESC, movie_id)",
    "CREATE INDEX ml_movie_top ON ml_movie(avg_rating DESC, n_ratings DESC, movie_id) WHERE n_ratings >= 50 AND work_id IS NOT NULL",
]

NOTES_ML = {
    "ml_movie": "Every film of MovieLens 32M: its own id, title, year, number of ratings and mean (1-5), the work it is, or the verifiable reason it is not in the catalogue. Nothing is guessed: no identifier, no match.",
    "ml_genre": "The genres of MovieLens (19). They are NOT the IMDb/Wikidata genres of `work_genre`: MovieLens classifies by its own list.",
    "work_ml_genre": "The MovieLens genres of a work, as MovieLens gives them (a film can have several, or none).",
    "work_tag": "MovieLens tags: how many distinct users gave the tag (normalised: lower case, single spaces) to the work. No user, no date.",
}

VIEWS_ML: dict[str, str] = {}
VIEWS_ML["v_ml_movie"] = """CREATE VIEW v_ml_movie AS
        SELECT m.movie_id AS movie_id, m.work_id AS work_id, n.name AS work_title, w.release_year AS work_year, w.kind AS work_kind,
               m.imdb_id AS imdb_id, m.ml_title AS ml_title, m.ml_year AS ml_year, m.avg_rating AS avg_rating, m.n_ratings AS n_ratings,
               CASE WHEN m.work_id IS NULL THEN 'excluded' ELSE 'in_catalogue' END AS status, m.reason AS reason
        FROM ml_movie m LEFT JOIN work w ON w.work_id = m.work_id
        LEFT JOIN entity_name n ON n.entity_id = m.work_id AND n.is_primary = 1"""
VIEWS_ML["v_ml_genre"] = """CREATE VIEW v_ml_genre AS
        SELECT x.work_id AS work_id, g.name AS genre FROM work_ml_genre x JOIN ml_genre g ON g.ml_genre_id = x.ml_genre_id"""
VIEWS_ML["v_work_tag"] = """CREATE VIEW v_work_tag AS
        SELECT t.work_id AS work_id, t.tag_norm AS tag, t.n_users AS n_users FROM work_tag t"""


def create_v3_schema_only(path, *, movielens: bool = False):
    """A v3 database with the structure and no rows: the v2 schema, the additive tables, the redefined views and the new ones. Used to generate the
    approved-view policy of the v3 file (`tool/cinema_db/approved_views_v3.py`) without the 1 GB file; the builder applies the same definitions."""
    import sqlite3

    from cinema_db.schema import create_database

    path = create_database(path)
    conn = sqlite3.connect(path)
    try:
        for ddl in TABLES_V3 + INDEXES_V3:
            conn.execute(ddl)
        for name, ddl in VIEWS_V3.items():
            conn.execute(f"DROP VIEW {name}")
            conn.execute(ddl)
        for ddl in NEW_VIEWS_V3.values():
            conn.execute(ddl)
        if movielens:
            for ddl in TABLES_ML + INDEXES_ML + list(VIEWS_ML.values()):
                conn.execute(ddl)
        conn.execute("INSERT OR REPLACE INTO build_info VALUES ('schema_version', ?)", (str(SCHEMA_VERSION_ML if movielens else SCHEMA_VERSION_V3),))
        conn.commit()
    finally:
        conn.close()
    return path


