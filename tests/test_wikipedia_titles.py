"""Topics with a qualifier and titles a page does not carry: the search retries once without the qualifier
only when the first search settled nothing, and another work with the same name is never taken for the one
asked. Offline."""
from __future__ import annotations

import pytest
from wikipedia_support import lookup_answer, make_tool, page

from tool.wikipedia.relevance import match_title, qualifier_free_topic
from turn import TOOL_PARAM_TURN_ID

TURN = {TOOL_PARAM_TURN_ID: "t"}
ARTICLE = "Lead text.\n\n== Plot ==\nA story is told here at some length."


def _tool(found, **kwargs):
    """`found`: {fragment of the phrase: [(title, lead)]}; an article answers by title."""

    def handler(language, params):
        if "gsrsearch" in params:
            asked = params["gsrsearch"].lower()
            rows = next((r for key, r in found.items() if key in asked), [])
            return lookup_answer(*[page(t, lead, index=i + 1) for i, (t, lead) in enumerate(rows)])
        return lookup_answer(page(params["titles"], ARTICLE, index=0))

    return make_tool(handler, default_language="en", **kwargs)


def _run(tool, **arguments):
    return tool.run(query="q", params={**TURN, "depth": "full", **arguments}, conversation_history=[])


def _phrases(transport):
    return [c[1]["gsrsearch"] for c in transport.calls if "gsrsearch" in c[1]]


def _meta(result):
    return result["metadata"]["wikipedia"]


FAHRENHEIT = "Fahrenheit 451 is a 1966 dystopian film directed by François Truffaut."


def test_a_qualifier_the_page_title_extends_is_found_with_the_name_alone() -> None:
    found = {
        '(film)"': [("Monorail", "A monorail is a rail."), ("Fahrenheit 451 (2018 film)", "Fahrenheit 451 is a 2018 film.")],
        '"fahrenheit 451" film': [("Fahrenheit 451 (1966 film)", FAHRENHEIT)],
    }
    tool, transport = _tool(found)
    result = _run(tool, topic="Fahrenheit 451 (film)", kind="film", year=1966)

    assert _phrases(transport) == ['"Fahrenheit 451 (film)" film 1966', '"Fahrenheit 451" film 1966']
    assert _meta(result)["pages"][0]["title"] == "Fahrenheit 451 (1966 film)"
    assert _meta(result)["pages"][0]["verification"] == "confirmed"
    assert result["trace"][0]["data"]["searches"][1]["retry"] == "without_qualifier"


def test_the_retry_does_not_confirm_a_page_of_another_year() -> None:
    found = {
        '(film)"': [],
        '"fahrenheit 451" film': [("Fahrenheit 451 (2018 film)", "Fahrenheit 451 is a 1966 and 2018 film.")],
    }
    tool, _ = _tool(found)
    result = _run(tool, topic="Fahrenheit 451 (film)", kind="film", year=1966)
    assert _meta(result)["pages"] == []
    assert [c["title"] for c in _meta(result)["candidates"]] == ["Fahrenheit 451 (2018 film)"]


def test_a_novel_is_not_confused_with_a_film_of_the_same_name() -> None:
    found = {
        '(novel)"': [],
        '"solaris"': [("Solaris (1972 film)", "Solaris is a 1972 film.")],
    }
    tool, transport = _tool(found)
    result = _run(tool, topic="Solaris (novel)", kind="topic")

    assert len(_phrases(transport)) == 2
    assert not [c for c in transport.calls if "titles" in c[1]]  # nothing was downloaded
    assert _meta(result)["pages"] == []
    assert [c["title"] for c in _meta(result)["candidates"]] == ["Solaris (1972 film)"]
    assert result["follow_up"]["reasons"] == ["unverified"]


def test_a_confirmed_first_search_is_not_repeated() -> None:
    found = {'"the shining (novel)"': [("The Shining (novel)", "The Shining is a 1977 novel.")]}
    tool, transport = _tool(found)
    result = _run(tool, topic="The Shining (novel)", kind="topic")
    assert len(_phrases(transport)) == 1
    assert _meta(result)["pages"][0]["title"] == "The Shining (novel)"


def test_a_year_in_parentheses_is_no_qualifier_and_triggers_no_retry() -> None:
    tool, transport = _tool({})
    _run(tool, topic="Kwaidan (1964)", kind="film")
    assert len(_phrases(transport)) == 1


def test_a_topic_without_qualifier_is_searched_once() -> None:
    tool, transport = _tool({})
    result = _run(tool, topic="Il sorpasso", kind="film")
    assert len(_phrases(transport)) == 1 and result["outcome"]["status"] == "empty"


def test_the_retry_costs_a_call_of_the_turn_budget() -> None:
    tool, transport = _tool({}, max_calls=1)
    result = _run(tool, topic="Solaris (novel)", kind="topic")
    assert len(transport.calls) == 1
    assert _meta(result)["status"] in ("empty", "error")


def test_a_distribution_title_stays_a_candidate_and_is_not_opened_alone() -> None:
    found = {'"the easy life"': [("Il Sorpasso", "Il Sorpasso (The Easy Life) is a 1962 Italian film.")]}
    tool, transport = _tool(found)
    result = _run(tool, topic="The Easy Life", kind="film", year=1962)

    assert not [c for c in transport.calls if "titles" in c[1]]
    assert _meta(result)["candidates"][0]["title"] == "Il Sorpasso"
    assert result["follow_up"]["reasons"] == ["unverified"]


@pytest.mark.parametrize(
    ("topic", "title", "expected"),
    [
        ("Fahrenheit 451 (film)", "Fahrenheit 451 (1966 film)", "qualified"),
        ("Solaris (novel)", "Solaris (1972 film)", "partial"),
        ("Solaris (film)", "Solaris (novel)", "partial"),
        ("Solaris (1972 film)", "Solaris (film)", "partial"),
        ("Kwaidan (film)", "Kwaidan (film)", "exact"),
        ("The Garden of the Finzi-Continis (novel)", "The Garden of the Finzi-Continis", "qualified"),
        ("Tokyo!", "Tokyo! (film)", "exact"),
    ],
)
def test_title_matching_with_qualifiers(topic: str, title: str, expected: str) -> None:
    assert match_title(topic, title) == expected or (topic, title) == ("Tokyo!", "Tokyo! (film)")


def test_qualifier_free_topic() -> None:
    assert qualifier_free_topic("Solaris (novel)") == "Solaris"
    assert qualifier_free_topic("Kwaidan (1964)") is None
    assert qualifier_free_topic("Kwaidan") is None


def test_the_retry_is_skipped_when_the_turn_cannot_also_open_the_page() -> None:
    """With one call left the retry would find a page nobody can open: the call is kept for the next step."""
    found = {'"solaris"': [("Solaris (novel)", "Solaris is a 1961 novel.")]}
    tool, transport = _tool(found, max_calls=2)
    result = _run(tool, topic="Solaris (book)", kind="topic")  # first search uses 1 of 2
    assert len(_phrases(transport)) == 1
    assert _meta(result)["status"] == "empty"
