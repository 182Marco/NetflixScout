from __future__ import annotations

import pytest

from wikipedia.models import PageHit, WikipediaToolInput
from wikipedia.relevance import lookup_hints, match_title, screen_pages, strip_qualifier, verification


def _request(**fields) -> WikipediaToolInput:
    return WikipediaToolInput.model_validate({"query": "q", "topic": "Parasite", "kind": "film", **fields})


def _page(title: str, index: int = 0, *, extract: str = "Testo.", disambiguation: bool = False) -> PageHit:
    return PageHit(pageid=index + 1, title=title, language="en", index=index, extract=extract, disambiguation=disambiguation)


@pytest.mark.parametrize(
    ("topic", "title", "expected"),
    [
        ("Parasite", "Parasite", "exact"),
        ("parasite", "Parasite (2019 film)", "qualified"),
        ("The Dungeon of Harrow", "Dungeon of Harrow", "exact"),
        ("Bong Joon-ho", "Bong Joon-ho", "exact"),
        ("Parasite", "Parasite (film 1982)", "qualified"),
        ("Joon-ho", "Bong Joon-ho", "partial"),
        ("Parasite", "Bong Joon-ho", "differs"),
        ("Amélie", "Amelie", "exact"),
    ],
)
def test_match_title(topic, title, expected) -> None:
    assert match_title(topic, title) == expected


def test_strip_qualifier() -> None:
    assert strip_qualifier("Parasite (2019 film)") == ("Parasite", "2019 film")
    assert strip_qualifier("Parasite") == ("Parasite", None)


def test_disambiguation_pages_and_empty_extracts_are_dropped_and_counted() -> None:
    pages = [_page("Parasite (disambiguation)", 0, disambiguation=True), _page("Parasite", 1), _page("Empty", 2, extract="  ")]

    kept, dropped = screen_pages(_request(), pages)

    assert [row.page.title for row in kept] == ["Parasite"]
    assert dropped == {"disambiguation": 1, "empty_extract": 1}


def test_confirmed_pages_come_first_then_search_order_inside_each_group() -> None:
    pages = [_page("Bong Joon-ho", 0), _page("Parasite (2019 film)", 2), _page("Parasitism", 1), _page("Parasite", 3)]

    kept, _ = screen_pages(_request(), pages)

    assert [(row.page.title, row.verification) for row in kept] == [
        ("Parasite (2019 film)", "confirmed"),
        ("Parasite", "confirmed"),
        ("Bong Joon-ho", "to_verify"),
        ("Parasitism", "to_verify"),
    ]
    assert kept[2].notes == ["title_differs"]


def test_a_film_year_that_contradicts_the_title_qualifier_is_to_verify() -> None:
    kept, _ = screen_pages(_request(year=2019), [_page("Parasite (film 1982)")])

    assert kept[0].verification == "to_verify" and kept[0].notes == ["year_conflict"]
    kept, _ = screen_pages(_request(year=2019), [_page("Parasite (2019 film)")])
    assert kept[0].verification == "confirmed"


def test_the_year_is_ignored_for_people() -> None:
    kept, _ = screen_pages(_request(kind="person", topic="Parasite", year=2019), [_page("Parasite (film 1982)")])

    assert kept[0].verification == "confirmed"


def test_verification_label() -> None:
    assert verification([]) == "confirmed"
    assert verification(["title_partial"]) == "to_verify"


def test_hints_suggest_a_year_only_when_it_would_help() -> None:
    request = _request()
    two, dropped = screen_pages(request, [_page("Parasite (2019 film)", 0), _page("Parasite (film 1982)", 1)])
    one, none = screen_pages(request, [_page("Parasite (2019 film)", 0)])

    assert lookup_hints(request, two, dropped) == ["specify_year"]
    assert lookup_hints(request, one, none) == []
    assert lookup_hints(_request(year=2019), two, dropped) == []
    assert lookup_hints(_request(kind="person"), two, dropped) == []


def test_only_disambiguation_results_suggest_adding_context() -> None:
    request = _request(kind="person", topic="John Smith")
    kept, dropped = screen_pages(request, [_page("John Smith", 0, disambiguation=True)])

    assert kept == [] and lookup_hints(request, kept, dropped) == ["add_context"]
