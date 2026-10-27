"""TV series, seasons and episodes: one `append_to_response` call each after resolution."""
from __future__ import annotations

from .. import endpoints
from ..context import TmdbContext
from ..models.enums import SearchKind
from ..models.requests import TmdbRequest
from ..models.results import RequestOutcome
from ..normalize import entities
from .details import facet_options, facet_params, fetch_details, new_outcome
from .resolve import resolve_target

TV_ALWAYS = endpoints.IDENTITY_APPENDS
PART_ALWAYS = ("translations",)


def tv_details(ctx: TmdbContext, request: TmdbRequest) -> RequestOutcome:
    resolution = resolve_target(ctx, request, SearchKind.tv)
    outcome = new_outcome(request, resolution)
    endpoint = endpoints.details(
        "tv",
        resolution.tmdb_id,
        language=ctx.api_language,
        appends=endpoints.append_keys(request.facets, always=TV_ALWAYS),
        extra=facet_params(ctx, request.facets),
    )
    data = fetch_details(
        ctx, endpoint, namespace="tv", tmdb_id=resolution.tmdb_id, facets=request.facets, outcome=outcome
    )
    outcome.entities.append(entities.tv(data, facet_options(ctx, request)))
    return outcome


def tv_season(ctx: TmdbContext, request: TmdbRequest) -> RequestOutcome:
    resolution = resolve_target(ctx, request, SearchKind.tv)
    outcome = new_outcome(request, resolution)
    endpoint = endpoints.tv_season(
        resolution.tmdb_id,
        request.season,
        language=ctx.api_language,
        appends=endpoints.append_keys(request.facets, always=PART_ALWAYS),
        extra=facet_params(ctx, request.facets),
    )
    data = fetch_details(
        ctx, endpoint, namespace="season", tmdb_id=resolution.tmdb_id, facets=request.facets, outcome=outcome
    )
    outcome.entities.append(
        entities.season(data, facet_options(ctx, request), series_id=resolution.tmdb_id, series_title=resolution.title)
    )
    return outcome


def tv_episode(ctx: TmdbContext, request: TmdbRequest) -> RequestOutcome:
    resolution = resolve_target(ctx, request, SearchKind.tv)
    outcome = new_outcome(request, resolution)
    endpoint = endpoints.tv_episode(
        resolution.tmdb_id,
        request.season,
        request.episode,
        language=ctx.api_language,
        appends=endpoints.append_keys(request.facets, always=PART_ALWAYS),
        extra=facet_params(ctx, request.facets),
    )
    data = fetch_details(
        ctx, endpoint, namespace="episode", tmdb_id=resolution.tmdb_id, facets=request.facets, outcome=outcome
    )
    outcome.entities.append(
        entities.episode(data, facet_options(ctx, request), series_id=resolution.tmdb_id, series_title=resolution.title)
    )
    return outcome
