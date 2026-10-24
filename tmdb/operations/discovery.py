"""Discover movies and series by filters. Names (genres, people, companies, keywords,
providers) are resolved to IDs first; if any cannot be resolved, discover is not run,
because partial filters would return wrong results."""
from __future__ import annotations

from typing import Any

from .. import endpoints
from ..context import TmdbContext
from ..errors import TmdbNotFound, TmdbUnresolvedFilter
from ..http import get_json
from ..models.enums import (
    RELEASE_TYPE_CODES,
    TV_STATUS_CODES,
    TV_TYPE_CODES,
    DiscoverSort,
    MediaType,
    SearchKind,
)
from ..models.requests import DiscoverFilters, TmdbRequest
from ..models.results import RequestOutcome
from . import reference
from .listing import list_outcome
from .resolve import resolve

# Sorting by rating without a vote floor surfaces obscure titles with a handful of votes.
MIN_VOTES_FOR_RATING_SORT = 200

_SORTS = {
    MediaType.movie: {
        DiscoverSort.popularity_desc: "popularity.desc",
        DiscoverSort.rating_desc: "vote_average.desc",
        DiscoverSort.rating_asc: "vote_average.asc",
        DiscoverSort.votes_desc: "vote_count.desc",
        DiscoverSort.release_date_desc: "primary_release_date.desc",
        DiscoverSort.release_date_asc: "primary_release_date.asc",
        DiscoverSort.revenue_desc: "revenue.desc",
    },
    MediaType.tv: {
        DiscoverSort.popularity_desc: "popularity.desc",
        DiscoverSort.rating_desc: "vote_average.desc",
        DiscoverSort.rating_asc: "vote_average.asc",
        DiscoverSort.votes_desc: "vote_count.desc",
        DiscoverSort.release_date_desc: "first_air_date.desc",
        DiscoverSort.release_date_asc: "first_air_date.asc",
    },
}
_DATE_FIELD = {MediaType.movie: "primary_release_date", MediaType.tv: "first_air_date"}


def _resolved(ctx: TmdbContext, kind: SearchKind, names: list[str]) -> list[tuple[str, str]]:
    """(name, TMDb ID) per requested name; the name is the one TMDb matched."""
    try:
        resolutions = [(name, resolve(ctx, kind, text=name)) for name in names]
    except TmdbNotFound:
        raise TmdbUnresolvedFilter(f"A {kind.value} name in the filters could not be resolved.") from None
    return [(found.title or name, str(found.tmdb_id)) for name, found in resolutions]


def _ids(ctx: TmdbContext, kind: SearchKind, names: list[str]) -> list[str]:
    return [tmdb_id for _, tmdb_id in _resolved(ctx, kind, names)]


def build_params(
    ctx: TmdbContext,
    media: MediaType,
    filters: DiscoverFilters,
    applied: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Query parameters of `/discover`. `applied`, when given, receives what the filters
    resolved to (names as TMDb matched them, IDs, sort, rating range, vote floor)."""
    applied = applied if applied is not None else {}
    sort = filters.sort or DiscoverSort.popularity_desc
    applied["sort"] = sort.value
    params = {"language": ctx.api_language, "sort_by": _SORTS[media][sort]}
    if media is MediaType.movie:
        params["include_video"] = "false"
    date_field = _DATE_FIELD[media]
    if filters.year_from:
        params[f"{date_field}.gte"] = f"{filters.year_from}-01-01"
    if filters.year_to:
        params[f"{date_field}.lte"] = f"{filters.year_to}-12-31"
    # Genres and people: all must match (","); companies, keywords, providers: any (|).
    if filters.genres:
        params["with_genres"] = ",".join(str(i) for i in reference.genre_ids(ctx, media, filters.genres))
    for field, param in (("people", "with_people"), ("cast", "with_cast")):
        names = getattr(filters, field)
        if names:
            found = _resolved(ctx, SearchKind.person, names)
            params[param] = ",".join(tmdb_id for _, tmdb_id in found)
            applied[field] = [{"name": name, "tmdb_id": int(tmdb_id)} for name, tmdb_id in found]
    if filters.companies:
        params["with_companies"] = "|".join(_ids(ctx, SearchKind.company, filters.companies))
    if filters.keywords:
        params["with_keywords"] = "|".join(_ids(ctx, SearchKind.keyword, filters.keywords))
    if filters.min_rating is not None:
        params["vote_average.gte"] = str(filters.min_rating)
    if filters.max_rating is not None:
        params["vote_average.lte"] = str(filters.max_rating)
    if filters.min_votes is not None:
        params["vote_count.gte"] = str(filters.min_votes)
    elif sort in (DiscoverSort.rating_desc, DiscoverSort.rating_asc):
        params["vote_count.gte"] = str(MIN_VOTES_FOR_RATING_SORT)
    for field, param in (
        ("min_rating", "vote_average.gte"),
        ("max_rating", "vote_average.lte"),
        ("vote_count", "vote_count.gte"),
    ):
        if param in params:
            applied[field] = float(params[param]) if "rating" in field else int(params[param])
    for field in ("genres", "year_from", "year_to"):
        value = getattr(filters, field)
        if value:
            applied[field] = value
    if filters.min_runtime is not None:
        params["with_runtime.gte"] = str(filters.min_runtime)
    if filters.max_runtime is not None:
        params["with_runtime.lte"] = str(filters.max_runtime)
    if filters.original_language:
        params["with_original_language"] = filters.original_language
    if filters.origin_country:
        params["with_origin_country"] = filters.origin_country
    if filters.watch_providers:
        provider_ids = reference.provider_ids(ctx, media, filters.watch_region, filters.watch_providers)
        params["with_watch_providers"] = "|".join(str(i) for i in provider_ids)
        params["watch_region"] = filters.watch_region
    if filters.monetization:
        params["with_watch_monetization_types"] = "|".join(m.value for m in filters.monetization)
    if filters.certification:
        params["certification"] = filters.certification
        params["certification_country"] = filters.certification_country
    if filters.release_types:
        params["with_release_type"] = "|".join(str(RELEASE_TYPE_CODES[t]) for t in filters.release_types)
        params["region"] = filters.region
    if filters.tv_status is not None:
        params["with_status"] = str(TV_STATUS_CODES[filters.tv_status])
    if filters.tv_type is not None:
        params["with_type"] = str(TV_TYPE_CODES[filters.tv_type])
    return params


def _discover(ctx: TmdbContext, request: TmdbRequest, media: MediaType) -> RequestOutcome:
    filters = request.filters or DiscoverFilters()
    applied: dict[str, Any] = {}
    data = get_json(ctx, endpoints.discover(media, build_params(ctx, media, filters, applied)))
    outcome = list_outcome(ctx, request, data, kind=media.value)
    outcome.applied_filters = applied
    # TMDb has no critics' scores: the ratings used for filtering and sorting are user votes.
    outcome.notes.append("ratings_are_tmdb_user_votes")
    if filters.watch_providers:
        outcome.attribution = reference.JUSTWATCH
    return outcome


def discover_movies(ctx: TmdbContext, request: TmdbRequest) -> RequestOutcome:
    return _discover(ctx, request, MediaType.movie)


def discover_tv(ctx: TmdbContext, request: TmdbRequest) -> RequestOutcome:
    return _discover(ctx, request, MediaType.tv)
