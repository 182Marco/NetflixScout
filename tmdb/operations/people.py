"""People: details with credits and other facets in one `append_to_response` call."""
from __future__ import annotations

from .. import endpoints
from ..context import TmdbContext
from ..models.enums import SearchKind
from ..models.requests import TmdbRequest
from ..models.results import RequestOutcome
from ..normalize import entities
from .details import facet_options, facet_params, fetch_details, new_outcome
from .resolve import resolve_target

PERSON_ALWAYS = ("translations",)


def person_details(ctx: TmdbContext, request: TmdbRequest) -> RequestOutcome:
    resolution = resolve_target(ctx, request, SearchKind.person)
    outcome = new_outcome(request, resolution)
    endpoint = endpoints.details(
        "person",
        resolution.tmdb_id,
        language=ctx.api_language,
        appends=endpoints.append_keys(request.facets, always=PERSON_ALWAYS),
        extra=facet_params(ctx, request.facets),
    )
    data = fetch_details(
        ctx, endpoint, namespace="person", tmdb_id=resolution.tmdb_id, facets=request.facets, outcome=outcome
    )
    outcome.entities.append(entities.person(data, facet_options(ctx, request)))
    return outcome
