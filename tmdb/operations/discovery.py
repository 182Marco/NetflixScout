"""Discover movies and series by filters. Names (genres, people, companies, keywords,
providers) are resolved to IDs first; if any cannot be resolved, discover is not run,
because partial filters would return wrong results."""
from __future__ import annotations

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
        DiscoverSort.votes_desc: "vote_count.desc",
        DiscoverSort.release_date_desc: "primary_release_date.desc",
        DiscoverSort.release_date_asc: "primary_release_date.asc",
        DiscoverSort.revenue_desc: "revenue.desc",
    },
    MediaType.tv: {
        DiscoverSort.popularity_desc: "popularity.desc",
        DiscoverSort.rating_desc: "vote_average.desc",
        DiscoverSort.votes_desc: "vote_count.desc",
        DiscoverSort.release_date_desc: "first_air_date.desc",
        DiscoverSort.release_date_asc: "first_air_date.asc",
    },
}
_DATE_FIELD = {MediaType.movie: "primary_release_date", MediaType.tv: "first_air_date"}


def _ids(ctx: TmdbContext, kind: SearchKind, names: list[str]) -> list[str]:
    try:
        return [str(resolve(ctx, kind, text=name).tmdb_id) for name in names]
    except TmdbNotFound:
        raise TmdbUnresolvedFilter(f"A {kind.value} name in the filters could not be resolved.") from None


def build_params(ctx: TmdbContext, media: MediaType, filters: DiscoverFilters) -> dict[str, str]:
    sort = filters.sort or DiscoverSort.popularity_desc
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
    if filters.people:
        params["with_people"] = ",".join(_ids(ctx, SearchKind.person, filters.people))
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
    elif sort is DiscoverSort.rating_desc:
        params["vote_count.gte"] = str(MIN_VOTES_FOR_RATING_SORT)
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
    data = get_json(ctx, endpoints.discover(media, build_params(ctx, media, filters)))
    outcome = list_outcome(ctx, request, data, kind=media.value)
    if filters.watch_providers:
        outcome.attribution = reference.JUSTWATCH
    return outcome


def discover_movies(ctx: TmdbContext, request: TmdbRequest) -> RequestOutcome:
    return _discover(ctx, request, MediaType.movie)


def discover_tv(ctx: TmdbContext, request: TmdbRequest) -> RequestOutcome:
    return _discover(ctx, request, MediaType.tv)
