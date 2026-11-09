"""The SQL of the tool: constant fragments, bound parameters, integer limits already validated. Nothing the model wrote is ever spliced in.

Every function returns `(sql, params)` for `Session.query`, which still validates it against the approved views and columns: this module
chooses WHICH approved query to run, it does not widen what may be read. Lists in `IN (...)` are literals from `constants.py` or one `?` per id.
"""
from __future__ import annotations

from collections.abc import Sequence

from .constants import FILM_KINDS, SCREEN_KINDS, SERIES_KINDS
from .ml_titles import normalize_title, stored_form

Query = tuple[str, list]


def _kinds(kinds: Sequence[str]) -> str:
    return ", ".join(f"'{k}'" for k in kinds)  # constants only


def _marks(n: int) -> str:
    return ", ".join("?" * n)


def kinds_for(type_: str | None) -> tuple[str, ...]:
    return FILM_KINDS if type_ == "film" else SERIES_KINDS if type_ == "series" else SCREEN_KINDS


_WORK_CARD = ("w.work_id AS work_id, w.kind AS kind, w.title AS title, w.original_title AS original_title, w.year AS year, w.end_year AS end_year, "
              "w.runtime_min AS runtime_min, w.status AS status, w.imdb_id AS imdb_id, w.tmdb_id AS tmdb_id, w.wikidata_id AS wikidata_id, "
              "w.wikipedia_it AS wikipedia_it")


# ---- identification -----------------------------------------------------------------------------------------------------------
def works_by_name(norm: str, kinds: Sequence[str], fetch: int) -> Query:
    return (f"SELECT DISTINCT {_WORK_CARD} FROM v_name n JOIN v_work w ON w.work_id = n.entity_id "
            f"WHERE n.name_norm = ? AND n.entity_type = 'work' AND w.kind IN ({_kinds(kinds)}) LIMIT {int(fetch)}", [norm])


def works_by_title_search(fts: str, kinds: Sequence[str], fetch: int) -> Query:
    return (f"SELECT DISTINCT {_WORK_CARD} FROM v_title_search t JOIN v_work w ON w.work_id = t.entity_id "
            f"WHERE t.search MATCH ? AND t.entity_type = 'work' AND w.kind IN ({_kinds(kinds)}) LIMIT {int(fetch)}", [fts])


def works_by_column(column: str, value: object, kinds: Sequence[str] | None = None) -> Query:
    if column not in {"work_id", "imdb_id", "tmdb_id", "wikidata_id"}:
        raise ValueError("column not allowed")
    kind_filter = f" AND w.kind IN ({_kinds(kinds)})" if kinds else ""
    return f"SELECT {_WORK_CARD} FROM v_work w WHERE w.{column} = ?{kind_filter} LIMIT 5", [value]


def work_ids_by_external(scheme: str, value: object) -> Query:
    """Indexed lookup (scheme, value): `v_work.tmdb_id` is a COALESCE of two columns and cannot use an index (1 s scan)."""
    if scheme not in {"tmdb_movie", "tmdb_tv", "imdb_title", "wikidata"}:
        raise ValueError("scheme not allowed")
    return "SELECT DISTINCT entity_id AS work_id FROM v_external_id WHERE scheme = ? AND value = ? AND entity_type = 'work' LIMIT 5", [scheme, str(value)]


def directors_of(work_ids: Sequence[int]) -> Query:
    return (f"SELECT work_id, person_id, person_name FROM v_credit WHERE work_id IN ({_marks(len(work_ids))}) AND role = 'director' "
            f"ORDER BY work_id, person_name LIMIT 50", list(work_ids))


_PERSON_CARD = "p.person_id AS person_id, p.name AS name, p.birth_year AS birth_year, p.death_year AS death_year, p.birth_country AS birth_country, p.wikidata_id AS wikidata_id, p.wikipedia_it AS wikipedia_it"


def persons_by_name(norm: str, fetch: int) -> Query:
    return (f"SELECT DISTINCT {_PERSON_CARD} FROM v_name n JOIN v_person p ON p.person_id = n.entity_id "
            f"WHERE n.name_norm = ? AND n.entity_type = 'person' LIMIT {int(fetch)}", [norm])


def persons_by_title_search(fts: str, fetch: int) -> Query:
    return (f"SELECT DISTINCT {_PERSON_CARD} FROM v_title_search t JOIN v_person p ON p.person_id = t.entity_id "
            f"WHERE t.search MATCH ? AND t.entity_type = 'person' LIMIT {int(fetch)}", [fts])


def persons_by_column(column: str, value: object) -> Query:
    if column not in {"person_id", "wikidata_id"}:
        raise ValueError("column not allowed")
    return f"SELECT {_PERSON_CARD} FROM v_person p WHERE p.{column} = ? LIMIT 5", [value]


def role_counts(person_ids: Sequence[int]) -> Query:
    return (f"SELECT person_id, role, count(*) AS n FROM v_credit WHERE person_id IN ({_marks(len(person_ids))}) "
            f"GROUP BY person_id, role LIMIT 50", list(person_ids))


def companies_by_name(norm: str, fetch: int) -> Query:
    return (f"SELECT DISTINCT entity_id AS company_id, name FROM v_name WHERE name_norm = ? AND entity_type = 'company' LIMIT {int(fetch)}", [norm])


def franchises_by_name(norm: str, fetch: int) -> Query:
    return (f"SELECT DISTINCT entity_id AS franchise_id, name FROM v_name WHERE name_norm = ? AND entity_type = 'franchise' LIMIT {int(fetch)}", [norm])


# ---- credits -------------------------------------------------------------------------------------------------------------------
def _year_filters(column: str, year_from: int | None, year_to: int | None) -> tuple[str, list]:
    sql, params = "", []
    if year_from is not None:
        sql += f" AND {column} >= ?"
        params.append(year_from)
    if year_to is not None:
        sql += f" AND {column} <= ?"
        params.append(year_to)
    return sql, params


def filmography(person_id: int, role: str | None, type_: str | None, year_from: int | None, year_to: int | None, order: str, limit: int) -> Query:
    years, yparams = _year_filters("work_year", year_from, year_to)
    role_sql, rparams = (" AND role = ?", [role]) if role else ("", [])
    direction = "DESC" if order == "desc" else "ASC"
    return (f"SELECT work_id, work_title AS title, work_year AS year, work_kind AS kind, role, character_name FROM v_credit "
            f"WHERE person_id = ?{role_sql} AND work_kind IN ({_kinds(kinds_for(type_))}){years} "
            f"ORDER BY work_year {direction}, work_title, role LIMIT {int(limit)}", [person_id, *rparams, *yparams])


def filmography_count(person_id: int, role: str | None, type_: str | None, year_from: int | None, year_to: int | None) -> Query:
    years, yparams = _year_filters("work_year", year_from, year_to)
    role_sql, rparams = (" AND role = ?", [role]) if role else ("", [])
    return (f"SELECT count(DISTINCT work_id) AS works FROM v_credit WHERE person_id = ?{role_sql} AND work_kind IN ({_kinds(kinds_for(type_))}){years}",
            [person_id, *rparams, *yparams])


def cast_of(work_id: int, limit: int) -> Query:
    return (f"SELECT person_id, person_name, character_name, credit_note, billing_order FROM v_credit WHERE work_id = ? AND is_cast = 1 "
            f"ORDER BY billing_order IS NULL, billing_order, character_name IS NULL, person_name LIMIT {int(limit)}", [work_id])


def cast_count(work_id: int) -> Query:
    return "SELECT count(*) AS n FROM v_credit WHERE work_id = ? AND is_cast = 1", [work_id]


def crew_of(work_id: int, role: str | None, limit: int) -> Query:
    role_sql, params = (" AND role = ?", [role]) if role else ("", [])
    return (f"SELECT person_id, person_name, role, department FROM v_credit WHERE work_id = ? AND is_cast = 0{role_sql} "
            f"ORDER BY department, role, person_name LIMIT {int(limit)}", [work_id, *params])


def shared_works(person_a: int, person_b: int, role_a: str | None, role_b: str | None, order: str, limit: int) -> Query:
    ra, pa = (" AND a.role = ?", [role_a]) if role_a else ("", [])
    rb, pb = (" AND b.role = ?", [role_b]) if role_b else ("", [])
    direction = "DESC" if order == "desc" else "ASC"
    return (f"SELECT a.work_id AS work_id, a.work_title AS title, a.work_year AS year, a.work_kind AS kind, a.role AS role_a, b.role AS role_b "
            f"FROM v_credit a JOIN v_credit b ON b.work_id = a.work_id WHERE a.person_id = ? AND b.person_id = ?{ra}{rb} "
            f"AND a.work_kind IN ({_kinds(SCREEN_KINDS)}) ORDER BY a.work_year {direction}, a.work_title LIMIT {int(limit)}", [person_a, person_b, *pa, *pb])


def top_collaborators(person: int, role_a: str | None, role_b: str | None, limit: int) -> Query:
    # The works of `person` come from an IN subquery, not from a second join of v_credit: SQLite does not push a join condition into the two branches of the
    # schema-3 view and would read every credit (a timeout); a WHERE ... IN (subquery) is pushed into both. Same result as the self-join.
    ra, pa = (" AND a.role = ?", [role_a]) if role_a else ("", [])
    rb, pb = (" AND b.role = ?", [role_b]) if role_b else ("", [])
    return (f"SELECT b.person_id AS person_id, b.person_name AS person_name, count(DISTINCT b.work_id) AS works FROM v_credit b "
            f"WHERE b.work_id IN (SELECT a.work_id FROM v_credit a WHERE a.person_id = ?{ra} AND a.work_kind IN ({_kinds(SCREEN_KINDS)})) "
            f"AND b.person_id <> ?{rb} GROUP BY b.person_id, b.person_name ORDER BY works DESC, b.person_name LIMIT {int(limit)}", [person, *pa, person, *pb])


# ---- awards ---------------------------------------------------------------------------------------------------------------------
_AWARD_COLUMNS = ("award, category, category_scope AS scope, ceremony_year AS year, ceremony_edition AS edition, outcome, work_id, work_title, "
                  "work_year, person_id, person_name")


# One award = one (ceremony year, award, category, outcome, work): the people who share it are NOT separate awards (Parasite's Best Original Screenplay has two writers).
_DISTINCT_AWARDS = "count(DISTINCT ceremony_year || '|' || award || '|' || category || '|' || outcome || '|' || coalesce(work_id, 0))"


def _award_filters(outcome: str | None, year_from: int | None, year_to: int | None, pattern: str | None = None) -> tuple[str, list]:
    sql, params = _year_filters("ceremony_year", year_from, year_to)
    if outcome:
        sql += " AND outcome = ?"
        params.append(outcome)
    if pattern:  # an award name that narrows the results of a work or a person ('Oscar')
        sql += " AND (lower(award) LIKE ? OR lower(category) LIKE ?)"
        params += [pattern, pattern]
    return sql, params


def awards_of(column: str, value: int, outcome: str | None, year_from: int | None, year_to: int | None, order: str, limit: int, pattern: str | None = None) -> Query:
    if column not in {"work_id", "person_id"}:
        raise ValueError("column not allowed")
    extra, params = _award_filters(outcome, year_from, year_to, pattern)
    direction = "DESC" if order == "desc" else "ASC"
    return (f"SELECT {_AWARD_COLUMNS} FROM v_award_result WHERE {column} = ?{extra} ORDER BY ceremony_year {direction}, award, category, outcome DESC LIMIT {int(limit)}",
            [value, *params])


def awards_by_name(pattern: str, exact: str, outcome: str | None, year_from: int | None, year_to: int | None, order: str, limit: int) -> Query:
    """Results whose award or category contains `pattern`; within a year the category that IS `exact` comes first ('Oscar al miglior film' before
    'Oscar al miglior film in lingua straniera'). Without it a plain LIMIT would cut the answer in favour of longer names."""
    extra, params = _award_filters(outcome, year_from, year_to)
    direction = "DESC" if order == "desc" else "ASC"
    return (f"SELECT {_AWARD_COLUMNS} FROM v_award_result WHERE (lower(award) LIKE ? OR lower(category) LIKE ?){extra} "
            f"ORDER BY ceremony_year {direction}, lower(category) = ? DESC, category, work_title LIMIT {int(limit)}", [pattern, pattern, *params, exact])


def awards_count(column: str | None, value: object, pattern: str | None, outcome: str | None, year_from: int | None, year_to: int | None) -> Query:
    if column:
        if column not in {"work_id", "person_id"}:
            raise ValueError("column not allowed")
        extra, params = _award_filters(outcome, year_from, year_to, pattern)
        return f"SELECT {_DISTINCT_AWARDS} AS n FROM v_award_result WHERE {column} = ?{extra}", [value, *params]
    extra, params = _award_filters(outcome, year_from, year_to)
    return f"SELECT {_DISTINCT_AWARDS} AS n FROM v_award_result WHERE (lower(award) LIKE ? OR lower(category) LIKE ?){extra}", [pattern, pattern, *params]


# ---- series ---------------------------------------------------------------------------------------------------------------------
def seasons_of(series_id: int, limit: int) -> Query:
    return (f"SELECT work_id, season_number, title, year FROM v_work WHERE parent_work_id = ? AND kind = 'season' "
            f"ORDER BY season_number, title LIMIT {int(limit)}", [series_id])


def episode_counts(parent_ids: Sequence[int]) -> Query:
    return (f"SELECT parent_work_id, count(*) AS episodes, count(episode_number) AS numbered FROM v_work WHERE parent_work_id IN ({_marks(len(parent_ids))}) AND kind = 'episode' "
            f"GROUP BY parent_work_id LIMIT 50", list(parent_ids))


def episodes_of(parent_id: int, season_number: int | None, limit: int) -> Query:
    season_sql, params = (" AND season_number = ?", [season_number]) if season_number is not None else ("", [])
    return (f"SELECT work_id, title, original_title, season_number, episode_number, release_date FROM v_work WHERE parent_work_id = ? AND kind = 'episode'{season_sql} "
            f"ORDER BY episode_number, title LIMIT {int(limit)}", [parent_id, *params])


# ---- companies, franchise, relations, card ---------------------------------------------------------------------------------------
def companies_of(work_id: int, limit: int) -> Query:
    return (f"SELECT DISTINCT company_id, company, role FROM v_work_company WHERE work_id = ? ORDER BY role, company LIMIT {int(limit)}", [work_id])


def works_of_company(company_id: int, limit: int) -> Query:
    return (f"SELECT DISTINCT work_id, work_title AS title, work_year AS year, role FROM v_work_company WHERE company_id = ? "
            f"ORDER BY work_year DESC, work_title LIMIT {int(limit)}", [company_id])


def franchise_of(work_id: int) -> Query:
    return "SELECT DISTINCT franchise_id, franchise, basis FROM v_franchise WHERE work_id = ? LIMIT 5", [work_id]


def franchise_members(franchise_id: int, limit: int) -> Query:
    return (f"SELECT work_id, work_title AS title, work_year AS year, work_kind AS kind FROM v_franchise WHERE franchise_id = ? "
            f"ORDER BY work_year, work_title LIMIT {int(limit)}", [franchise_id])


def relations_of(work_id: int, limit: int) -> Query:
    return (f"SELECT relation, relation_label, direction, related_work_id, related_title, related_kind, related_year FROM v_work_relation WHERE work_id = ? "
            f"ORDER BY relation, direction, related_year LIMIT {int(limit)}", [work_id])


def external_ids_of(work_ids: Sequence[int]) -> Query:
    return (f"SELECT work_id, imdb_id, tmdb_id, kind FROM v_work WHERE work_id IN ({_marks(len(work_ids))}) LIMIT 50", list(work_ids))




def credits_by_roles(work_id: int, roles: Sequence[str], limit: int) -> Query:
    return (f"SELECT person_id, person_name, role FROM v_credit WHERE work_id = ? AND role IN ({_marks(len(roles))}) "
            f"ORDER BY role, person_name LIMIT {int(limit)}", [work_id, *roles])


def genres_of(work_id: int) -> Query:
    return "SELECT DISTINCT genre FROM v_work_genre WHERE work_id = ? ORDER BY genre LIMIT 12", [work_id]


def countries_of(work_id: int) -> Query:
    return "SELECT DISTINCT country, iso2 FROM v_work_country WHERE work_id = ? AND role = 'origin' ORDER BY country LIMIT 12", [work_id]




def money_of(work_id: int) -> Query:
    return "SELECT kind, scope, country, amount, currency, reference_year FROM v_work_financial WHERE work_id = ? ORDER BY kind, scope LIMIT 8", [work_id]


# ---- schema 3: identification level, ratings, provenance ----------------------------------------------------------------------
def identity_of(work_ids: Sequence[int]) -> Query:
    return (f"SELECT work_id, identity_level, entry_route FROM v_work_status WHERE work_id IN ({_marks(len(work_ids))}) LIMIT 50", list(work_ids))


def ratings_of(work_id: int) -> Query:
    return "SELECT source, audience, rating, scale_max, vote_count, as_of FROM v_work_rating WHERE work_id = ? ORDER BY source LIMIT 10", [work_id]


def top_rated(type_: str | None, year_from: int | None, year_to: int | None, min_votes: int, limit: int) -> Query:
    years, yparams = _year_filters("work_year", year_from, year_to)
    return (f"SELECT work_id, work_title AS title, work_year AS year, work_kind AS kind, rating, scale_max, vote_count, as_of FROM v_work_rating "
            f"WHERE source = 'imdb-datasets' AND vote_count >= ? AND work_kind IN ({_kinds(kinds_for(type_))}){years} "
            f"ORDER BY rating DESC, vote_count DESC LIMIT {int(limit)}", [int(min_votes), *yparams])


def ids_of_entity(entity_id: int) -> Query:
    return "SELECT scheme, value, is_primary FROM v_external_id WHERE entity_id = ? ORDER BY scheme, is_primary DESC, value LIMIT 40", [entity_id]


def status_of(work_id: int) -> Query:
    return "SELECT entry_route, identification, identity_level, plot_status, completeness FROM v_work_status WHERE work_id = ? LIMIT 1", [work_id]


def claims_of(entity_ids: Sequence[int], limit: int) -> Query:
    return (f"SELECT entity_id, field, value, source, source_ref FROM v_entity_claim WHERE entity_id IN ({_marks(len(entity_ids))}) "
            f"ORDER BY field, value LIMIT {int(limit)}", list(entity_ids))


def candidates_of(entity_ids: Sequence[int], limit: int) -> Query:
    return (f"SELECT entity_id, scheme, value, tier, evidence FROM v_external_id_candidate WHERE entity_id IN ({_marks(len(entity_ids))}) "
            f"ORDER BY tier, value LIMIT {int(limit)}", list(entity_ids))


def merged_into(person_id: int) -> Query:
    return ("SELECT merged_entity_id, merged_name, canonical_entity_id, canonical_name, reason FROM v_entity_canonical "
            "WHERE canonical_entity_id = ? OR merged_entity_id = ? LIMIT 10", [person_id, person_id])


# ---- schema 4: MovieLens (the six operations of the old movie_db_search) ---------------------------------------------------------
_ML_COLUMNS = ("m.movie_id AS movie_id, m.imdb_id AS imdb_id, m.work_id AS work_id, m.work_title AS title, m.work_year AS year, m.work_kind AS kind, m.ml_title AS ml_title, "
               "m.avg_rating AS avg_rating, m.n_ratings AS n_ratings, m.status AS status, m.reason AS reason, "
               "(SELECT group_concat(g.genre, '|') FROM v_ml_genre g WHERE g.work_id = m.work_id) AS genres")


def _ml_filters(genre: str | None, year_from: int | None, year_to: int | None) -> tuple[str, list]:
    clauses, params = [], []
    if genre:
        clauses.append(" AND m.work_id IN (SELECT f.work_id FROM v_ml_genre f WHERE f.genre = ?)")
        params.append(genre)
    if year_from:
        clauses.append(" AND m.ml_year >= ?")
        params.append(int(year_from))
    if year_to:
        clauses.append(" AND m.ml_year <= ?")
        params.append(int(year_to))
    return "".join(clauses), params


def ml_ranking(order: str, genre: str | None, year_from: int | None, year_to: int | None, min_ratings: int, limit: int) -> Query:
    """top_rated / most_rated / by_genre_year: films, shorts and TV films of the catalogue (never a series or an episode), MovieLens mean and count.
    The year filters use the year MovieLens gives (as the old tool did), not the catalogue year shown in the result."""
    where, params = _ml_filters(genre, year_from, year_to)
    by = "m.avg_rating DESC, m.n_ratings DESC, m.movie_id" if order == "rating" else "m.n_ratings DESC, m.avg_rating DESC, m.movie_id"
    # the minimum is a validated integer written as a literal: with the default (50) the planner can use the partial index ml_movie_top
    return (f"SELECT {_ML_COLUMNS} FROM v_ml_movie m WHERE m.work_id IS NOT NULL AND m.work_kind IN ({_kinds(FILM_KINDS)}) AND m.n_ratings >= {int(min_ratings)}{where} "
            f"ORDER BY {by} LIMIT {int(limit)}", params)


def _like_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def ml_by_title(title: str, genre: str | None, year_from: int | None, year_to: int | None, limit: int) -> Query:
    """by_title: three tiers like the old tool (exact, trailing article normalised, substring) on the MovieLens title; films not in the catalogue are listed too."""
    canonical = normalize_title(title)
    stored = stored_form(canonical)
    where, params = _ml_filters(genre, year_from, year_to)
    sql = (f"SELECT {_ML_COLUMNS} FROM v_ml_movie m WHERE (m.ml_title LIKE ? ESCAPE '\\' OR m.ml_title LIKE ? ESCAPE '\\' OR m.ml_title LIKE ? ESCAPE '\\'){where} "
           "ORDER BY CASE WHEN m.ml_title = ? COLLATE NOCASE THEN 0 WHEN m.ml_title = ? COLLATE NOCASE OR m.ml_title = ? COLLATE NOCASE OR m.ml_title LIKE ? ESCAPE '\\' THEN 1 ELSE 2 END, "
           f"m.n_ratings DESC, m.movie_id LIMIT {int(limit)}")
    substring = [f"%{_like_escape(title)}%", f"%{_like_escape(canonical)}%", f"%{_like_escape(stored)}%" if stored else None]
    tier = [title, canonical, stored, f"{_like_escape(stored)} (%" if stored else None]
    return sql, [*substring, *params, *tier]


def ml_by_tag(tag: str, genre: str | None, year_from: int | None, year_to: int | None, limit: int, type_: str | None = None) -> Query:
    """by_tag: every linked work with the tag; `type_` (film/series) narrows it, absent = all linked works (the kind is always in the result)."""
    where, params = _ml_filters(genre, year_from, year_to)
    if type_:
        where += f" AND m.work_kind IN ({_kinds(kinds_for(type_))})"
    return (f"SELECT {_ML_COLUMNS}, t.n_users AS tag_count FROM v_work_tag t JOIN v_ml_movie m ON m.work_id = t.work_id WHERE t.tag = ?{where} "
            f"ORDER BY t.n_users DESC, coalesce(m.avg_rating, 0) DESC, m.movie_id LIMIT {int(limit)}", [" ".join(tag.split()).casefold(), *params])


def ml_genre_stats(genre: str | None, year_from: int | None, year_to: int | None, min_ratings: int, limit: int) -> Query:
    clauses, params = [], [int(min_ratings)]
    if genre:
        clauses.append(" AND g.genre = ?")
        params.append(genre)
    if year_from:
        clauses.append(" AND m.ml_year >= ?")
        params.append(int(year_from))
    if year_to:
        clauses.append(" AND m.ml_year <= ?")
        params.append(int(year_to))
    return ("SELECT g.genre AS genre, count(*) AS n_movies, round(avg(m.avg_rating), 3) AS avg_rating, sum(m.n_ratings) AS n_ratings "
            f"FROM v_ml_genre g JOIN v_ml_movie m ON m.work_id = g.work_id WHERE m.work_kind IN ({_kinds(FILM_KINDS)}) AND m.n_ratings >= ?{''.join(clauses)} "
            f"GROUP BY g.genre ORDER BY avg_rating DESC, g.genre LIMIT {int(limit)}", params)
