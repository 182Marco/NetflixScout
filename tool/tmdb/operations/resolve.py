"""Search and ID resolution for movies, series, people, collections, companies and keywords.

Priority: TMDb ID (no call) → external ID (`/find`) → text search. The choice among search
results is deterministic: exact (original or translated) title → same year → year ±1 →
known-for department → most popular. Resolutions are memoized for the turn, and the TTL
cache makes repeated searches free across turns.

Movies and series are works with an identity: a result is accepted only if its title or
original title is the requested one (accents kept first, then ignored) and, when a year
is given, its year is within ±1. Otherwise `TmdbUnverifiedMatch` reports the closest
results as unverified alternatives instead of picking the most popular one. A title in
another language (e.g. English in an Italian turn) gets one more search in English
(counted). With `ctx.strict_identity` several equally good matches are refused too.

When no result has the requested title, or none has a compatible year, a result is still
accepted if its *own* TMDb record proves both: the title is one of its translated or
alternative titles, or its title with or without a leading article ("The Dungeon of
Harrow"); the year is within ±1 of any release date TMDb records for it (premieres,
other countries). At most `MAX_ALTERNATIVE_CHECKS` results are checked, with the details
call the details operation makes next (`endpoints.identity_appends`). Two verified works
are ambiguous; none leaves the request unverified. Containment never counts: "The
Sinner" is not "The Sinners". "&" reads "and" ("Mars & Avril").
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .. import endpoints
from ..context import TmdbContext
from ..errors import TmdbNotFound, TmdbUnverifiedMatch
from ..http import get_json
from ..models.enums import DEPARTMENT_NAMES, Department, ExternalSource, SearchKind
from ..models.requests import TmdbRequest
from ..models.results import RequestOutcome
from ..normalize.common import article_free_name, clean_text, normalize_name, strict_name, year_of
from ..settings import REFERENCE_LANGUAGE
from .listing import list_outcome

MAX_CANDIDATES = 3
# Results whose translated/alternative titles are checked when no title matches (1 call each).
MAX_ALTERNATIVE_CHECKS = 2
ALTERNATIVE_TITLE_MATCH = "alternative_title_match"
YEAR_FROM_RELEASE_DATES = "year_from_release_dates"

# (title key, original title key, date key) of each kind's search results.
_FIELDS: dict[SearchKind, tuple[str, str | None, str | None]] = {
    SearchKind.movie: ("title", "original_title", "release_date"),
    SearchKind.tv: ("name", "original_name", "first_air_date"),
    SearchKind.person: ("name", "original_name", None),
    SearchKind.collection: ("name", "original_name", None),
    SearchKind.company: ("name", None, None),
    SearchKind.keyword: ("name", None, None),
}
_YEAR_KINDS = (SearchKind.movie, SearchKind.tv)
_FIND_RESULTS = {
    "movie_results": "movie",
    "tv_results": "tv",
    "person_results": "person",
}
_FIND_KEY = {SearchKind.movie: "movie_results", SearchKind.tv: "tv_results", SearchKind.person: "person_results"}


@dataclass(frozen=True)
class Resolution:
    tmdb_id: int
    title: str | None = None
    candidates: tuple[dict[str, Any], ...] = ()
    # True when the requested title is only a translated/alternative title of this work.
    via_alternative_title: bool = False
    # True when the year is confirmed by a secondary TMDb release date, not the primary one.
    year_from_release_dates: bool = False


def _results(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for r in data.get("results") or [] if isinstance(r, dict) and isinstance(r.get("id"), int)]


def _search(
    ctx: TmdbContext, kind: SearchKind, text: str, year: int | None, *, language: str | None = None
) -> list[dict[str, Any]]:
    return _results(get_json(ctx, endpoints.search(kind, text, language=language or ctx.api_language, year=year)))


def _exact_matches(kind: SearchKind, results: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    """Results whose title or original title is `text`: with accents if any, else without."""
    title_key, original_key, _ = _FIELDS[kind]

    def titles(result: dict[str, Any]) -> list[Any]:
        return [result.get(title_key), result.get(original_key) if original_key else None]

    for key in (strict_name, normalize_name):
        wanted = key(text)
        exact = [r for r in results if wanted and wanted in {key(t) for t in titles(r)}]
        if exact:
            return exact
    return []


def _candidate_rows(kind: SearchKind, results: list[dict[str, Any]], exclude: int | None = None) -> tuple[dict[str, Any], ...]:
    title_key, _, date_key = _FIELDS[kind]
    return tuple(
        {
            "tmdb_id": r["id"],
            "title": clean_text(r.get(title_key)),
            "year": year_of(r.get(date_key)) if date_key else None,
        }
        for r in results
        if r["id"] != exclude
    )[:MAX_CANDIDATES]


def _pick_work(
    kind: SearchKind,
    results: list[dict[str, Any]],
    text: str,
    year: int | None,
    *,
    strict_identity: bool,
) -> Resolution:
    """Movie or series: only a verified title (and year, when given) is accepted."""
    _, _, date_key = _FIELDS[kind]
    by_popularity = sorted(results, key=lambda r: r.get("popularity") or 0, reverse=True)
    exact = _exact_matches(kind, results, text)
    if not exact:
        raise TmdbUnverifiedMatch("title_mismatch", _candidate_rows(kind, by_popularity))
    pool = exact
    if year is not None:
        same = [r for r in exact if year_of(r.get(date_key)) == year]
        near = [r for r in exact if (y := year_of(r.get(date_key))) is not None and abs(y - year) == 1]
        pool = same or near
        if not pool:
            raise TmdbUnverifiedMatch("year_mismatch", _candidate_rows(kind, exact))
    if strict_identity and len(pool) > 1:
        raise TmdbUnverifiedMatch("ambiguous", _candidate_rows(kind, pool))
    best = max(pool, key=lambda r: r.get("popularity") or 0)  # first wins on ties: deterministic
    candidates = _candidate_rows(kind, exact, exclude=best["id"]) if len(exact) > 1 else ()
    return Resolution(best["id"], clean_text(best.get(_FIELDS[kind][0])), candidates)


def _known_titles(kind: SearchKind, data: dict[str, Any]) -> list[str]:
    """Every title TMDb associates with this one work: own, original, translated, alternative."""
    title_key, original_key, _ = _FIELDS[kind]
    titles = [data.get(title_key), data.get(original_key) if original_key else None]
    for translation in (data.get("translations") or {}).get("translations") or []:
        titles.append((translation.get("data") or {}).get(title_key))
    alternative = data.get("alternative_titles") or {}
    # Movies list them under "titles", series under "results".
    for item in alternative.get("titles") or alternative.get("results") or []:
        titles.append(item.get("title") if isinstance(item, dict) else None)
    return [title for title in titles if isinstance(title, str) and title.strip()]


def _release_years(kind: SearchKind, data: dict[str, Any]) -> set[int]:
    """Primary year plus every release date TMDb records for this work (movies only)."""
    _, _, date_key = _FIELDS[kind]
    years = {year_of(data.get(date_key))}
    for country in (data.get("release_dates") or {}).get("results") or []:
        for item in country.get("release_dates") or [] if isinstance(country, dict) else []:
            years.add(year_of(item.get("release_date")) if isinstance(item, dict) else None)
    return {year for year in years if year is not None}


def _title_tier(text: str, own: list[Any], known: list[str]) -> str | None:
    """'own' (TMDb title or original), 'alternative' (translated/alternative title or the same
    title with or without a leading article) or None. Never a contained title."""
    for key in (strict_name, normalize_name):
        if key(text) and key(text) in {key(title) for title in own}:
            return "own"
    for key in (strict_name, normalize_name, article_free_name):
        if key(text) and key(text) in {key(title) for title in known}:
            return "alternative"
    return None


def _verify_by_details(
    ctx: TmdbContext, kind: SearchKind, results: list[dict[str, Any]], text: str, year: int | None
) -> Resolution | None:
    """The single work whose own TMDb record proves both title and year, if any.

    Checked (at most `MAX_ALTERNATIVE_CHECKS`, one details call each, the same call the
    details operation makes next): first the results whose title differs only by a leading
    article, then those with a compatible year (without a year: only a lone search result). The title must be one TMDb lists for that
    work; the year must be within ±1 of any release date TMDb records for it.
    """
    title_key, original_key, date_key = _FIELDS[kind]
    namespace = "movie" if kind is SearchKind.movie else "tv"
    wanted = article_free_name(text)

    def same_title(result: dict[str, Any]) -> bool:
        return bool(wanted) and wanted in {
            article_free_name(result.get(title_key)), article_free_name(result.get(original_key) if original_key else None)
        }

    def near_year(result: dict[str, Any]) -> bool:
        return year is None or ((y := year_of(result.get(date_key))) is not None and abs(y - year) <= 1)

    # Without a year a different title is checked only when TMDb found that single work for
    # the text: checking unrelated titles costs calls and proves nothing (real case: tv "Dune"
    # checked "Dune: Prophecy" and "I figli di Dune").
    if year is not None:
        by_year = [r for r in results if near_year(r) and not same_title(r)]
    else:
        by_year = [r for r in results if not same_title(r)] if len(results) == 1 else []
    ordered = [r for r in results if same_title(r)] + by_year
    verified = []
    for result in ordered[:MAX_ALTERNATIVE_CHECKS]:
        try:
            data = get_json(
                ctx,
                endpoints.details(
                    namespace, result["id"], language=ctx.api_language, appends=endpoints.identity_appends(namespace)
                ),
            )
        except TmdbNotFound:
            continue
        own = [data.get(title_key), data.get(original_key) if original_key else None]
        tier = _title_tier(text, own, _known_titles(kind, data))
        if tier is None:
            continue
        if year is not None and not any(abs(y - year) <= 1 for y in _release_years(kind, data)):
            continue
        primary = year_of(data.get(date_key))
        primary_ok = year is None or (primary is not None and abs(primary - year) <= 1)
        verified.append((result, tier, primary_ok))
    if len(verified) > 1:
        raise TmdbUnverifiedMatch("ambiguous", _candidate_rows(kind, [result for result, _, _ in verified]))
    if not verified:
        return None
    best, tier, primary_ok = verified[0]
    return Resolution(
        best["id"],
        clean_text(best.get(title_key)),
        (),
        via_alternative_title=tier == "alternative",
        year_from_release_dates=not primary_ok,
    )


def _pick(
    kind: SearchKind,
    results: list[dict[str, Any]],
    text: str,
    year: int | None,
    department: Department | None,
) -> Resolution:
    title_key, original_key, date_key = _FIELDS[kind]
    wanted = normalize_name(text)
    exact = [
        r for r in results
        if wanted in {normalize_name(r.get(title_key)), normalize_name(r.get(original_key) if original_key else None)}
    ]
    base = exact or results
    pool = base
    if year is not None and date_key:
        same = [r for r in pool if year_of(r.get(date_key)) == year]
        near = [r for r in pool if (y := year_of(r.get(date_key))) is not None and abs(y - year) == 1]
        pool = same or near or pool
    if department is not None:
        in_department = [r for r in pool if r.get("known_for_department") == DEPARTMENT_NAMES[department]]
        pool = in_department or pool
    best = max(pool, key=lambda r: r.get("popularity") or 0)  # first wins on ties: deterministic

    candidates: tuple[dict[str, Any], ...] = ()
    if len(exact) != 1:
        candidates = tuple(
            {
                "tmdb_id": r["id"],
                "title": clean_text(r.get(title_key)),
                "year": year_of(r.get(date_key)) if date_key else None,
            }
            for r in base
            if r["id"] != best["id"]
        )[:MAX_CANDIDATES]
    return Resolution(best["id"], clean_text(best.get(title_key)), candidates)


def _resolve_external(ctx: TmdbContext, kind: SearchKind, external_id: str, source: ExternalSource) -> Resolution:
    data = get_json(ctx, endpoints.find(external_id, source, language=ctx.api_language))
    matches = _results({"results": data.get(_FIND_KEY[kind])})
    if not matches:
        raise TmdbNotFound(f"No {kind.value} matches the external ID.")
    title_key = _FIELDS[kind][0]
    return Resolution(matches[0]["id"], clean_text(matches[0].get(title_key)))


def resolve(
    ctx: TmdbContext,
    kind: SearchKind,
    *,
    text: str | None = None,
    year: int | None = None,
    tmdb_id: int | None = None,
    external_id: str | None = None,
    external_source: ExternalSource | None = None,
    department: Department | None = None,
) -> Resolution:
    if tmdb_id:
        return Resolution(tmdb_id)
    if external_id and external_source:
        return _resolve_external(ctx, kind, external_id, external_source)
    if not text:
        raise TmdbNotFound(f"No {kind.value} to resolve.")

    key = (kind.value, normalize_name(text), year, department)
    if key in ctx.resolutions:
        return ctx.resolutions[key]
    search_year = year if kind in _YEAR_KINDS and not ctx.year_after_search else None
    results = _search(ctx, kind, text, search_year)
    if not results and search_year is not None:
        # Release years are often off by one: one more search without the year (counted).
        results = _search(ctx, kind, text, None)
    if not results:
        raise TmdbNotFound(f"No {kind.value} matches the requested name.")
    if kind in _YEAR_KINDS:
        resolution = _resolve_work(ctx, kind, results, text, year, search_year)
    else:
        resolution = _pick(kind, results, text, year, department)
    ctx.resolutions[key] = resolution
    return resolution


def _resolve_work(
    ctx: TmdbContext,
    kind: SearchKind,
    results: list[dict[str, Any]],
    text: str,
    year: int | None,
    search_year: int | None,
) -> Resolution:
    try:
        return _pick_work(kind, results, text, year, strict_identity=ctx.strict_identity)
    except TmdbUnverifiedMatch as exc:
        if exc.reason not in ("title_mismatch", "year_mismatch"):
            raise
        searched = list(results)
        if ctx.year_after_search and year is not None:
            # Nothing usable on the year-less page: one search with TMDb's year filter (counted).
            filtered = _search(ctx, kind, text, year)
            try:
                return _pick_work(kind, filtered, text, year, strict_identity=ctx.strict_identity)
            except TmdbUnverifiedMatch:
                seen = {r["id"] for r in searched}
                searched += [r for r in filtered if r["id"] not in seen]
        if exc.reason == "title_mismatch" and ctx.api_language != REFERENCE_LANGUAGE:
            # The user may have written the English title in a non-English turn (counted call).
            english = _search(ctx, kind, text, search_year, language=REFERENCE_LANGUAGE)
            try:
                return _pick_work(kind, english, text, year, strict_identity=ctx.strict_identity)
            except TmdbUnverifiedMatch:
                seen = {r["id"] for r in searched}
                searched += [r for r in english if r["id"] not in seen]
        alternative = _verify_by_details(ctx, kind, searched, text, year)
        if alternative is not None:
            return alternative
        raise exc from None


def resolve_target(ctx: TmdbContext, request: TmdbRequest, kind: SearchKind) -> Resolution:
    return resolve(
        ctx,
        kind,
        text=request.title or request.name,
        year=request.year,
        tmdb_id=request.tmdb_id,
        external_id=request.external_id,
        external_source=request.external_source,
        department=request.department,
    )


def search_operation(ctx: TmdbContext, request: TmdbRequest) -> RequestOutcome:
    data = get_json(
        ctx,
        endpoints.search(request.kind, request.search_query, language=ctx.api_language, year=request.year),
    )
    return list_outcome(ctx, request, data, kind=request.kind.value)


def find_operation(ctx: TmdbContext, request: TmdbRequest) -> RequestOutcome:
    data = get_json(ctx, endpoints.find(request.external_id, request.external_source, language=ctx.api_language))
    merged = [
        {"media_type": kind, **item}
        for key, kind in _FIND_RESULTS.items()
        for item in _results({"results": data.get(key)})
    ]
    outcome = list_outcome(ctx, request, {"results": merged}, kind="movie")
    if not outcome.items:
        outcome.notes.append("no_match_for_external_id")
    return outcome
