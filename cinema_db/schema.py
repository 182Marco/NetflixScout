"""Relational schema of the local cinema database: tables, reference vocabularies and the PUBLIC VIEWS.

Single source of the structure. The ingestion (phase 3+) creates the file from `create_database`; the generated
documentation (schema.html, schema.mmd) and the approved-view policy of the SQL tool are derived from the SQLite
file that results, never from this text. No data is invented here: the only rows are definitional vocabularies
(kinds of work, professional roles, relation types, identifier schemes).

Design rules (see docs/cinema_db/PLAN.md §16):
  * one `entity` supertype gives every work, person, company, franchise and award a key that names, external ids and
    field provenance can reference with a real foreign key (the composite FK (id, entity_type) keeps the subtype honest);
  * film, series, season, episode and non-screen source works (novel, comic, game) are ALL `work` rows: relations,
    credits and identifiers need no special cases, hierarchy is `parent_work_id`;
  * no JSON columns: every many-to-many fact is a junction table with its own `source_id`;
  * every fact row names its source (`source_id`, `source_ref`); `field_provenance` records the origin of a single
    column when it differs from the row's source (a gap filled from a secondary source).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 2

# --- tables ---------------------------------------------------------------------------------------------------

TABLES: tuple[str, ...] = (
    # provenance and build
    """CREATE TABLE source (
        source_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        kind TEXT NOT NULL CHECK (kind IN ('wikidata','wikipedia','imdb','dataset','manual','derived')),
        url TEXT,
        license TEXT NOT NULL,
        license_url TEXT,
        usage_scope TEXT NOT NULL CHECK (usage_scope IN ('open_public_domain','open_attribution','open_share_alike','non_commercial','unverified')),
        attribution_required INTEGER NOT NULL CHECK (attribution_required IN (0,1)),
        attribution_text TEXT,
        terms_note TEXT,
        snapshot_label TEXT,
        snapshot_sha256 TEXT,
        retrieved_at TEXT
    ) STRICT""",
    """CREATE TABLE build_info (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    ) STRICT""",
    # definitional vocabularies
    """CREATE TABLE work_kind (
        kind TEXT PRIMARY KEY,
        medium TEXT NOT NULL CHECK (medium IN ('screen','literary','game','comic','stage','other')),
        label_en TEXT NOT NULL,
        label_it TEXT NOT NULL
    ) STRICT""",
    """CREATE TABLE role_type (
        role TEXT PRIMARY KEY,
        department TEXT NOT NULL CHECK (department IN ('direction','writing','cast','production','music','camera','editing','design','other')),
        is_cast INTEGER NOT NULL CHECK (is_cast IN (0,1)),
        label_en TEXT NOT NULL,
        label_it TEXT NOT NULL
    ) STRICT""",
    """CREATE TABLE relation_type (
        relation TEXT PRIMARY KEY,
        inverse_label TEXT NOT NULL,
        label_en TEXT NOT NULL,
        description TEXT NOT NULL
    ) STRICT""",
    """CREATE TABLE id_scheme (
        scheme TEXT PRIMARY KEY,
        label TEXT NOT NULL,
        entity_type TEXT CHECK (entity_type IN ('work','person','company','franchise','award')),
        url_template TEXT
    ) STRICT""",
    # lookups filled from sources
    """CREATE TABLE genre (
        genre_id INTEGER PRIMARY KEY,
        code TEXT NOT NULL UNIQUE CHECK (code GLOB '[a-z]*' AND code NOT GLOB '*[^a-z_]*'),
        label_en TEXT NOT NULL,
        label_it TEXT NOT NULL,
        parent_genre_id INTEGER REFERENCES genre(genre_id),
        description TEXT,
        source_id INTEGER NOT NULL REFERENCES source(source_id),
        CHECK (parent_genre_id IS NULL OR parent_genre_id <> genre_id)
    ) STRICT""",
    """CREATE TABLE genre_label (
        label_id INTEGER PRIMARY KEY,
        wikidata_id TEXT UNIQUE,
        label_it TEXT,
        label_en TEXT,
        label_norm TEXT NOT NULL CHECK (length(label_norm) > 0),
        source_id INTEGER NOT NULL REFERENCES source(source_id),
        source_ref TEXT,
        CHECK (label_it IS NOT NULL OR label_en IS NOT NULL)
    ) STRICT""",
    """CREATE TABLE genre_label_map (
        label_id INTEGER NOT NULL REFERENCES genre_label(label_id),
        genre_id INTEGER NOT NULL REFERENCES genre(genre_id),
        mapping TEXT NOT NULL CHECK (mapping IN ('exact','synonym','specific')),
        rule TEXT NOT NULL,
        source_id INTEGER NOT NULL REFERENCES source(source_id),
        PRIMARY KEY (label_id, genre_id)
    ) STRICT""",
    """CREATE TABLE country (
        country_id INTEGER PRIMARY KEY,
        iso2 TEXT UNIQUE CHECK (iso2 IS NULL OR length(iso2) = 2),
        label_en TEXT NOT NULL,
        label_it TEXT,
        wikidata_id TEXT UNIQUE,
        source_id INTEGER NOT NULL REFERENCES source(source_id)
    ) STRICT""",
    """CREATE TABLE language (
        language_id INTEGER PRIMARY KEY,
        iso639_1 TEXT UNIQUE CHECK (iso639_1 IS NULL OR length(iso639_1) = 2),
        iso639_3 TEXT,
        label_en TEXT NOT NULL,
        label_it TEXT,
        wikidata_id TEXT UNIQUE,
        source_id INTEGER NOT NULL REFERENCES source(source_id)
    ) STRICT""",
    # entities
    """CREATE TABLE entity (
        entity_id INTEGER PRIMARY KEY,
        entity_type TEXT NOT NULL CHECK (entity_type IN ('work','person','company','franchise','award')),
        UNIQUE (entity_id, entity_type)
    ) STRICT""",
    """CREATE TABLE work (
        work_id INTEGER PRIMARY KEY,
        entity_type TEXT NOT NULL DEFAULT 'work' CHECK (entity_type = 'work'),
        kind TEXT NOT NULL REFERENCES work_kind(kind),
        parent_work_id INTEGER REFERENCES work(work_id),
        season_number INTEGER CHECK (season_number IS NULL OR season_number >= 0),
        episode_number INTEGER CHECK (episode_number IS NULL OR episode_number >= 0),
        release_date TEXT CHECK (release_date IS NULL OR release_date GLOB '[0-9][0-9][0-9][0-9]*'),
        release_year INTEGER CHECK (release_year IS NULL OR release_year BETWEEN 1800 AND 2100),
        end_date TEXT CHECK (end_date IS NULL OR end_date GLOB '[0-9][0-9][0-9][0-9]*'),
        end_year INTEGER CHECK (end_year IS NULL OR end_year BETWEEN 1800 AND 2100),
        runtime_min INTEGER CHECK (runtime_min IS NULL OR runtime_min BETWEEN 1 AND 3000),
        status TEXT CHECK (status IS NULL OR status IN ('released','in_production','announced','cancelled','ongoing','ended','unreleased')),
        source_id INTEGER NOT NULL REFERENCES source(source_id),
        source_ref TEXT,
        FOREIGN KEY (work_id, entity_type) REFERENCES entity(entity_id, entity_type),
        CHECK (kind NOT IN ('season','episode') OR parent_work_id IS NOT NULL),
        CHECK (kind <> 'episode' OR parent_work_id IS NOT NULL),
        CHECK (episode_number IS NULL OR kind = 'episode'),
        CHECK (season_number IS NULL OR kind IN ('season','episode')),
        CHECK (parent_work_id IS NULL OR parent_work_id <> work_id)
    ) STRICT""",
    """CREATE TABLE person (
        person_id INTEGER PRIMARY KEY,
        entity_type TEXT NOT NULL DEFAULT 'person' CHECK (entity_type = 'person'),
        birth_date TEXT CHECK (birth_date IS NULL OR birth_date GLOB '[0-9][0-9][0-9][0-9]*'),
        birth_year INTEGER CHECK (birth_year IS NULL OR birth_year BETWEEN 1000 AND 2100),
        death_date TEXT CHECK (death_date IS NULL OR death_date GLOB '[0-9][0-9][0-9][0-9]*'),
        death_year INTEGER CHECK (death_year IS NULL OR death_year BETWEEN 1000 AND 2100),
        birth_country_id INTEGER REFERENCES country(country_id),
        source_id INTEGER NOT NULL REFERENCES source(source_id),
        source_ref TEXT,
        FOREIGN KEY (person_id, entity_type) REFERENCES entity(entity_id, entity_type)
    ) STRICT""",
    """CREATE TABLE company (
        company_id INTEGER PRIMARY KEY,
        entity_type TEXT NOT NULL DEFAULT 'company' CHECK (entity_type = 'company'),
        country_id INTEGER REFERENCES country(country_id),
        source_id INTEGER NOT NULL REFERENCES source(source_id),
        source_ref TEXT,
        FOREIGN KEY (company_id, entity_type) REFERENCES entity(entity_id, entity_type)
    ) STRICT""",
    """CREATE TABLE franchise (
        franchise_id INTEGER PRIMARY KEY,
        entity_type TEXT NOT NULL DEFAULT 'franchise' CHECK (entity_type = 'franchise'),
        source_id INTEGER NOT NULL REFERENCES source(source_id),
        source_ref TEXT,
        FOREIGN KEY (franchise_id, entity_type) REFERENCES entity(entity_id, entity_type)
    ) STRICT""",
    """CREATE TABLE award (
        award_id INTEGER PRIMARY KEY,
        entity_type TEXT NOT NULL DEFAULT 'award' CHECK (entity_type = 'award'),
        country_id INTEGER REFERENCES country(country_id),
        source_id INTEGER NOT NULL REFERENCES source(source_id),
        source_ref TEXT,
        FOREIGN KEY (award_id, entity_type) REFERENCES entity(entity_id, entity_type)
    ) STRICT""",
    # names, identifiers, field provenance (all point at the supertype)
    """CREATE TABLE entity_name (
        name_id INTEGER PRIMARY KEY,
        entity_id INTEGER NOT NULL REFERENCES entity(entity_id),
        name TEXT NOT NULL CHECK (length(name) > 0),
        name_norm TEXT NOT NULL CHECK (length(name_norm) > 0),
        language TEXT,
        kind TEXT NOT NULL CHECK (kind IN ('primary','original','translated','alias','former','working','abbreviation')),
        is_primary INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0,1)),
        source_id INTEGER NOT NULL REFERENCES source(source_id),
        source_ref TEXT,
        CHECK (is_primary = 0 OR kind = 'primary')
    ) STRICT""",
    """CREATE VIRTUAL TABLE entity_name_fts USING fts5(
        name, content='entity_name', content_rowid='name_id', tokenize='unicode61 remove_diacritics 2', prefix='2 3'
    )""",
    """CREATE TABLE external_id (
        entity_id INTEGER NOT NULL REFERENCES entity(entity_id),
        scheme TEXT NOT NULL REFERENCES id_scheme(scheme),
        value TEXT NOT NULL CHECK (length(value) > 0),
        is_primary INTEGER NOT NULL DEFAULT 1 CHECK (is_primary IN (0,1)),
        source_id INTEGER NOT NULL REFERENCES source(source_id),
        source_ref TEXT,
        PRIMARY KEY (entity_id, scheme, value),
        UNIQUE (scheme, value)
    ) STRICT""",
    """CREATE TABLE field_provenance (
        entity_id INTEGER NOT NULL REFERENCES entity(entity_id),
        field TEXT NOT NULL,
        source_id INTEGER NOT NULL REFERENCES source(source_id),
        source_ref TEXT,
        acquired_at TEXT,
        PRIMARY KEY (entity_id, field)
    ) STRICT""",
    # work facts
    """CREATE TABLE work_genre (
        work_id INTEGER NOT NULL REFERENCES work(work_id),
        label_id INTEGER NOT NULL REFERENCES genre_label(label_id),
        source_id INTEGER NOT NULL REFERENCES source(source_id),
        source_ref TEXT,
        PRIMARY KEY (work_id, label_id)
    ) STRICT""",
    """CREATE TABLE work_country (
        work_id INTEGER NOT NULL REFERENCES work(work_id),
        country_id INTEGER NOT NULL REFERENCES country(country_id),
        role TEXT NOT NULL CHECK (role IN ('origin','production','filming')),
        source_id INTEGER NOT NULL REFERENCES source(source_id),
        source_ref TEXT,
        PRIMARY KEY (work_id, country_id, role)
    ) STRICT""",
    """CREATE TABLE work_language (
        work_id INTEGER NOT NULL REFERENCES work(work_id),
        language_id INTEGER NOT NULL REFERENCES language(language_id),
        role TEXT NOT NULL CHECK (role IN ('original','spoken')),
        source_id INTEGER NOT NULL REFERENCES source(source_id),
        source_ref TEXT,
        PRIMARY KEY (work_id, language_id, role)
    ) STRICT""",
    """CREATE TABLE work_company (
        work_id INTEGER NOT NULL REFERENCES work(work_id),
        company_id INTEGER NOT NULL REFERENCES company(company_id),
        role TEXT NOT NULL CHECK (role IN ('production','distribution','broadcaster','network')),
        source_id INTEGER NOT NULL REFERENCES source(source_id),
        source_ref TEXT,
        PRIMARY KEY (work_id, company_id, role)
    ) STRICT""",
    """CREATE TABLE work_franchise (
        work_id INTEGER NOT NULL REFERENCES work(work_id),
        franchise_id INTEGER NOT NULL REFERENCES franchise(franchise_id),
        position INTEGER CHECK (position IS NULL OR position >= 1),
        basis TEXT NOT NULL CHECK (basis IN ('wikidata_franchise','wikidata_series','title','manual')),
        source_id INTEGER NOT NULL REFERENCES source(source_id),
        source_ref TEXT,
        PRIMARY KEY (work_id, franchise_id)
    ) STRICT""",
    """CREATE TABLE work_relation (
        work_id INTEGER NOT NULL REFERENCES work(work_id),
        related_work_id INTEGER NOT NULL REFERENCES work(work_id),
        relation TEXT NOT NULL REFERENCES relation_type(relation),
        source_id INTEGER NOT NULL REFERENCES source(source_id),
        source_ref TEXT,
        PRIMARY KEY (work_id, related_work_id, relation),
        CHECK (work_id <> related_work_id)
    ) STRICT""",
    """CREATE TABLE work_release (
        release_id INTEGER PRIMARY KEY,
        work_id INTEGER NOT NULL REFERENCES work(work_id),
        country_id INTEGER REFERENCES country(country_id),
        release_date TEXT NOT NULL CHECK (release_date GLOB '[0-9][0-9][0-9][0-9]*'),
        kind TEXT NOT NULL CHECK (kind IN ('premiere','theatrical','streaming','television','home_video')),
        source_id INTEGER NOT NULL REFERENCES source(source_id),
        source_ref TEXT
    ) STRICT""",
    """CREATE TABLE work_financial (
        financial_id INTEGER PRIMARY KEY,
        work_id INTEGER NOT NULL REFERENCES work(work_id),
        kind TEXT NOT NULL CHECK (kind IN ('budget','box_office')),
        scope TEXT NOT NULL CHECK (scope IN ('worldwide','domestic','country','unspecified')),
        country_id INTEGER REFERENCES country(country_id),
        amount INTEGER NOT NULL CHECK (amount >= 0),
        currency TEXT NOT NULL CHECK (length(currency) = 3),
        reference_year INTEGER CHECK (reference_year IS NULL OR reference_year BETWEEN 1800 AND 2100),
        source_id INTEGER NOT NULL REFERENCES source(source_id),
        source_ref TEXT,
        CHECK (scope <> 'country' OR country_id IS NOT NULL)
    ) STRICT""",
    # people and credits
    """CREATE TABLE credit (
        credit_id INTEGER PRIMARY KEY,
        work_id INTEGER NOT NULL REFERENCES work(work_id),
        person_id INTEGER NOT NULL REFERENCES person(person_id),
        role TEXT NOT NULL REFERENCES role_type(role),
        character_name TEXT,
        billing_order INTEGER CHECK (billing_order IS NULL OR billing_order >= 1),
        credit_note TEXT CHECK (credit_note IS NULL OR credit_note IN ('uncredited','voice','cameo','archive','additional')),
        source_id INTEGER NOT NULL REFERENCES source(source_id),
        source_ref TEXT
    ) STRICT""",
    # awards
    """CREATE TABLE award_category (
        category_id INTEGER PRIMARY KEY,
        award_id INTEGER NOT NULL REFERENCES award(award_id),
        name TEXT NOT NULL CHECK (length(name) > 0),
        name_norm TEXT NOT NULL,
        scope TEXT NOT NULL CHECK (scope IN ('work','person','person_for_work')),
        wikidata_id TEXT UNIQUE,
        source_id INTEGER NOT NULL REFERENCES source(source_id),
        source_ref TEXT,
        UNIQUE (award_id, name_norm)
    ) STRICT""",
    """CREATE TABLE ceremony (
        ceremony_id INTEGER PRIMARY KEY,
        award_id INTEGER NOT NULL REFERENCES award(award_id),
        year INTEGER NOT NULL CHECK (year BETWEEN 1800 AND 2100),
        edition TEXT,
        ceremony_date TEXT CHECK (ceremony_date IS NULL OR ceremony_date GLOB '[0-9][0-9][0-9][0-9]*'),
        wikidata_id TEXT UNIQUE,
        source_id INTEGER NOT NULL REFERENCES source(source_id),
        source_ref TEXT
    ) STRICT""",
    """CREATE TABLE award_result (
        result_id INTEGER PRIMARY KEY,
        ceremony_id INTEGER NOT NULL REFERENCES ceremony(ceremony_id),
        category_id INTEGER NOT NULL REFERENCES award_category(category_id),
        work_id INTEGER REFERENCES work(work_id),
        person_id INTEGER REFERENCES person(person_id),
        outcome TEXT NOT NULL CHECK (outcome IN ('won','nominated')),
        note TEXT,
        source_id INTEGER NOT NULL REFERENCES source(source_id),
        source_ref TEXT,
        CHECK (work_id IS NOT NULL OR person_id IS NOT NULL)
    ) STRICT""",
)

INDEXES: tuple[str, ...] = (
    "CREATE UNIQUE INDEX entity_name_primary ON entity_name(entity_id) WHERE is_primary = 1",
    "CREATE UNIQUE INDEX entity_name_unique ON entity_name(entity_id, name_norm, COALESCE(language, ''), kind)",
    "CREATE INDEX entity_name_norm ON entity_name(name_norm)",
    "CREATE INDEX external_id_entity ON external_id(entity_id, scheme)",
    "CREATE INDEX work_kind_year ON work(kind, release_year)",
    "CREATE INDEX work_parent ON work(parent_work_id, season_number, episode_number)",
    "CREATE INDEX work_year ON work(release_year)",
    "CREATE INDEX person_birth ON person(birth_year)",
    "CREATE INDEX credit_person ON credit(person_id, role)",
    "CREATE INDEX credit_work ON credit(work_id, role)",
    "CREATE INDEX credit_role ON credit(role, person_id)",
    "CREATE UNIQUE INDEX credit_unique ON credit(work_id, person_id, role, COALESCE(character_name, ''))",
    "CREATE INDEX work_genre_label ON work_genre(label_id, work_id)",
    "CREATE INDEX genre_label_norm ON genre_label(label_norm)",
    "CREATE INDEX genre_label_map_genre ON genre_label_map(genre_id, label_id)",
    "CREATE INDEX work_country_country ON work_country(country_id, role, work_id)",
    "CREATE INDEX work_language_language ON work_language(language_id, role, work_id)",
    "CREATE INDEX work_company_company ON work_company(company_id, work_id)",
    "CREATE INDEX work_franchise_franchise ON work_franchise(franchise_id, position)",
    "CREATE INDEX work_relation_related ON work_relation(related_work_id, relation)",
    "CREATE INDEX work_release_work ON work_release(work_id, country_id)",
    "CREATE INDEX work_release_country ON work_release(country_id, release_date)",
    "CREATE UNIQUE INDEX work_release_unique ON work_release(work_id, COALESCE(country_id, 0), kind, release_date)",
    "CREATE INDEX work_financial_work ON work_financial(work_id, kind)",
    "CREATE UNIQUE INDEX work_financial_unique ON work_financial(work_id, kind, scope, COALESCE(country_id, 0), COALESCE(reference_year, 0), currency)",
    "CREATE INDEX award_category_award ON award_category(award_id)",
    "CREATE UNIQUE INDEX ceremony_unique ON ceremony(award_id, year, COALESCE(edition, ''))",
    "CREATE INDEX award_result_person ON award_result(person_id, outcome)",
    "CREATE INDEX award_result_work ON award_result(work_id, outcome)",
    "CREATE INDEX award_result_category ON award_result(category_id, ceremony_id)",
    "CREATE UNIQUE INDEX award_result_unique ON award_result(ceremony_id, category_id, COALESCE(work_id, 0), COALESCE(person_id, 0))",
)

# --- definitional vocabularies (no facts about films) -------------------------------------------------------------

WORK_KINDS: tuple[tuple[str, str, str, str], ...] = (
    ("film", "screen", "Film", "Film"),
    ("tv_film", "screen", "Television film", "Film per la televisione"),
    ("short", "screen", "Short film", "Cortometraggio"),
    ("series", "screen", "Television series", "Serie TV"),
    ("miniseries", "screen", "Miniseries", "Miniserie"),
    ("season", "screen", "Season of a series", "Stagione"),
    ("episode", "screen", "Episode", "Episodio"),
    ("literary_work", "literary", "Literary work", "Opera letteraria"),
    ("comic", "comic", "Comic", "Fumetto"),
    ("video_game", "game", "Video game", "Videogioco"),
    ("stage_work", "stage", "Stage work", "Opera teatrale"),
    ("other", "other", "Other work", "Altra opera"),
)

ROLES: tuple[tuple[str, str, int, str, str], ...] = (
    ("director", "direction", 0, "Director", "Regista"),
    ("writer", "writing", 0, "Writer", "Sceneggiatore"),
    ("screenplay", "writing", 0, "Screenplay", "Sceneggiatura"),
    ("story", "writing", 0, "Story", "Soggetto"),
    ("author", "writing", 0, "Author of the source work", "Autore dell'opera d'origine"),
    ("creator", "writing", 0, "Creator (series)", "Ideatore (serie)"),
    ("cast", "cast", 1, "Cast member", "Interprete"),
    ("voice_cast", "cast", 1, "Voice actor", "Doppiatore / voce"),
    ("producer", "production", 0, "Producer", "Produttore"),
    ("executive_producer", "production", 0, "Executive producer", "Produttore esecutivo"),
    ("composer", "music", 0, "Composer", "Compositore"),
    ("cinematographer", "camera", 0, "Cinematographer", "Direttore della fotografia"),
    ("editor", "editing", 0, "Editor", "Montatore"),
    ("production_designer", "design", 0, "Production designer", "Scenografo"),
    ("costume_designer", "design", 0, "Costume designer", "Costumista"),
    ("other", "other", 0, "Other role", "Altro ruolo"),
)

# (relation, inverse label, label, description). Only the canonical direction is stored; v_work_relation shows both.
RELATIONS: tuple[tuple[str, str, str, str], ...] = (
    ("based_on", "is source of", "is based on", "The work is based on, adapted from or derived from the related work (a remake, an adaptation and an inspired work are NOT distinguished: Wikidata does not)."),
    ("follows", "is followed by", "follows", "Order in a series: the work comes after the related work (does not say whether it is a sequel, a prequel or a reboot)."),
    ("remake_of", "was remade as", "is a remake of", "The work is a remake of the related work (only where a source states it explicitly)."),
    ("spin_off_of", "has spin-off", "is a spin-off of", "The work is a spin-off of the related work (only where a source states it explicitly)."),
)

ID_SCHEMES: tuple[tuple[str, str, str | None, str | None], ...] = (
    ("wikidata", "Wikidata item", None, "https://www.wikidata.org/wiki/{value}"),
    ("imdb_title", "IMDb title id", "work", "https://www.imdb.com/title/{value}/"),
    ("imdb_name", "IMDb name id", "person", "https://www.imdb.com/name/{value}/"),
    ("tmdb_movie", "TMDb movie id", "work", "https://www.themoviedb.org/movie/{value}"),
    ("tmdb_tv", "TMDb TV series id", "work", "https://www.themoviedb.org/tv/{value}"),
    ("tmdb_person", "TMDb person id", "person", "https://www.themoviedb.org/person/{value}"),
    ("tvdb_series", "TheTVDB series id", "work", None),
    ("tvmaze_show", "TVmaze show id", "work", "https://www.tvmaze.com/shows/{value}"),
    ("eidr", "EIDR id", "work", None),
    ("wikipedia_it", "Wikipedia (it) page title", None, "https://it.wikipedia.org/wiki/{value}"),
    ("wikipedia_en", "Wikipedia (en) page title", None, "https://en.wikipedia.org/wiki/{value}"),
)

# --- public views (the ONLY objects the SQL tool may read) ------------------------------------------------------------
# The primary name of an entity is its `entity_name` row with is_primary = 1; identifiers are looked up by scheme.

_NAME = "LEFT JOIN entity_name {a} ON {a}.entity_id = {key} AND {a}.is_primary = 1"


def _ext(entity: str, scheme: str) -> str:
    return (
        f"(SELECT x.value FROM external_id x WHERE x.entity_id = {entity} AND x.scheme = '{scheme}' "
        "ORDER BY x.is_primary DESC, x.value LIMIT 1)"
    )


VIEWS: tuple[tuple[str, str], ...] = (
    (
        "v_work",
        f"""CREATE VIEW v_work AS
        SELECT w.work_id AS work_id, w.kind AS kind, k.medium AS medium, n.name AS title,
               (SELECT o.name FROM entity_name o WHERE o.entity_id = w.work_id AND o.kind = 'original'
                ORDER BY o.name LIMIT 1) AS original_title,
               w.release_year AS year, w.release_date AS release_date, w.end_year AS end_year,
               w.runtime_min AS runtime_min, w.status AS status, w.parent_work_id AS parent_work_id,
               w.season_number AS season_number, w.episode_number AS episode_number,
               {_ext('w.work_id', 'imdb_title')} AS imdb_id, COALESCE({_ext('w.work_id', 'tmdb_movie')}, {_ext('w.work_id', 'tmdb_tv')}) AS tmdb_id,
               {_ext('w.work_id', 'wikidata')} AS wikidata_id, {_ext('w.work_id', 'wikipedia_it')} AS wikipedia_it,
               {_ext('w.work_id', 'wikipedia_en')} AS wikipedia_en, s.name AS source
        FROM work w JOIN work_kind k ON k.kind = w.kind
        {_NAME.format(a='n', key='w.work_id')} LEFT JOIN source s ON s.source_id = w.source_id""",
    ),
    (
        "v_person",
        f"""CREATE VIEW v_person AS
        SELECT p.person_id AS person_id, n.name AS name, p.birth_date AS birth_date, p.birth_year AS birth_year,
               p.death_date AS death_date, p.death_year AS death_year, c.label_en AS birth_country,
               {_ext('p.person_id', 'imdb_name')} AS imdb_id, {_ext('p.person_id', 'tmdb_person')} AS tmdb_id,
               {_ext('p.person_id', 'wikidata')} AS wikidata_id, {_ext('p.person_id', 'wikipedia_it')} AS wikipedia_it,
               {_ext('p.person_id', 'wikipedia_en')} AS wikipedia_en, s.name AS source
        FROM person p {_NAME.format(a='n', key='p.person_id')}
        LEFT JOIN country c ON c.country_id = p.birth_country_id LEFT JOIN source s ON s.source_id = p.source_id""",
    ),
    (
        "v_name",
        """CREATE VIEW v_name AS
        SELECT e.entity_id AS entity_id, e.entity_type AS entity_type, n.name AS name, n.name_norm AS name_norm,
               n.language AS language, n.kind AS name_kind, n.is_primary AS is_primary
        FROM entity_name n JOIN entity e ON e.entity_id = n.entity_id""",
    ),
    (
        "v_external_id",
        """CREATE VIEW v_external_id AS
        SELECT x.entity_id AS entity_id, e.entity_type AS entity_type, x.scheme AS scheme, i.label AS scheme_label,
               x.value AS value, x.is_primary AS is_primary
        FROM external_id x JOIN entity e ON e.entity_id = x.entity_id JOIN id_scheme i ON i.scheme = x.scheme""",
    ),
    (
        "v_credit",
        f"""CREATE VIEW v_credit AS
        SELECT c.credit_id AS credit_id, c.work_id AS work_id, wn.name AS work_title, w.release_year AS work_year,
               w.kind AS work_kind, c.person_id AS person_id, pn.name AS person_name, c.role AS role,
               r.department AS department, r.is_cast AS is_cast, c.character_name AS character_name,
               c.billing_order AS billing_order, c.credit_note AS credit_note, s.name AS source
        FROM credit c JOIN work w ON w.work_id = c.work_id JOIN role_type r ON r.role = c.role
        {_NAME.format(a='wn', key='c.work_id')} {_NAME.format(a='pn', key='c.person_id')}
        LEFT JOIN source s ON s.source_id = c.source_id""",
    ),
    (
        "v_work_genre",
        """CREATE VIEW v_work_genre AS
        SELECT DISTINCT wg.work_id AS work_id, n.name AS work_title, w.release_year AS work_year, w.kind AS work_kind,
               g.genre_id AS genre_id, g.code AS genre_code, g.label_en AS genre, g.label_it AS genre_it
        FROM work_genre wg JOIN genre_label_map m ON m.label_id = wg.label_id JOIN genre g ON g.genre_id = m.genre_id
        JOIN work w ON w.work_id = wg.work_id LEFT JOIN entity_name n ON n.entity_id = wg.work_id AND n.is_primary = 1""",
    ),
    (
        "v_work_genre_label",
        """CREATE VIEW v_work_genre_label AS
        SELECT wg.work_id AS work_id, n.name AS work_title, w.release_year AS work_year, gl.label_id AS label_id,
               gl.label_it AS label_it, gl.label_en AS label_en, gl.wikidata_id AS wikidata_id, g.label_en AS genre,
               m.mapping AS mapping, s.name AS source
        FROM work_genre wg JOIN genre_label gl ON gl.label_id = wg.label_id JOIN work w ON w.work_id = wg.work_id
        LEFT JOIN genre_label_map m ON m.label_id = gl.label_id LEFT JOIN genre g ON g.genre_id = m.genre_id
        LEFT JOIN entity_name n ON n.entity_id = wg.work_id AND n.is_primary = 1 LEFT JOIN source s ON s.source_id = wg.source_id""",
    ),
    (
        "v_genre_label",
        """CREATE VIEW v_genre_label AS
        SELECT gl.label_id AS label_id, gl.label_it AS label_it, gl.label_en AS label_en, gl.wikidata_id AS wikidata_id,
               g.code AS genre_code, g.label_en AS genre, m.mapping AS mapping, m.rule AS rule
        FROM genre_label gl LEFT JOIN genre_label_map m ON m.label_id = gl.label_id LEFT JOIN genre g ON g.genre_id = m.genre_id""",
    ),
    (
        "v_title_search",
        """CREATE VIEW v_title_search AS
        SELECT n.entity_id AS entity_id, e.entity_type AS entity_type, n.name AS name, n.kind AS name_kind, n.language AS language,
               n.is_primary AS is_primary, w.kind AS work_kind, w.release_year AS work_year,
               entity_name_fts.rank AS rank, entity_name_fts.name AS search
        FROM entity_name_fts JOIN entity_name n ON n.name_id = entity_name_fts.rowid JOIN entity e ON e.entity_id = n.entity_id
        LEFT JOIN work w ON w.work_id = n.entity_id""",
    ),
    (
        "v_work_country",
        """CREATE VIEW v_work_country AS
        SELECT wc.work_id AS work_id, n.name AS work_title, w.release_year AS work_year, w.kind AS work_kind,
               c.country_id AS country_id, c.label_en AS country, c.iso2 AS iso2, wc.role AS role
        FROM work_country wc JOIN country c ON c.country_id = wc.country_id JOIN work w ON w.work_id = wc.work_id
        LEFT JOIN entity_name n ON n.entity_id = wc.work_id AND n.is_primary = 1""",
    ),
    (
        "v_work_language",
        """CREATE VIEW v_work_language AS
        SELECT wl.work_id AS work_id, n.name AS work_title, w.release_year AS work_year, w.kind AS work_kind,
               l.label_en AS language, l.iso639_1 AS iso639_1, wl.role AS role
        FROM work_language wl JOIN language l ON l.language_id = wl.language_id JOIN work w ON w.work_id = wl.work_id
        LEFT JOIN entity_name n ON n.entity_id = wl.work_id AND n.is_primary = 1""",
    ),
    (
        "v_work_release",
        """CREATE VIEW v_work_release AS
        SELECT r.work_id AS work_id, n.name AS work_title, w.kind AS work_kind, c.label_en AS country, c.iso2 AS iso2,
               r.release_date AS release_date, r.kind AS release_kind
        FROM work_release r JOIN work w ON w.work_id = r.work_id LEFT JOIN country c ON c.country_id = r.country_id
        LEFT JOIN entity_name n ON n.entity_id = r.work_id AND n.is_primary = 1""",
    ),
    (
        "v_work_company",
        """CREATE VIEW v_work_company AS
        SELECT wc.work_id AS work_id, wn.name AS work_title, w.release_year AS work_year, wc.company_id AS company_id,
               cn.name AS company, wc.role AS role
        FROM work_company wc JOIN work w ON w.work_id = wc.work_id
        LEFT JOIN entity_name wn ON wn.entity_id = wc.work_id AND wn.is_primary = 1
        LEFT JOIN entity_name cn ON cn.entity_id = wc.company_id AND cn.is_primary = 1""",
    ),
    (
        "v_work_relation",
        """CREATE VIEW v_work_relation AS
        SELECT r.work_id AS work_id, wn.name AS work_title, r.relation AS relation, t.label_en AS relation_label,
               'forward' AS direction, r.related_work_id AS related_work_id, rn.name AS related_title,
               rw.kind AS related_kind, rw.release_year AS related_year, s.name AS source
        FROM work_relation r JOIN relation_type t ON t.relation = r.relation JOIN work rw ON rw.work_id = r.related_work_id
        LEFT JOIN entity_name wn ON wn.entity_id = r.work_id AND wn.is_primary = 1
        LEFT JOIN entity_name rn ON rn.entity_id = r.related_work_id AND rn.is_primary = 1
        LEFT JOIN source s ON s.source_id = r.source_id
        UNION ALL
        SELECT r.related_work_id, rn.name, r.relation, t.inverse_label, 'inverse', r.work_id, wn.name, w.kind, w.release_year, s.name
        FROM work_relation r JOIN relation_type t ON t.relation = r.relation JOIN work w ON w.work_id = r.work_id
        LEFT JOIN entity_name wn ON wn.entity_id = r.work_id AND wn.is_primary = 1
        LEFT JOIN entity_name rn ON rn.entity_id = r.related_work_id AND rn.is_primary = 1
        LEFT JOIN source s ON s.source_id = r.source_id""",
    ),
    (
        "v_franchise",
        """CREATE VIEW v_franchise AS
        SELECT f.franchise_id AS franchise_id, fn.name AS franchise, wf.work_id AS work_id, wn.name AS work_title,
               w.release_year AS work_year, w.kind AS work_kind, wf.position AS position, wf.basis AS basis
        FROM work_franchise wf JOIN franchise f ON f.franchise_id = wf.franchise_id JOIN work w ON w.work_id = wf.work_id
        LEFT JOIN entity_name fn ON fn.entity_id = f.franchise_id AND fn.is_primary = 1
        LEFT JOIN entity_name wn ON wn.entity_id = wf.work_id AND wn.is_primary = 1""",
    ),
    (
        "v_award_result",
        """CREATE VIEW v_award_result AS
        SELECT r.result_id AS result_id, an.name AS award, ac.name AS category, ac.scope AS category_scope,
               ce.year AS ceremony_year, ce.edition AS ceremony_edition, r.outcome AS outcome,
               r.work_id AS work_id, wn.name AS work_title, w.release_year AS work_year, r.person_id AS person_id,
               pn.name AS person_name, r.note AS note, s.name AS source
        FROM award_result r JOIN ceremony ce ON ce.ceremony_id = r.ceremony_id JOIN award_category ac ON ac.category_id = r.category_id
        LEFT JOIN entity_name an ON an.entity_id = ac.award_id AND an.is_primary = 1
        LEFT JOIN work w ON w.work_id = r.work_id LEFT JOIN entity_name wn ON wn.entity_id = r.work_id AND wn.is_primary = 1
        LEFT JOIN entity_name pn ON pn.entity_id = r.person_id AND pn.is_primary = 1
        LEFT JOIN source s ON s.source_id = r.source_id""",
    ),
    (
        "v_work_financial",
        """CREATE VIEW v_work_financial AS
        SELECT f.work_id AS work_id, n.name AS work_title, w.release_year AS work_year, f.kind AS kind, f.scope AS scope,
               c.label_en AS country, f.amount AS amount, f.currency AS currency, f.reference_year AS reference_year,
               s.name AS source
        FROM work_financial f JOIN work w ON w.work_id = f.work_id LEFT JOIN country c ON c.country_id = f.country_id
        LEFT JOIN entity_name n ON n.entity_id = f.work_id AND n.is_primary = 1 LEFT JOIN source s ON s.source_id = f.source_id""",
    ),
    ("v_genre", "CREATE VIEW v_genre AS SELECT genre_id AS genre_id, code AS code, label_en AS genre, label_it AS genre_it, parent_genre_id AS parent_genre_id, description AS description FROM genre"),
    ("v_role_type", "CREATE VIEW v_role_type AS SELECT role AS role, department AS department, is_cast AS is_cast, label_en AS label_en, label_it AS label_it FROM role_type"),
    (
        "v_source",
        """CREATE VIEW v_source AS
        SELECT source_id AS source_id, name AS name, kind AS kind, url AS url, license AS license, license_url AS license_url,
               usage_scope AS usage_scope, attribution_required AS attribution_required, attribution_text AS attribution_text,
               terms_note AS terms_note, snapshot_label AS snapshot_label, retrieved_at AS retrieved_at
        FROM source""",
    ),
)

PUBLIC_VIEWS: tuple[str, ...] = tuple(name for name, _ in VIEWS)


def rebuild_fts(conn: sqlite3.Connection) -> None:
    """Fill the external-content FTS5 index from entity_name. Call once after the names are loaded (no triggers keep it in sync:
    the database is read-only at runtime and is rebuilt as a whole)."""
    conn.execute("INSERT INTO entity_name_fts(entity_name_fts) VALUES ('rebuild')")


def check_fts(conn: sqlite3.Connection) -> list[str]:
    """Problems with the FTS5 index: it must be consistent and contain exactly one row per entity_name row."""
    problems: list[str] = []
    try:
        conn.execute("INSERT INTO entity_name_fts(entity_name_fts, rank) VALUES ('integrity-check', 1)")
    except sqlite3.DatabaseError as exc:
        problems.append(f"fts5 integrity-check failed: {exc}")
    names = conn.execute("SELECT count(*) FROM entity_name").fetchone()[0]
    indexed = conn.execute("SELECT count(*) FROM entity_name_fts_docsize").fetchone()[0]
    if names != indexed:
        problems.append(f"fts5 index has {indexed} rows but entity_name has {names}: rebuild it")
    return problems


def create_database(path: str | Path, *, overwrite: bool = False) -> Path:
    """Create an empty database with the schema and the definitional vocabularies. Refuses an existing file."""
    target = Path(path)
    if target.exists() and not overwrite:
        raise FileExistsError(f"{target} exists; refusing to overwrite it.")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    conn = sqlite3.connect(target)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        for ddl in TABLES:
            conn.execute(ddl)
        for ddl in INDEXES:
            conn.execute(ddl)
        for _, ddl in VIEWS:
            conn.execute(ddl)
        conn.executemany("INSERT INTO work_kind VALUES (?,?,?,?)", WORK_KINDS)
        conn.executemany("INSERT INTO role_type VALUES (?,?,?,?,?)", ROLES)
        conn.executemany("INSERT INTO relation_type VALUES (?,?,?,?)", RELATIONS)
        conn.executemany("INSERT INTO id_scheme VALUES (?,?,?,?)", ID_SCHEMES)
        conn.execute("INSERT INTO build_info VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        conn.commit()
    finally:
        conn.close()
    return target
