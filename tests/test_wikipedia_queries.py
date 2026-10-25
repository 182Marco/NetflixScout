from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from wikipedia.models import WikipediaToolInput
from wikipedia.queries import api_url, article_params, lookup_params, page_url, phrase, search_term


def _request(**fields) -> WikipediaToolInput:
    return WikipediaToolInput.model_validate({"query": "q", "topic": "Parasite", **fields})


def test_phrase_removes_operators_and_control_characters() -> None:
    assert phrase('Park "Chan-wook"') == '"Park Chan-wook"'
    assert phrase('a\\b ~c* \x00d') == '"a b c d"'
    assert phrase('   ') is None
    assert phrase('""') is None


@pytest.mark.parametrize(
    ("fields", "term"),
    [
        ({"kind": "person", "topic": "Park Chan-wook"}, '"Park Chan-wook"'),
        ({"kind": "topic", "topic": "Nouvelle Vague"}, '"Nouvelle Vague"'),
        ({"kind": "film"}, '"Parasite" film'),
        ({"kind": "film", "year": 2019}, '"Parasite" film 2019'),
        ({"kind": "person", "year": 2019}, '"Parasite"'),
    ],
)
def test_search_term_adds_context_words_only_for_films(fields, term) -> None:
    assert search_term(_request(**fields)) == term


def test_a_topic_cannot_inject_search_operators() -> None:
    term = search_term(_request(kind="film", topic='x" OR intitle:"y -z~'))

    assert term is not None and term.count('"') == 2
    assert "~" not in term


def test_lookup_params_ask_for_leads_of_several_pages_in_one_request() -> None:
    params = lookup_params(_request(kind="film", year=2019), max_results=3)

    assert params["generator"] == "search" and params["gsrlimit"] == "6" and params["gsrnamespace"] == "0"
    assert params["gsrsearch"] == '"Parasite" film 2019'
    assert params["exintro"] == "1" and params["explaintext"] == "1" and params["exlimit"] == "max"
    assert params["redirects"] == "1" and params["maxlag"] == "5" and params["formatversion"] == "2"
    assert "exchars" not in params and "titles" not in params


def test_the_search_asks_for_more_pages_than_it_shows_within_a_ceiling() -> None:
    assert lookup_params(_request(), max_results=1)["gsrlimit"] == "2"
    assert lookup_params(_request(), max_results=5)["gsrlimit"] == "10"


def test_article_params_open_one_page_whole() -> None:
    params = article_params("Park Chan-wook")

    assert params["titles"] == "Park Chan-wook" and params["exsectionformat"] == "wiki"
    assert "exintro" not in params and "generator" not in params and "exchars" not in params


def test_urls_are_built_from_the_allowed_host_and_the_title() -> None:
    assert api_url("it") == "https://it.wikipedia.org/w/api.php"
    assert page_url("it", "Park Chan-wook") == "https://it.wikipedia.org/wiki/Park_Chan-wook"
    assert page_url("en", "Parasite (2019 film)") == "https://en.wikipedia.org/wiki/Parasite_(2019_film)"
    url = page_url("en", 'A/B?x=1#"<>')
    assert urlsplit(url).netloc == "en.wikipedia.org" and not parse_qs(urlsplit(url).query)
    assert "?" not in url[len("https://en.wikipedia.org/wiki/") :] and "#" not in url and '"' not in url
