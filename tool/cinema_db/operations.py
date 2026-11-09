"""The operations of `cinema_sql`: resolve the entity, run a few targeted queries, return a structured result with the data gaps stated.

Each function takes the validated request, the session and the row limit, and returns an `OpResult`. They never write SQL text of their own
(`queries.py` does) and never read outside the approved views (the session validates every statement).
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable

from . import queries as Q
from .constants import IDS_FOR_FIRST, MAX_LIMIT, ML_MIN_RATINGS, SERIES_KINDS
from .models import CinemaSqlInput
from .names import normalize_name
from .resolve import AMBIGUOUS, NOT_FOUND, RESOLVED, UNVERIFIED, Resolution, resolve_named, resolve_person, resolve_work
from .ml_titles import normalize_title
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
    if session.schema >= 3:  # only the levels that are not 'verified' are written (the absence of the key means verified)
        levels = {r["work_id"]: r["identity_level"] for r in session.rows(*Q.identity_of([w["work_id"] for w in head]))}
        for w in head:
            if levels.get(w["work_id"]) not in (None, "verified"):
                w["identity_level"] = levels[w["work_id"]]
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
    people = [{"person_id": r["person_id"], "name": r["person_name"], "character": r["character_name"], "note": r["credit_note"],
               **({"billing_order": r["billing_order"]} if r.get("billing_order") is not None else {})} for r in rows]
    ordered = any(p.get("billing_order") is not None for p in people)  # schema 3: the first credited people carry IMDb's order
    notes = ["cast_order_partial" if ordered else "cast_order", "coverage"] + (["limit"] if total > len(people) else [])
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
        if request.year and request.year_from is None and request.year_to is None:  # «who won the Oscar in 1995»: with no work to identify, `year` can only be the ceremony's
            request = request.model_copy(update={"year_from": request.year, "year_to": request.year})
    if column:
        narrow = _like(request.award) if request.award and normalize_name(request.award) else None  # "Oscar" with a work or a person: only their Oscar results
        rows = session.rows(*Q.awards_of(column, value, request.outcome, request.year_from, request.year_to, request.order, MAX_LIMIT, narrow))
        total = session.rows(*Q.awards_count(column, value, narrow, request.outcome, request.year_from, request.year_to))[0]["n"]
    else:
        exact = " ".join((request.award or "").casefold().split())
        rows = session.rows(*Q.awards_by_name(pattern, exact, request.outcome, request.year_from, request.year_to, request.order, MAX_LIMIT))
        total = session.rows(*Q.awards_count(None, None, pattern, request.outcome, request.year_from, request.year_to))[0]["n"]
    results = _awards_with_people(rows)[:limit]
    notes = ["awards"] + (["awards_person_scope"] if column == "person_id" else []) + (["limit"] if total > len(results) else [])
    return _empty_or_ok(results, "no_award_results_recorded", subject=subject, data={"results": results}, total=total, shown=len(results), truncated=total > len(results), notes=notes, via=via)


def _awards_with_people(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per award (ceremony year, award, category, outcome, work) with the names of the people who share it: counting a prize once per recipient would make
    «how many Oscars» answer with the number of statuettes handed out, not of awards."""
    grouped: OrderedDict[tuple, dict[str, Any]] = OrderedDict()
    for r in rows:
        key = (r["year"], r["award"], r["category"], r["outcome"], r["work_id"])
        entry = grouped.setdefault(key, {**{k: v for k, v in r.items() if k not in {"person_id", "person_name"}}, "people": []})
        if r.get("person_name") and r["person_name"] not in entry["people"]:
            entry["people"].append(r["person_name"])
    return list(grouped.values())


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


def relation_nature(relation: str, direction: str, kind: str | None, related_kind: str | None) -> str:
    """What a stored relation proves, from the kinds of the two works (the database has no `remake_of` rows: no source states one).

    - `adaptation_of_non_screen_work`: the work is based on something that is not a film or a series (a novel, a comic, a play, a game): an adaptation, by definition.
    - `based_on_screen_work`: a film or series based on another film or series: a remake, a reboot or a derived work, which the data does not tell apart.
    - `adapted_into_screen_work` (a novel and the film made from it) and `source_of_screen_work` (a film that another film is based on): the inverse direction, with the same limits; `order_in_series`: comes after/before, not a statement of sequel, prequel or reboot."""
    screen = ("film", "short", "tv_film", "series", "miniseries")
    if relation == "follows":
        return "order_in_series"
    if direction == "forward":
        return "adaptation_of_non_screen_work" if related_kind not in screen and kind in screen else "based_on_screen_work"
    return "adapted_into_screen_work" if kind not in screen and related_kind in screen else "source_of_screen_work"


def relations(request: CinemaSqlInput, session: Session, limit: int) -> OpResult:
    res = resolve_work(session, request)
    if res.status != RESOLVED:
        return _unresolved(res, kind="work")
    rows = session.rows(*Q.relations_of(res.entity["work_id"], limit))
    listed = [{"relation": r["relation_label"], "direction": r["direction"], "work_id": r["related_work_id"], "title": r["related_title"],
               "kind": r["related_kind"], "year": r["related_year"], "nature": relation_nature(r["relation"], r["direction"], res.entity.get("kind"), r["related_kind"])} for r in rows]
    return _empty_or_ok(listed, "no_relation_recorded", subject={"kind": "work", **res.entity}, data={"relations": listed}, shown=len(listed),
                        truncated=len(rows) >= limit, notes=["relations"], via=res.via)


# ---- schema 3 only: ratings and provenance --------------------------------------------------------------------------------------
NOT_IN_THIS_DATABASE = "not_in_this_database"


def ratings(request: CinemaSqlInput, session: Session, limit: int) -> OpResult:
    """Audience ratings and vote counts of one work, or (no work given) the best rated titles. Only the reconciled database has them."""
    if session.schema < 3:
        return OpResult(EMPTY, reason=NOT_IN_THIS_DATABASE)
    if any((request.title, request.work_id, request.imdb_id, request.tmdb_id, request.wikidata_id)):
        res = resolve_work(session, request)
        if res.status != RESOLVED:
            return _unresolved(res, kind="work")
        rows = session.rows(*Q.ratings_of(res.entity["work_id"]))
        listed = [{"source": r["source"], "audience": r["audience"], "rating": r["rating"], "scale_max": r["scale_max"], "votes": r["vote_count"], "as_of": r["as_of"]} for r in rows]
        return _empty_or_ok(listed, "no_rating_recorded", subject={"kind": "work", **res.entity}, data={"ratings": listed}, shown=len(listed), notes=["ratings"], via=res.via)
    min_votes = request.min_votes or 1000
    rows = session.rows(*Q.top_rated(request.type, request.year_from, request.year_to, min_votes, limit))
    listed = [{"work_id": r["work_id"], "title": r["title"], "year": r["year"], "kind": r["kind"], "rating": r["rating"], "scale_max": r["scale_max"], "votes": r["vote_count"]} for r in rows]
    _with_ids(session, listed)
    return _empty_or_ok(listed, "no_rated_title_in_catalogue", data={"ranking": listed, "min_votes": min_votes, "as_of": rows[0]["as_of"] if rows else None}, shown=len(listed),
                        truncated=len(listed) >= limit, notes=["ratings", "ratings_ranking"] + ([] if request.type else ["ratings_mixed_types"]) + (["limit"] if len(listed) >= limit else []))


def movielens(request: CinemaSqlInput, session: Session, limit: int) -> OpResult:
    """The six lists of the old MovieLens tool, on the MovieLens tables of the v4 file: rankings, title search, tag search, mean per genre."""
    if not session.movielens:
        return OpResult(EMPTY, reason=NOT_IN_THIS_DATABASE)
    mode, min_ratings = request.ml_mode, request.min_votes or ML_MIN_RATINGS
    if mode == "genre_stats":
        rows = session.rows(*Q.ml_genre_stats(request.genre, request.year_from, request.year_to, min_ratings, limit))
        listed = [{"genre": r["genre"], "films": r["n_movies"], "avg_rating": r["avg_rating"], "ratings": r["n_ratings"]} for r in rows]
        return _empty_or_ok(listed, "no_genre_in_range", data={"mode": mode, "genres": listed, "scale_max": 5, "min_ratings": min_ratings}, shown=len(listed),
                            notes=["movielens", "movielens_genres", "movielens_films_only"])
    if mode in {"top_rated", "most_rated"}:
        rows = session.rows(*Q.ml_ranking("rating" if mode == "top_rated" else "count", request.genre, request.year_from, request.year_to, min_ratings, limit))
    elif mode == "by_title":
        rows = session.rows(*Q.ml_by_title(request.title or "", request.genre, request.year_from, request.year_to, limit))
    else:
        rows = session.rows(*Q.ml_by_tag(request.tag or "", request.genre, request.year_from, request.year_to, limit, request.type))
    listed = []
    for r in rows:
        item = {"work_id": r["work_id"], "imdb_id": r["imdb_id"], "title": r["title"] or normalize_title(r["ml_title"]), "year": r["year"], "kind": r["kind"], "avg_rating": r["avg_rating"],
                "ratings": r["n_ratings"], "genres": sorted((r["genres"] or "").split("|")) if r["genres"] else []}
        if r["status"] != "in_catalogue":
            item.update({"status": "excluded", "reason": r["reason"], "title": normalize_title(r["ml_title"])})
        if "tag_count" in r:
            item["tag_users"] = r["tag_count"]
        listed.append(item)
    return _empty_or_ok(listed, "no_movielens_film_found", data={"mode": mode, "movies": listed, "scale_max": 5, "min_ratings": min_ratings if mode in {"top_rated", "most_rated"} else None},
                        shown=len(listed), truncated=len(listed) >= limit, notes=["movielens", "movielens_genres"] + (["movielens_any_kind"] if mode == "by_tag" and not request.type else []) + (["limit"] if len(listed) >= limit else []))


def provenance(request: CinemaSqlInput, session: Session, limit: int) -> OpResult:
    """Where the facts about a work or a person come from: every identifier (primary or alternative), the identification level, values that lost a priority
    decision, and identifiers that were suspected but NOT attached. Candidates and claims are information about the data, never facts about the film."""
    if session.schema < 3:
        return OpResult(EMPTY, reason=NOT_IN_THIS_DATABASE)
    has_work = any((request.title, request.work_id, request.imdb_id, request.tmdb_id)) or (request.wikidata_id and not request.person and not request.person_id)
    if has_work:
        res = resolve_work(session, request)
        kind, key = "work", "work_id"
    else:
        res = resolve_person(session, name=request.person, person_id=request.person_id, wikidata_id=request.wikidata_id, birth_year=request.birth_year)
        kind, key = "person", "person_id"
    if res.status != RESOLVED:
        return _unresolved(res, kind=kind)
    eid = res.entity[key]
    merged: list[dict[str, Any]] = []
    group = [eid]
    if kind == "person":  # a person merged into another is the same human: read the claims and candidates of the whole group
        merged = [{"merged_person_id": r["merged_entity_id"], "merged_name": r["merged_name"], "canonical_person_id": r["canonical_entity_id"], "reason": r["reason"]}
                  for r in session.rows(*Q.merged_into(eid))]
        group = sorted({eid, *[m["merged_person_id"] for m in merged], *[m["canonical_person_id"] for m in merged]})[:8]
    ids = [{"scheme": r["scheme"], "value": r["value"], "primary": bool(r["is_primary"])} for r in session.rows(*Q.ids_of_entity(eid))]
    claims = [{"field": r["field"], "value": r["value"], "source": r["source"], "source_ref": r["source_ref"]} for r in session.rows(*Q.claims_of(group, limit))]
    candidates = [{"scheme": r["scheme"], "value": r["value"], "tier": r["tier"], "evidence": r["evidence"]} for r in session.rows(*Q.candidates_of(group, limit))]
    data: dict[str, Any] = {"identifiers": ids, "claims": claims, "candidates_not_attached": candidates}
    if kind == "work":
        status = session.rows(*Q.status_of(eid))
        if status:
            data["identification"] = {"entry_route": status[0]["entry_route"], "identification": status[0]["identification"], "identity_level": status[0]["identity_level"],
                                      "completeness": status[0]["completeness"], "plot_status": status[0]["plot_status"]}
    else:
        data["merged_persons"] = merged
    shown = len(ids) + len(claims) + len(candidates)
    return OpResult(OK if shown or data.get("identification") else EMPTY, reason=None if shown else "no_provenance_recorded", subject={"kind": kind, **res.entity}, data=data,
                    shown=shown, truncated=len(claims) >= limit or len(candidates) >= limit, notes=["provenance"] + (["limit"] if len(claims) >= limit or len(candidates) >= limit else []), via=res.via)


def sql(request: CinemaSqlInput, session: Session, limit: int) -> OpResult:
    result = session.query(request.sql or "", request.params or [])
    rows = [dict(zip(result.columns, r)) for r in result.rows]
    return _empty_or_ok(rows, "no_rows", data={"columns": list(result.columns), "rows": rows}, shown=len(rows), truncated=result.truncated,
                        notes=["coverage"] + (["limit"] if result.truncated else []))


OPERATIONS: dict[str, Callable[[CinemaSqlInput, Session, int], OpResult]] = {
    "find_work": find_work, "work_card": work_card, "find_person": find_person, "filmography": filmography, "cast": cast, "crew": crew,
    "collaborations": collaborations, "awards": awards, "series": series, "companies": companies, "franchise": franchise, "relations": relations, "ratings": ratings, "movielens": movielens, "provenance": provenance, "sql": sql,
}
