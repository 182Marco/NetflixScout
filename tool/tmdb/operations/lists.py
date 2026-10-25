"""Trending and current charts (popular, top rated, now playing, upcoming, on the air)."""
from __future__ import annotations

from .. import endpoints
from ..context import TmdbContext
from ..http import get_json
from ..models.requests import TmdbRequest
from ..models.results import RequestOutcome
from .listing import list_outcome


def trending(ctx: TmdbContext, request: TmdbRequest) -> RequestOutcome:
    data = get_json(ctx, endpoints.trending(request.media, request.window, language=ctx.api_language))
    return list_outcome(ctx, request, data, kind=request.media.value)


def chart(ctx: TmdbContext, request: TmdbRequest) -> RequestOutcome:
    endpoint = endpoints.chart(request.media, request.chart, language=ctx.api_language, region=request.region)
    return list_outcome(ctx, request, get_json(ctx, endpoint), kind=request.media.value)
