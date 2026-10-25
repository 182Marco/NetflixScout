"""Reference data: genres, streaming providers, certifications.

Used internally to turn names into IDs (matched in English, `REFERENCE_LANGUAGE`) and
exposed as operations. Always through `get_json`: cached and counted like any call.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .. import endpoints
from ..context import TmdbContext
from ..errors import TmdbUnresolvedFilter
from ..http import get_json, optional_json
from ..models.enums import MediaType
from ..models.requests import TmdbRequest
from ..models.results import RequestOutcome
from ..normalize.common import clean_text, normalize_name, truncate
from ..settings import DEFAULT_REGION, REFERENCE_LANGUAGE

MEANING_CHARS = 160
JUSTWATCH = "justwatch"


def _genre_table(data: dict[str, Any]) -> dict[int, str]:
    return {g["id"]: g["name"] for g in data.get("genres") or [] if isinstance(g, dict) and g.get("id") and g.get("name")}


def genre_names(ctx: TmdbContext, media_kinds: Iterable[str], skipped: list[str]) -> dict[int, str]:
    """Genre id → name for list results; optional, so lists still work without it."""
    table: dict[int, str] = {}
    for kind in media_kinds:
        data = optional_json(
            ctx,
            endpoints.genre_list(MediaType(kind), language=REFERENCE_LANGUAGE),
            skipped=skipped,
            label=f"genre_names_{kind}",
        )
        table.update(_genre_table(data or {}))
    return table


def _match(wanted: str, table: dict[str, int], what: str) -> int:
    key = normalize_name(wanted)
    if key in table:
        return table[key]
    partial = [value for name, value in table.items() if key and (key in name or name in key)]
    if len(set(partial)) == 1:
        return partial[0]
    raise TmdbUnresolvedFilter(f"A {what} name in the filters could not be matched.")


def genre_ids(ctx: TmdbContext, media: MediaType, wanted: list[str]) -> list[int]:
    data = get_json(ctx, endpoints.genre_list(media, language=REFERENCE_LANGUAGE))
    table = {normalize_name(name): genre_id for genre_id, name in _genre_table(data).items()}
    return [_match(name, table, "genre") for name in wanted]


def _providers(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for p in data.get("results") or [] if isinstance(p, dict) and p.get("provider_id")]


def provider_ids(ctx: TmdbContext, media: MediaType, region: str, wanted: list[str]) -> list[int]:
    data = get_json(ctx, endpoints.watch_provider_list(media, region=region, language=REFERENCE_LANGUAGE))
    table = {normalize_name(p.get("provider_name")): p["provider_id"] for p in _providers(data)}
    return [_match(name, table, "provider") for name in wanted]


def genres_operation(ctx: TmdbContext, request: TmdbRequest) -> RequestOutcome:
    data = get_json(ctx, endpoints.genre_list(request.media, language=ctx.api_language))
    rows = [{"id": genre_id, "name": name} for genre_id, name in _genre_table(data).items()]
    return RequestOutcome(operation=request.operation.value, reference=rows, reference_total=len(rows))


def providers_catalog_operation(ctx: TmdbContext, request: TmdbRequest) -> RequestOutcome:
    region = request.region or DEFAULT_REGION
    data = get_json(ctx, endpoints.watch_provider_list(request.media, region=region, language=REFERENCE_LANGUAGE))
    providers = _providers(data)
    providers.sort(key=lambda p: (p.get("display_priorities") or {}).get(region, p.get("display_priority", 999)))
    rows = [{"id": p["provider_id"], "name": clean_text(p.get("provider_name"))} for p in providers]
    return RequestOutcome(
        operation=request.operation.value,
        reference=rows[: ctx.limit(request.limit)],
        reference_total=len(rows),
        notes=[f"region:{region}"],
        attribution=JUSTWATCH,
    )


def certifications_operation(ctx: TmdbContext, request: TmdbRequest) -> RequestOutcome:
    region = request.region or DEFAULT_REGION
    data = get_json(ctx, endpoints.certification_list(request.media))
    items = ((data.get("certifications") or {}).get(region)) or []
    items = sorted((i for i in items if isinstance(i, dict)), key=lambda i: i.get("order", 0))
    rows = [
        {"certification": clean_text(i.get("certification")), "meaning": truncate(clean_text(i.get("meaning")), MEANING_CHARS)}
        for i in items
    ]
    outcome = RequestOutcome(operation=request.operation.value, reference=rows, reference_total=len(rows))
    outcome.notes.append(f"region:{region}" if rows else f"no_certifications_for_region:{region}")
    return outcome
