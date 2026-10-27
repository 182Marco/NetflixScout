"""Collections (sagas) and production companies.

`/collection/{id}` does not support `append_to_response`: images and translations are
separate, optional calls, made only while the budget allows them.
"""
from __future__ import annotations

from typing import Any

from .. import endpoints
from ..context import TmdbContext
from ..http import get_json, optional_json
from ..models.enums import Facet, SearchKind
from ..models.requests import TmdbRequest
from ..models.results import RequestOutcome
from ..normalize import entities
from ..normalize.common import clean_text
from ..settings import REFERENCE_LANGUAGE
from .details import facet_options, facet_params, new_outcome
from .resolve import resolve_target


def collection_data(
    ctx: TmdbContext,
    collection_id: int,
    *,
    facets: list[Facet],
    outcome: RequestOutcome,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(collection, extra sections). Translations are fetched for a requested facet or
    when the localized overview is empty (fallback to English)."""
    data = get_json(ctx, endpoints.collection(collection_id, language=ctx.api_language))
    extra: dict[str, Any] = {}
    needs_fallback = not clean_text(data.get("overview")) and ctx.api_language != REFERENCE_LANGUAGE
    if Facet.translations in facets or needs_fallback:
        translations = optional_json(
            ctx,
            endpoints.collection_translations(collection_id),
            skipped=outcome.skipped_for_budget,
            label="translations",
        )
        if translations is not None:
            extra["translations"] = translations
    if Facet.images in facets:
        images = optional_json(
            ctx,
            endpoints.collection_images(collection_id, image_languages=facet_params(ctx, facets)["include_image_language"]),
            skipped=outcome.skipped_for_budget,
            label="images",
        )
        if images is not None:
            extra["images"] = images
    return data, extra


def collection_details(ctx: TmdbContext, request: TmdbRequest) -> RequestOutcome:
    resolution = resolve_target(ctx, request, SearchKind.collection)
    outcome = new_outcome(request, resolution)
    data, extra = collection_data(ctx, resolution.tmdb_id, facets=request.facets, outcome=outcome)
    outcome.entities.append(entities.collection(data, facet_options(ctx, request), extra))
    return outcome


def company_details(ctx: TmdbContext, request: TmdbRequest) -> RequestOutcome:
    resolution = resolve_target(ctx, request, SearchKind.company)
    outcome = new_outcome(request, resolution)
    outcome.entities.append(entities.company(get_json(ctx, endpoints.company(resolution.tmdb_id))))
    return outcome
