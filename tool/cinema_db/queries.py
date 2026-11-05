"""The SQL of the tool: constant fragments, bound parameters, integer limits already validated. Nothing the model wrote is ever spliced in.

Every function returns `(sql, params)` for `Session.query`, which still validates it against the approved views and columns: this module
chooses WHICH approved query to run, it does not widen what may be read. Lists in `IN (...)` are literals from `constants.py` or one `?` per id.
"""
from __future__ import annotations

from collections.abc import Sequence

from .constants import FILM_KINDS, SCREEN_KINDS, SERIES_KINDS

Query = tuple[str, list]


def _kinds(kinds: Sequence[str]) -> str:
    return ", ".join(f"'{k}'" for k in kinds)  # constants only


def _marks(n: int) -> str:
    return ", ".join("?" * n)


def kinds_for(type_: str | None) -> tuple[str, ...]:
    return FILM_KINDS if type_ == "film" else SERIES_KINDS if type_ == "series" else SCREEN_KINDS


_WORK_CARD = ("w.work_id AS work_id, w.kind AS kind, w.title AS title, w.original_title AS original_title, w.year AS year, w.end_year AS end_year, "
              "w.runtime_min AS runtime_min, w.status AS status, w.imdb_id AS imdb_id, w.tmdb_id AS tmdb_id, w.wikidata_id AS wikidata_id")


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


_PERSON_CARD = "p.person_id AS person_id, p.name AS name, p.birth_year AS birth_year, p.death_year AS death_year, p.birth_country AS birth_country, p.wikidata_id AS wikidata_id"


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
    return (f"SELECT person_id, person_name, character_name, credit_note FROM v_credit WHERE work_id = ? AND is_cast = 1 "
            f"ORDER BY character_name IS NULL, person_name LIMIT {int(limit)}", [work_id])


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
    ra, pa = (" AND a.role = ?", [role_a]) if role_a else ("", [])
    rb, pb = (" AND b.role = ?", [role_b]) if role_b else ("", [])
    return (f"SELECT b.person_id AS person_id, b.person_name AS person_name, count(DISTINCT a.work_id) AS works FROM v_credit a "
            f"JOIN v_credit b ON b.work_id = a.work_id WHERE a.person_id = ?{ra} AND b.person_id <> a.person_id{rb} "
            f"AND a.work_kind IN ({_kinds(SCREEN_KINDS)}) GROUP BY b.person_id, b.person_name ORDER BY works DESC, b.person_name LIMIT {int(limit)}", [person, *pa, *pb])


# ---- awards ---------------------------------------------------------------------------------------------------------------------
_AWARD_COLUMNS = ("award, category, category_scope AS scope, ceremony_year AS year, ceremony_edition AS edition, outcome, work_id, work_title, "
                  "work_year, person_id, person_name")


def _award_filters(outcome: str | None, year_from: int | None, year_to: int | None) -> tuple[str, list]:
    sql, params = _year_filters("ceremony_year", year_from, year_to)
    if outcome:
        sql += " AND outcome = ?"
        params.append(outcome)
    return sql, params


def awards_of(column: str, value: int, outcome: str | None, year_from: int | None, year_to: int | None, order: str, limit: int) -> Query:
    if column not in {"work_id", "person_id"}:
        raise ValueError("column not allowed")
    extra, params = _award_filters(outcome, year_from, year_to)
    direction = "DESC" if order == "desc" else "ASC"
    return (f"SELECT {_AWARD_COLUMNS} FROM v_award_result WHERE {column} = ?{extra} ORDER BY ceremony_year {direction}, award, category, outcome DESC LIMIT {int(limit)}",
            [value, *params])


def awards_by_name(pattern: str, outcome: str | None, year_from: int | None, year_to: int | None, order: str, limit: int) -> Query:
    extra, params = _award_filters(outcome, year_from, year_to)
    direction = "DESC" if order == "desc" else "ASC"
    return (f"SELECT {_AWARD_COLUMNS} FROM v_award_result WHERE (lower(award) LIKE ? OR lower(category) LIKE ?){extra} "
            f"ORDER BY ceremony_year {direction}, category, work_title LIMIT {int(limit)}", [pattern, pattern, *params])


def awards_count(column: str | None, value: object, pattern: str | None, outcome: str | None, year_from: int | None, year_to: int | None) -> Query:
    extra, params = _award_filters(outcome, year_from, year_to)
    if column:
        if column not in {"work_id", "person_id"}:
            raise ValueError("column not allowed")
        return f"SELECT count(*) AS n FROM v_award_result WHERE {column} = ?{extra}", [value, *params]
    return f"SELECT count(*) AS n FROM v_award_result WHERE (lower(award) LIKE ? OR lower(category) LIKE ?){extra}", [pattern, pattern, *params]


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


def names_of(work_id: int) -> Query:
    return "SELECT name, name_kind, language FROM v_name WHERE entity_id = ? AND entity_type = 'work' ORDER BY is_primary DESC, name_kind, name LIMIT 12", [work_id]


def credits_by_roles(work_id: int, roles: Sequence[str], limit: int) -> Query:
    return (f"SELECT person_id, person_name, role FROM v_credit WHERE work_id = ? AND role IN ({_marks(len(roles))}) "
            f"ORDER BY role, person_name LIMIT {int(limit)}", [work_id, *roles])


def genres_of(work_id: int) -> Query:
    return "SELECT DISTINCT genre FROM v_work_genre WHERE work_id = ? ORDER BY genre LIMIT 12", [work_id]


def countries_of(work_id: int) -> Query:
    return "SELECT DISTINCT country, iso2 FROM v_work_country WHERE work_id = ? AND role = 'origin' ORDER BY country LIMIT 12", [work_id]


def languages_of(work_id: int) -> Query:
    return "SELECT DISTINCT language FROM v_work_language WHERE work_id = ? ORDER BY language LIMIT 8", [work_id]


def money_of(work_id: int) -> Query:
    return "SELECT kind, scope, country, amount, currency, reference_year FROM v_work_financial WHERE work_id = ? ORDER BY kind, scope LIMIT 8", [work_id]
