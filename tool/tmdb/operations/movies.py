"""Movies: details with facets in one `append_to_response` call, and the movie's collection."""
from __future__ import annotations

from typing import Any

from .. import endpoints
from ..context import TmdbContext
from ..models.enums import Facet, SearchKind
from ..models.requests import TmdbRequest
from ..models.results import RequestOutcome
from ..normalize import entities
from .collections import collection_data
from .details import facet_options, facet_params, fetch_details, new_outcome
from .resolve import resolve_target

# Always appended (free): see `endpoints.IDENTITY_APPENDS`.
MOVIE_ALWAYS = endpoints.MOVIE_IDENTITY_APPENDS


def _movie_data(ctx: TmdbContext, tmdb_id: int, facets: list[Facet], outcome: RequestOutcome) -> dict[str, Any]:
    endpoint = endpoints.details(
        "movie",
        tmdb_id,
        language=ctx.api_language,
        appends=endpoints.append_keys(facets, always=MOVIE_ALWAYS),
        extra=facet_params(ctx, facets),
    )
    return fetch_details(ctx, endpoint, namespace="movie", tmdb_id=tmdb_id, facets=facets, outcome=outcome)


def movie_details(ctx: TmdbContext, request: TmdbRequest) -> RequestOutcome:
    resolution = resolve_target(ctx, request, SearchKind.movie)
    outcome = new_outcome(request, resolution)
    data = _movie_data(ctx, resolution.tmdb_id, request.facets, outcome)
    outcome.entities.append(entities.movie(data, facet_options(ctx, request)))
    return outcome


def movie_collection(ctx: TmdbContext, request: TmdbRequest) -> RequestOutcome:
    resolution = resolve_target(ctx, request, SearchKind.movie)
    outcome = new_outcome(request, resolution)
    # No facets: same request (and cache entry) as a plain `movie_details`.
    data = _movie_data(ctx, resolution.tmdb_id, [], outcome)
    collection = data.get("belongs_to_collection")
    if not isinstance(collection, dict) or not isinstance(collection.get("id"), int):
        outcome.notes.append("movie_has_no_collection")
        outcome.entities.append(entities.movie(data, facet_options(ctx, request)))
        return outcome
    collection_raw, extra = collection_data(ctx, collection["id"], facets=[], outcome=outcome)
    outcome.entities.append(entities.collection(collection_raw, facet_options(ctx, request), extra))
    return outcome
