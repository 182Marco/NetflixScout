"""Entity resolution: which work, person, company or franchise does the request mean? Pure decisions over rows read through the guarded session.

Rules (same spirit as the OMDb and Wikidata tools): an identifier is the identity; a name must match exactly after normalisation (titles,
translated and original titles and aliases all count) and, when given, the year, the type and the director must agree; several matches are
`ambiguous` (alternatives listed, no data); only similar names are `unverified` (alternatives, never taken for the answer); nothing is
`not_found`. A missing field is never a match, and nothing is merged: two Wikidata items for one film are two candidates.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import queries as Q
from .constants import CANDIDATE_FETCH, MAX_CANDIDATES, SCREEN_KINDS
from .models import CinemaSqlInput
from .names import fts_query, normalize_name
from .session import Session

RESOLVED, AMBIGUOUS, UNVERIFIED, NOT_FOUND = "resolved", "ambiguous", "unverified", "not_found"
_KIND_ORDER = {k: i for i, k in enumerate(SCREEN_KINDS)}


@dataclass
class Resolution:
    status: str
    entity: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    omitted: int = 0
    reason: str | None = None
    via: str = "name"
    notes: list[str] = field(default_factory=list)


# ---- works -----------------------------------------------------------------------------------------------------------------------
def _year_ok(row: dict[str, Any], year: int | None) -> bool:
    if year is None:
        return True
    start, end = row.get("year"), row.get("end_year")
    return start == year or (start is not None and end is not None and start <= year <= end)


def _director_ok(directors: list[str], wanted: str | None) -> bool:
    if not wanted:
        return True
    tokens = normalize_name(wanted).split()
    return any(tokens and all(t in normalize_name(d).split() for t in tokens) for d in directors)


def _order(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda r: (_KIND_ORDER.get(r["kind"], 9), r.get("year") or 9999, r.get("title") or ""))


def _dedupe(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    seen: dict[Any, dict[str, Any]] = {}
    for r in rows:
        seen.setdefault(r[key], r)
    return list(seen.values())


MAX_DIRECTORS = 4  # a series lists the directors of every episode: the identity keeps a few and says how many there are


def _compact(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None and v != []}


def work_identity(row: dict[str, Any], directors: list[str]) -> dict[str, Any]:
    out = {
        "work_id": row["work_id"], "kind": row["kind"], "title": row["title"], "original_title": row.get("original_title"), "year": row.get("year"),
        "end_year": row.get("end_year"), "runtime_min": row.get("runtime_min"), "status": row.get("status"), "directors": directors[:MAX_DIRECTORS],
        "imdb_id": row.get("imdb_id"), "tmdb_id": row.get("tmdb_id"), "wikidata_id": row.get("wikidata_id"), "wikipedia_it": row.get("wikipedia_it"),
    }
    if len(directors) > MAX_DIRECTORS:
        out["directors_total"] = len(directors)
    return _compact(out)


def _directors(session: Session, work_ids: list[int]) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    if work_ids:
        for r in session.rows(*Q.directors_of(work_ids[:CANDIDATE_FETCH])):
            out.setdefault(r["work_id"], []).append(r["person_name"])
    return out


def _work_candidates(session: Session, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    rows = _order(rows)
    shown = rows[:MAX_CANDIDATES]
    dirs = _directors(session, [r["work_id"] for r in shown])
    return [work_identity(r, dirs.get(r["work_id"], [])) for r in shown], len(rows) - len(shown)


def _by_ids(session: Session, request: CinemaSqlInput) -> Resolution | None:
    found: dict[int, dict[str, Any]] = {}
    asked = 0
    lookups: list[tuple[str, Any]] = []
    if request.work_id is not None:
        asked += 1
        lookups.append(("work_id", request.work_id))
    if request.imdb_id:
        asked += 1
        lookups.append(("imdb_title", request.imdb_id))
    if request.wikidata_id:
        asked += 1
        lookups.append(("wikidata", request.wikidata_id))
    if request.tmdb_id is not None:
        asked += 1
        lookups.append(("tmdb_tv" if request.type == "series" else "tmdb_movie", request.tmdb_id))
    if not lookups:
        return None
    for scheme, value in lookups:
        ids = [value] if scheme == "work_id" else [r["work_id"] for r in session.rows(*Q.work_ids_by_external(scheme, value))]
        for wid in ids:
            for row in session.rows(*Q.works_by_column("work_id", wid)):
                found[row["work_id"]] = row
    if not found:
        return Resolution(NOT_FOUND, reason="id_unknown", via="id")
    if len(found) > 1:  # identifiers pointing at different works: never pick one
        cands, omitted = _work_candidates(session, list(found.values()))
        return Resolution(AMBIGUOUS, candidates=cands, omitted=omitted, reason="ids_disagree", via="id")
    row = next(iter(found.values()))
    return Resolution(RESOLVED, entity=work_identity(row, _directors(session, [row["work_id"]]).get(row["work_id"], [])), via="id")


def resolve_work(session: Session, request: CinemaSqlInput, *, allow_any_kind: bool = False) -> Resolution:
    by_id = _by_ids(session, request)
    if by_id is not None:
        return by_id
    title = (request.title or "").strip()
    norm = normalize_name(title)
    if not norm:
        return Resolution(NOT_FOUND, reason="no_title")
    kinds = Q.kinds_for(request.type)
    rows = _dedupe(session.rows(*Q.works_by_name(norm, kinds, CANDIDATE_FETCH)), "work_id")
    if rows:
        matching = [r for r in rows if _year_ok(r, request.year)]
        if request.director and matching:
            dirs = _directors(session, [r["work_id"] for r in matching])
            matching = [r for r in matching if _director_ok(dirs.get(r["work_id"], []), request.director)]
        if len(matching) == 1:
            row = matching[0]
            return Resolution(RESOLVED, entity=work_identity(row, _directors(session, [row["work_id"]]).get(row["work_id"], [])))
        if len(matching) > 1:
            cands, omitted = _work_candidates(session, matching)
            return Resolution(AMBIGUOUS, candidates=cands, omitted=omitted)
        cands, omitted = _work_candidates(session, rows)  # the title exists but not with the given year or director
        return Resolution(UNVERIFIED, candidates=cands, omitted=omitted, reason="filters_not_matched")
    fts = fts_query(title)
    similar = _dedupe(session.rows(*Q.works_by_title_search(fts, kinds, CANDIDATE_FETCH)), "work_id") if fts else []
    if similar:
        cands, omitted = _work_candidates(session, similar)
        return Resolution(UNVERIFIED, candidates=cands, omitted=omitted, reason="similar_names_only", via="search")
    return Resolution(NOT_FOUND, reason="title_unknown")


# ---- people ----------------------------------------------------------------------------------------------------------------------
def person_identity(row: dict[str, Any], roles: dict[str, int] | None = None) -> dict[str, Any]:
    out = {"person_id": row["person_id"], "name": row["name"], "birth_year": row.get("birth_year"), "death_year": row.get("death_year"),
           "birth_country": row.get("birth_country"), "wikidata_id": row.get("wikidata_id"), "wikipedia_it": row.get("wikipedia_it")}
    if roles is not None:
        out["credits_by_role"] = roles
    return _compact(out)


def _roles(session: Session, ids: list[int]) -> dict[int, dict[str, int]]:
    out: dict[int, dict[str, int]] = {}
    if ids:
        for r in session.rows(*Q.role_counts(ids[:MAX_CANDIDATES])):
            out.setdefault(r["person_id"], {})[r["role"]] = r["n"]
    return out


def _person_candidates(session: Session, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    rows = sorted(rows, key=lambda r: (r.get("birth_year") or 9999, r["name"] or ""))
    shown = rows[:MAX_CANDIDATES]
    roles = _roles(session, [r["person_id"] for r in shown])
    return [person_identity(r, roles.get(r["person_id"], {})) for r in shown], len(rows) - len(shown)


def resolve_person(session: Session, *, name: str | None, person_id: int | None, wikidata_id: str | None, birth_year: int | None,
                   needs_credits: bool = False, include_roles: bool = False) -> Resolution:
    """`include_roles` adds the credit counts per role to the identity of a RESOLVED person (an extra query: only identification asks for it);
    candidates always carry them, because they are what tells namesakes apart."""
    if person_id is not None or wikidata_id:
        rows = session.rows(*(Q.persons_by_column("person_id", person_id) if person_id is not None else Q.persons_by_column("wikidata_id", wikidata_id)))
        if not rows:
            return Resolution(NOT_FOUND, reason="id_unknown", via="id")
        row = rows[0]
        return Resolution(RESOLVED, entity=person_identity(row, _roles(session, [row["person_id"]]).get(row["person_id"], {}) if include_roles else None), via="id")
    norm = normalize_name(name or "")
    if not norm:
        return Resolution(NOT_FOUND, reason="no_name")
    rows = _dedupe(session.rows(*Q.persons_by_name(norm, CANDIDATE_FETCH)), "person_id")
    if rows:
        matching = [r for r in rows if birth_year is None or r.get("birth_year") == birth_year]
        notes: list[str] = []
        if len(matching) > 1 and needs_credits:
            # Namesakes that only exist as an award nominee have no credits to list: ignore them, say so (never silently).
            roles = _roles(session, [r["person_id"] for r in matching[:MAX_CANDIDATES]])
            with_credits = [r for r in matching if roles.get(r["person_id"])]
            if len(matching) <= MAX_CANDIDATES and len(with_credits) == 1:
                notes.append("namesakes_without_credits_ignored")
                matching = with_credits
        if len(matching) == 1:
            row = matching[0]
            return Resolution(RESOLVED, entity=person_identity(row, _roles(session, [row["person_id"]]).get(row["person_id"], {}) if include_roles else None), notes=notes)
        if len(matching) > 1:
            cands, omitted = _person_candidates(session, matching)
            return Resolution(AMBIGUOUS, candidates=cands, omitted=omitted)
        cands, omitted = _person_candidates(session, rows)
        return Resolution(UNVERIFIED, candidates=cands, omitted=omitted, reason="filters_not_matched")
    fts = fts_query(name or "")
    similar = _dedupe(session.rows(*Q.persons_by_title_search(fts, CANDIDATE_FETCH)), "person_id") if fts else []
    if similar:
        cands, omitted = _person_candidates(session, similar)
        return Resolution(UNVERIFIED, candidates=cands, omitted=omitted, reason="similar_names_only", via="search")
    return Resolution(NOT_FOUND, reason="name_unknown")


# ---- companies and franchises (exact name only) ----------------------------------------------------------------------------------
def resolve_named(session: Session, kind: str, name: str) -> Resolution:
    norm = normalize_name(name)
    if not norm:
        return Resolution(NOT_FOUND, reason="no_name")
    build = Q.companies_by_name if kind == "company" else Q.franchises_by_name
    key = "company_id" if kind == "company" else "franchise_id"
    rows = _dedupe(session.rows(*build(norm, CANDIDATE_FETCH)), key)
    if not rows:
        return Resolution(NOT_FOUND, reason=f"{kind}_unknown")
    if len(rows) == 1:
        return Resolution(RESOLVED, entity={key: rows[0][key], "name": rows[0]["name"]})
    shown = rows[:MAX_CANDIDATES]
    return Resolution(AMBIGUOUS, candidates=[{key: r[key], "name": r["name"]} for r in shown], omitted=len(rows) - len(shown))
