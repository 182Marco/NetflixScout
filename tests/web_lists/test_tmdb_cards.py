"""The `tmdb_calls` step carries the cards `web_lists` hydrates from."""
from __future__ import annotations

from tool.tmdb.models.results import Entity, RequestOutcome
from tool.tmdb.normalize.entities import list_item
from tool.tmdb.trace import build_tmdb_trace, tmdb_cards


def test_cards_cover_movies_and_series_once_in_order() -> None:
    raw = {"id": 1396, "name": "Breaking Bad", "first_air_date": "2008-01-20", "poster_path": "/p.jpg",
           "overview": "Chemistry.", "vote_average": 8.9, "vote_count": 10, "original_language": "en"}
    tv = list_item(raw, kind="tv", genre_names={})
    person = Entity(kind="person", tmdb_id=5, title="Someone")
    outcomes = [RequestOutcome(operation="search", items=[tv, person]), RequestOutcome(operation="x", entities=[tv])]
    (card,) = tmdb_cards(outcomes)
    assert card == {"id": 1396, "media_type": "tv", "title": "Breaking Bad", "original_title": None, "overview": "Chemistry.",
                    "vote_average": 8.9, "release_date": "2008-01-20", "original_language": "en",
                    "poster_path": "/p.jpg"}


def test_trace_keeps_calls_and_attributions_with_items() -> None:
    (step,) = build_tmdb_trace(["https://x?api_key=***"], ["justwatch"], [{"id": 1}])
    assert step["data"] == {"calls": ["https://x?api_key=***"], "attributions": ["justwatch"], "items": [{"id": 1}]}
