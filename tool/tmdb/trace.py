"""Trace of a TMDb run: the endpoints actually called and the sources to credit.

Kept outside `metadata` (which goes into the LLM prompt): attributions are shown to the
user by the presenters, never left to the model.
"""
from __future__ import annotations

from typing import Any

from turn import STEP_TMDB_CALLS

from .models.results import Entity, RequestOutcome

TMDB_CALLS_TITLE = "TMDb"
CARD_KINDS = ("movie", "tv")


def _card(entity: Entity) -> dict[str, Any]:
    """The fields a web card shows, as TMDb gave them (the title is the localized one)."""
    return {
        "id": entity.tmdb_id,
        "media_type": entity.kind,
        "title": entity.title,
        "original_title": entity.original_title,
        "overview": entity.essentials.get("overview") or entity.summary,
        "vote_average": entity.essentials.get("vote_average") or entity.score,
        "release_date": entity.release_date,
        "original_language": entity.original_language,
        "poster_path": entity.poster_path,
    }


def tmdb_cards(outcomes: list[RequestOutcome]) -> list[dict[str, Any]]:
    """Movies and series of the run, once each, in order: what a web list can point to."""
    cards: dict[str, dict[str, Any]] = {}
    for outcome in outcomes:
        for entity in [*outcome.entities, *outcome.items]:
            if entity.kind in CARD_KINDS:
                cards.setdefault(entity.key, _card(entity))
    return list(cards.values())


def build_tmdb_trace(
    calls: list[str],
    attributions: list[str],
    items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    return [
        {
            "kind": STEP_TMDB_CALLS,
            "title": TMDB_CALLS_TITLE,
            "data": {"calls": list(calls), "attributions": list(attributions), "items": list(items or [])},
        }
    ]
