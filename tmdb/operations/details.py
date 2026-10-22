"""Shared steps of detail operations: facet parameters, fallbacks and normalizer options."""
from __future__ import annotations

from typing import Any

from .. import endpoints
from ..context import TmdbContext
from ..http import get_json, optional_json
from ..models.enums import Facet
from ..models.requests import TmdbRequest
from ..models.results import RequestOutcome
from ..normalize.common import language_code
from ..normalize.entities import FacetOptions
from ..settings import DEFAULT_REGION, REFERENCE_LANGUAGE
from .resolve import ALTERNATIVE_TITLE_MATCH, YEAR_FROM_RELEASE_DATES, Resolution


def facet_params(ctx: TmdbContext, facets: list[Facet]) -> dict[str, str]:
    """Language fallbacks for appended images and videos: no extra call needed."""
    code = language_code(ctx.api_language)
    params: dict[str, str] = {}
    if Facet.images in facets:
        params["include_image_language"] = ",".join(dict.fromkeys([code, "en", "null"]))
    if Facet.videos in facets:
        params["include_video_language"] = ",".join(dict.fromkeys([code, "en"]))
    return params


def facet_options(ctx: TmdbContext, request: TmdbRequest) -> FacetOptions:
    return FacetOptions(
        facets=tuple(request.facets),
        region=request.region or DEFAULT_REGION,
        api_language=ctx.api_language,
        limit=ctx.limit(None),
    )


def new_outcome(request: TmdbRequest, resolution: Resolution | None = None) -> RequestOutcome:
    outcome = RequestOutcome(
        operation=request.operation.value,
        candidates=list(resolution.candidates) if resolution else [],
    )
    if resolution is not None and resolution.via_alternative_title:
        # The requested title is not TMDb's own title for this work, only one of its
        # translated or alternative titles: the answer must say which title TMDb uses.
        outcome.notes.append(ALTERNATIVE_TITLE_MATCH)
    if resolution is not None and resolution.year_from_release_dates:
        # The year matched a secondary release date: the answer must give both years.
        outcome.notes.append(YEAR_FROM_RELEASE_DATES)
    return outcome


def fetch_details(
    ctx: TmdbContext,
    endpoint: endpoints.Endpoint,
    *,
    namespace: str,
    tmdb_id: int,
    facets: list[Facet],
    outcome: RequestOutcome,
) -> dict[str, Any]:
    """Main call, then optional fallbacks only while the budget allows them.

    - `watch/providers` as an append value is not spelled out in the docs: if the key is
      missing, one separate call is made (counted).
    - Appended reviews follow `language`: if none come back in the turn language, one
      English call is made (counted).
    """
    data = get_json(ctx, endpoint)
    if namespace not in ("movie", "tv"):
        return data
    if Facet.watch_providers in facets and "watch/providers" not in data:
        providers = optional_json(
            ctx,
            endpoints.watch_providers(namespace, tmdb_id),
            skipped=outcome.skipped_for_budget,
            label="watch_providers",
        )
        if providers is not None:
            data = {**data, "watch/providers": providers}
    if (
        Facet.reviews in facets
        and ctx.api_language != REFERENCE_LANGUAGE
        and not (data.get("reviews") or {}).get("results")
    ):
        reviews = optional_json(
            ctx,
            endpoints.reviews(namespace, tmdb_id, language=REFERENCE_LANGUAGE),
            skipped=outcome.skipped_for_budget,
            label="reviews_en",
        )
        if reviews is not None:
            data = {**data, "reviews": reviews}
    return data
