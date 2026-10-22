"""Shared shaping of list responses (search, find, discover, trending, charts)."""
from __future__ import annotations

from typing import Any

from ..context import TmdbContext
from ..models.requests import TmdbRequest
from ..models.results import RequestOutcome
from ..normalize.entities import list_item
from .reference import genre_names


def list_outcome(ctx: TmdbContext, request: TmdbRequest, data: dict[str, Any], *, kind: str) -> RequestOutcome:
    """Keep at most `max_results` items; genre names are fetched only if items carry genre IDs."""
    raws = [r for r in data.get("results") or [] if isinstance(r, dict)]
    outcome = RequestOutcome(operation=request.operation.value, total_results=data.get("total_results"))
    selected = raws[: ctx.limit(request.limit) * 2]  # some results (e.g. TV episodes) are skipped
    media_kinds = sorted({r.get("media_type") or kind for r in selected if r.get("genre_ids")} & {"movie", "tv"})
    genres = genre_names(ctx, media_kinds, outcome.skipped_for_budget) if media_kinds else {}
    items = (list_item(raw, kind=kind, genre_names=genres) for raw in selected)
    outcome.items = [item for item in items if item is not None][: ctx.limit(request.limit)]
    if outcome.total_results is None:
        outcome.total_results = len(raws)
    return outcome
