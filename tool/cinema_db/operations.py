"""The operations of `cinema_sql`: resolve the entity, run a few targeted queries, return a structured result with the data gaps stated.

Each function takes the validated request, the session and the row limit, and returns an `OpResult`. They never write SQL text of their own
(`queries.py` does) and never read outside the approved views (the session validates every statement).
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable

from . import queries as Q
from .constants import IDS_FOR_FIRST, MAX_LIMIT, SERIES_KINDS
from .models import CinemaSqlInput
from .names import normalize_name
from .resolve import AMBIGUOUS, NOT_FOUND, RESOLVED, UNVERIFIED, Resolution, resolve_named, resolve_person, resolve_work
from .session import Session

OK, EMPTY, ERROR = "ok", "empty", "error"


@dataclass
class OpResult:
    status: str                       # ok | empty | ambiguous | unverified | not_found | error
    reason: str | None = None
    subject: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    omitted: int = 0
    data: dict[str, Any] = field(default_factory=dict)
    total: int | None = None
    shown: int = 0
    truncated: bool = False
    notes: list[str] = field(default_factory=list)
    via: str | None = None


def _unresolved(res: Resolution, *, kind: str) -> OpResult:
    notes = ["unverified"] if res.status == UNVERIFIED else []
    return OpResult(res.status, reason=res.reason, candidates=res.candidates, omitted=res.omitted, notes=notes, via=res.via)


def _group(rows: list[dict[str, Any]], key: str, fields: tuple[str, ...], collect: dict[str, str]) -> list[dict[str, Any]]:
    """One entry per `key` (a work with several roles appears once), listing each `collect` column as a deduplicated list."""
    out: OrderedDict[Any, dict[str, Any]] = OrderedDict()
    for r in rows:
        item = out.setdefault(r[key], {**{f: r[f] for f in fields}, **{name: [] for name in collect.values()}})
        for column, name in collect.items():
            if r.get(column) is not None and r[column] not in item[name]:
                item[name].append(r[column])
    return list(out.values())


def _with_ids(session: Session, works: list[dict[str, Any]]) -> bool:
    """Add imdb_id and tmdb_id to the first works of a list (one query) so the next step can reuse them; returns True when some works got none
    only because the list is longer than `IDS_FOR_FIRST`. The tmdb id is meaningful with the kind (film or series): both are given."""
    head = works[:IDS_FOR_FIRST]
    if not head:
        return False
    found = {r["work_id"]: r for r in session.rows(*Q.external_ids_of([w["work_id"] for w in head]))}
    for w in head:
        ids = found.get(w["work_id"], {})
        for key in ("imdb_id", "tmdb_id"):
            if ids.get(key):
                w[key] = ids[key]
    return len(works) > IDS_FOR_FIRST


def _empty_or_ok(rows: Any, reason: str, **kwargs: Any) -> OpResult:
    return OpResult(OK if rows else EMPTY, reason=None if rows else reason, **kwargs)


# ---- identification ----------------------------------------------------------------------------------------------------------------
def find_work(request: CinemaSqlInput, session: Session, limit: int) -> OpResult:
    res = resolve_work(session, request)
    if res.status != RESOLVED:
        return _unresolved(res, kind="work")
    notes = [] if any(res.entity.get(k) for k in ("imdb_id", "tmdb_id", "wikidata_id")) else ["no_ids"]
    return OpResult(OK, subject={"kind": "work", **res.entity}, via=res.via, notes=notes)


def find_person(request: CinemaSqlInput, session: Session, limit: int) -> OpResult:
    res = resolve_person(session, name=request.person, person_id=request.person_id, wikidata_id=request.wikidata_id, birth_year=request.birth_year, include_roles=True)
    if res.status != RESOLVED:
        return _unresolved(res, kind="person")
    return OpResult(OK, subject={"kind": "person", **res.entity}, via=res.via, notes=["person"])


def work_card(request: CinemaSqlInput, session: Session, limit: int) -> OpResult:
    """Facts of one work in 5 queries after the identification: crew, genres, countries, companies and money (names and franchise have their own operations)."""
    res = resolve_work(session, request)
    if res.status != RESOLVED:
        return _unresolved(res, kind="work")
    wid = res.entity["work_id"]
    credits = session.rows(*Q.credits_by_roles(wid, ["writer", "composer"], 20))
    money = session.rows(*Q.money_of(wid))
    data = {
        "writers": [c["person_name"] for c in credits if c["role"] == "writer"],
        "composers": [c["person_name"] for c in credits if c["role"] == "composer"],
        "genres": [g["genre"] for g in session.rows(*Q.genres_of(wid))],
        "countries": [c["country"] for c in session.rows(*Q.countries_of(wid))],
        "companies": _group(session.rows(*Q.companies_of(wid, 12)), "role", ("role",), {"company": "companies"}),
        "money": money,
    }
    notes = ["coverage"] + (["money"] if money else [])
    return OpResult(OK, subject={"kind": "work", **res.entity}, data=data, via=res.via, notes=notes)


# ---- credits -----------------------------------------------------------------------------------------------------------------------
def filmography(request: CinemaSqlInput, session: Session, limit: int) -> OpResult:
    res = resolve_person(session, name=request.person, person_id=request.person_id, wikidata_id=request.wikidata_id, birth_year=request.birth_year, needs_credits=True)
    if res.status != RESOLVED:
        return _unresolved(res, kind="person")
    pid = res.entity["person_id"]
    args = (pid, request.role, request.type, request.year_from, request.year_to)
    rows = session.rows(*Q.filmography(*args, request.order, limit))
    total = session.rows(*Q.filmography_count(*args))[0]["works"]
    works = _group(rows, "work_id", ("work_id", "title", "year", "kind"), {"role": "roles"})
    notes = ["filmography"] + res.notes + (["ids_partial"] if _with_ids(session, works) else [])
    truncated = total > len(works)
    if truncated:
        notes.append("limit")
    return _empty_or_ok(works, "no_credits_in_catalogue", subject={"kind": "person", **res.entity}, data={"works": works}, total=total, shown=len(works),
                        truncated=truncated, notes=notes, via=res.via)


def cast(request: CinemaSqlInput, session: Session, limit: int) -> OpResult:
    res = resolve_work(session, request)
    if res.status != RESOLVED:
        return _unresolved(res, kind="work")
    wid = res.entity["work_id"]
    rows = session.rows(*Q.cast_of(wid, limit))
    total = session.rows(*Q.cast_count(wid))[0]["n"]
    people = [{"person_id": r["person_id"], "name": r["person_name"], "character": r["character_name"], "note": r["credit_note"]} for r in rows]
    notes = ["cast_order", "coverage"] + (["limit"] if total > len(people) else [])
    return _empty_or_ok(people, "no_cast_in_catalogue", subject={"kind": "work", **res.entity}, data={"cast": people}, total=total, shown=len(people),
                        truncated=total > len(people), notes=notes, via=res.via)


def crew(request: CinemaSqlInput, session: Session, limit: int) -> OpResult:
    res = resolve_work(session, request)
    if res.status != RESOLVED:
        return _unresolved(res, kind="work")
    rows = session.rows(*Q.crew_of(res.entity["work_id"], request.role, limit))
    crew_rows = _group(rows, "role", ("role",), {"person_name": "people"})
    return _empty_or_ok(crew_rows, "no_crew_in_catalogue", subject={"kind": "work", **res.entity}, data={"crew": crew_rows}, shown=len(rows),
                        truncated=len(rows) >= limit, notes=["coverage", "crew"] + (["limit"] if len(rows) >= limit else []), via=res.via)


def collaborations(request: CinemaSqlInput, session: Session, limit: int) -> OpResult:
    a = resolve_person(session, name=request.person, person_id=request.person_id, wikidata_id=request.wikidata_id, birth_year=request.birth_year, needs_credits=True)
    if a.status != RESOLVED:
        return _unresolved(a, kind="person")
    subject = {"kind": "person", **a.entity}
    if request.person_b is None and request.person_b_id is None:
        rows = session.rows(*Q.top_collaborators(a.entity["person_id"], request.role, request.role_b, limit))
        people = [{"person_id": r["person_id"], "name": r["person_name"], "works": r["works"]} for r in rows]
        return _empty_or_ok(people, "no_collaborators_in_catalogue", subject=subject, data={"collaborators": people}, shown=len(people),
                            truncated=len(people) >= limit, notes=["filmography"] + a.notes + (["limit"] if len(people) >= limit else []), via=a.via)
    b = resolve_person(session, name=request.person_b, person_id=request.person_b_id, wikidata_id=None, birth_year=None, needs_credits=True)
    if b.status != RESOLVED:
        out = _unresolved(b, kind="person")
        out.data = {"which": "second_person"}
        out.subject = subject
        return out
    if b.entity["person_id"] == a.entity["person_id"]:
        return OpResult(ERROR, reason="same_person", subject=subject)
    rows = session.rows(*Q.shared_works(a.entity["person_id"], b.entity["person_id"], request.role, request.role_b, request.order, MAX_LIMIT))
    works = _group(rows, "work_id", ("work_id", "title", "year", "kind"), {})
    for w in works:
        w["roles_of_first"] = sorted({r["role_a"] for r in rows if r["work_id"] == w["work_id"]})
        w["roles_of_second"] = sorted({r["role_b"] for r in rows if r["work_id"] == w["work_id"]})
    works = works[:limit]
    return _empty_or_ok(works, "no_shared_works_in_catalogue", subject=subject, data={"second_person": b.entity, "shared_works": works}, total=len(works), shown=len(works),
                        notes=["filmography"] + a.notes + b.notes, via=a.via)


# ---- awards ------------------------------------------------------------------------------------------------------------------------
def _like(text: str) -> str:
    cleaned = " ".join(text.replace("%", " ").replace("_", " ").casefold().split())
    return f"%{cleaned[:90]}%"


def awards(request: CinemaSqlInput, session: Session, limit: int) -> OpResult:
    has_work = any((request.title, request.work_id, request.imdb_id, request.tmdb_id)) or (request.wikidata_id and not request.person and not request.person_id)
    subject: dict[str, Any] | None = None
    column: str | None = None
    value: Any = None
    pattern: str | None = None
    via = None
    if has_work:
        res = resolve_work(session, request)
        if res.status != RESOLVED:
            return _unresolved(res, kind="work")
        column, value, subject, via = "work_id", res.entity["work_id"], {"kind": "work", **res.entity}, res.via
    elif request.person or request.person_id or request.wikidata_id:
        res = resolve_person(session, name=request.person, person_id=request.person_id, wikidata_id=request.wikidata_id, birth_year=request.birth_year)
        if res.status != RESOLVED:
            return _unresolved(res, kind="person")
        column, value, subject, via = "person_id", res.entity["person_id"], {"kind": "person", **res.entity}, res.via
    else:
        pattern = _like(request.award or "")
        if normalize_name(request.award or "") == "":
            return OpResult(NOT_FOUND, reason="no_award_name")
    if column:
        narrow = _like(request.award) if request.award and normalize_name(request.award) else None  # "Oscar" with a work or a person: only their Oscar results
        rows = session.rows(*Q.awards_of(column, value, request.outcome, request.year_from, request.year_to, request.order, limit, narrow))
        total = session.rows(*Q.awards_count(column, value, narrow, request.outcome, request.year_from, request.year_to))[0]["n"]
    else:
        exact = " ".join((request.award or "").casefold().split())
        rows = session.rows(*Q.awards_by_name(pattern, exact, request.outcome, request.year_from, request.year_to, request.order, limit))
        total = session.rows(*Q.awards_count(None, None, pattern, request.outcome, request.year_from, request.year_to))[0]["n"]
    notes = ["awards"] + (["awards_person_scope"] if column == "person_id" else []) + (["limit"] if total > len(rows) else [])
    return _empty_or_ok(rows, "no_award_results_recorded", subject=subject, data={"results": rows}, total=total, shown=len(rows), truncated=total > len(rows), notes=notes, via=via)


# ---- series ------------------------------------------------------------------------------------------------------------------------
def series(request: CinemaSqlInput, session: Session, limit: int) -> OpResult:
    scoped = request if request.type else request.model_copy(update={"type": "series"})
    res = resolve_work(session, scoped)
    if res.status != RESOLVED:
        return _unresolved(res, kind="work")
    entity = res.entity
    subject = {"kind": "work", **entity}
    if entity["kind"] not in SERIES_KINDS:
        return OpResult(EMPTY, reason="not_a_series", subject=subject, via=res.via)
    sid = entity["work_id"]
    seasons = session.rows(*Q.seasons_of(sid, MAX_LIMIT))
    if request.season is None:
        counts: dict[int, tuple[int, int]] = {}
        ids = [s["work_id"] for s in seasons] + [sid]
        for i in range(0, len(ids), 15):
            for r in session.rows(*Q.episode_counts(ids[i:i + 15])):
                counts[r["parent_work_id"]] = (r["episodes"], r["numbered"])
        # `episodes` counts every episode row of the catalogue; `numbered_episodes` only those with a number, the safer count: an episode known both
        # from its own page and from a table row can appear twice, once without a number.
        listed = [{"season_number": s["season_number"], "title": s["title"], "episodes": counts.get(s["work_id"], (0, 0))[0],
                   "numbered_episodes": counts.get(s["work_id"], (0, 0))[1]} for s in seasons]
        loose = counts.get(sid, (0, 0))[0]
        return _empty_or_ok(listed or loose, "no_seasons_in_catalogue", subject=subject, data={"seasons": listed, "episodes_without_season": loose}, shown=len(listed),
                            notes=["series", "episode_duplicates"], via=res.via)
    season_row = next((s for s in seasons if s["season_number"] == request.season), None)
    rows = session.rows(*(Q.episodes_of(season_row["work_id"], None, limit) if season_row else Q.episodes_of(sid, request.season, limit)))
    total = None
    notes_extra: list[str] = []
    if season_row:
        total = (session.rows(*Q.episode_counts([season_row["work_id"]])) or [{"episodes": 0}])[0]["episodes"]
        notes_extra = ["episode_duplicates"]
    episodes = [{"episode_number": r["episode_number"], "title": r["title"], "original_title": r["original_title"], "date": r["release_date"]} for r in rows]
    truncated = total is not None and total > len(episodes)
    return _empty_or_ok(episodes, "season_or_episodes_not_in_catalogue", subject=subject, data={"season": request.season, "episodes": episodes}, total=total, shown=len(episodes),
                        truncated=truncated, notes=["series"] + notes_extra + (["limit"] if truncated else []), via=res.via)


# ---- companies, franchise, relations -----------------------------------------------------------------------------------------------
def companies(request: CinemaSqlInput, session: Session, limit: int) -> OpResult:
    if any((request.title, request.work_id, request.imdb_id, request.tmdb_id, request.wikidata_id)):
        res = resolve_work(session, request)
        if res.status != RESOLVED:
            return _unresolved(res, kind="work")
        rows = session.rows(*Q.companies_of(res.entity["work_id"], limit))
        grouped = _group(rows, "role", ("role",), {"company": "companies"})
        return _empty_or_ok(grouped, "no_company_recorded", subject={"kind": "work", **res.entity}, data={"companies": grouped}, shown=len(rows), notes=["companies"], via=res.via)
    res = resolve_named(session, "company", request.company or "")
    if res.status != RESOLVED:
        return _unresolved(res, kind="company")
    rows = session.rows(*Q.works_of_company(res.entity["company_id"], limit))
    works = _group(rows, "work_id", ("work_id", "title", "year"), {"role": "roles"})
    return _empty_or_ok(works, "no_work_recorded_for_company", subject={"kind": "company", **res.entity}, data={"works": works}, shown=len(works),
                        truncated=len(rows) >= limit, notes=["companies"] + (["limit"] if len(rows) >= limit else []))


def franchise(request: CinemaSqlInput, session: Session, limit: int) -> OpResult:
    if any((request.title, request.work_id, request.imdb_id, request.tmdb_id, request.wikidata_id)):
        res = resolve_work(session, request)
        if res.status != RESOLVED:
            return _unresolved(res, kind="work")
        subject, via = {"kind": "work", **res.entity}, res.via
        found = session.rows(*Q.franchise_of(res.entity["work_id"]))
    else:
        named = resolve_named(session, "franchise", request.franchise or "")
        if named.status != RESOLVED:
            return _unresolved(named, kind="franchise")
        subject, via = {"kind": "franchise", **named.entity}, None
        found = [{"franchise_id": named.entity["franchise_id"], "franchise": named.entity["name"]}]
    listed = []
    for f in found[:2]:
        members = session.rows(*Q.franchise_members(f["franchise_id"], limit))
        partial = _with_ids(session, members)
        listed.append({"franchise": f["franchise"], "members": members, "truncated": len(members) >= limit, "ids_partial": partial})
    cut = any(f["truncated"] for f in listed)
    return _empty_or_ok(listed, "no_franchise_recorded", subject=subject, data={"franchises": listed}, shown=sum(len(f["members"]) for f in listed), truncated=cut,
                        notes=["franchise"] + (["limit"] if cut else []) + (["ids_partial"] if any(f["ids_partial"] for f in listed) else []), via=via)


def relations(request: CinemaSqlInput, session: Session, limit: int) -> OpResult:
    res = resolve_work(session, request)
    if res.status != RESOLVED:
        return _unresolved(res, kind="work")
    rows = session.rows(*Q.relations_of(res.entity["work_id"], limit))
    listed = [{"relation": r["relation_label"], "direction": r["direction"], "work_id": r["related_work_id"], "title": r["related_title"],
               "kind": r["related_kind"], "year": r["related_year"]} for r in rows]
    return _empty_or_ok(listed, "no_relation_recorded", subject={"kind": "work", **res.entity}, data={"relations": listed}, shown=len(listed),
                        truncated=len(rows) >= limit, notes=["relations"], via=res.via)


def sql(request: CinemaSqlInput, session: Session, limit: int) -> OpResult:
    result = session.query(request.sql or "", request.params or [])
    rows = [dict(zip(result.columns, r)) for r in result.rows]
    return _empty_or_ok(rows, "no_rows", data={"columns": list(result.columns), "rows": rows}, shown=len(rows), truncated=result.truncated,
                        notes=["coverage"] + (["limit"] if result.truncated else []))


OPERATIONS: dict[str, Callable[[CinemaSqlInput, Session, int], OpResult]] = {
    "find_work": find_work, "work_card": work_card, "find_person": find_person, "filmography": filmography, "cast": cast, "crew": crew,
    "collaborations": collaborations, "awards": awards, "series": series, "companies": companies, "franchise": franchise, "relations": relations, "sql": sql,
}
