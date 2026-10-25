"""The summary the planner reads: where to look next, never the text it already gave to the answer."""
from __future__ import annotations

from wikipedia.models import PageResult
from wikipedia.settings import PLANNER_SUMMARY_CHARS
from wikipedia.trace import build_planner_summary, build_wikipedia_trace

SECRET_TEXT = "Park Chan-wook was born in Seoul and studied philosophy."


def _page(**fields) -> PageResult:
    base = {
        "title": "Park Chan-wook", "language": "en", "verification": "confirmed", "total_chars": 18420, "delivered_chars": 5230,
        "sections": ["Introduction", "Career"],
        "outline": [{"title": "Introduction", "level": 1, "chars": 800, "delivered": True},
                    {"title": "Career", "level": 2, "chars": 4430, "delivered": True},
                    {"title": "Awards", "level": 2, "chars": 900, "delivered": False}],
        "omitted": [{"title": "Awards", "chars": 900}],
        "keywords": [{"keyword": "debut", "status": "read", "sections": []},
                     {"keyword": "awards", "status": "unread", "sections": ["Awards"]},
                     {"keyword": "dubbing", "status": "absent", "sections": []}],
        "text": [{"section": "Introduction", "text": SECRET_TEXT}],
    }
    return PageResult(**{**base, **fields})


def _summary(pages=None, reasons=("more_in_page", "keywords_absent"), **fields) -> str:
    base = {"edition": "en", "languages_tried": ["en"], "other_edition": "it", "context_used": 5230, "context_budget": 40000, "calls_left": 4}
    return build_planner_summary(pages or [_page()], list(reasons), **{**base, **fields})


def test_the_summary_names_the_edition_used_and_the_one_not_yet_asked() -> None:
    text = _summary()

    assert "edizione usata: en; consultate nel turno: en; edizione it non ancora consultata (si apre con language it)" in text
    assert "tutte le edizioni già consultate" in _summary(other_edition=None, languages_tried=["en", "it"])


def test_the_summary_lists_what_was_read_what_was_not_and_the_keywords() -> None:
    text = _summary()

    assert "[en] Park Chan-wook (confirmed): letti 5230/18420 caratteri." in text
    assert "Introduction* (800) · Career* (4430) · Awards (900)" in text and "Non lette: Awards (900)" in text
    assert "«debut» lette; «awards» non lette (in: Awards); «dubbing» assenti dall'articolo" in text


def test_the_summary_says_why_more_could_help() -> None:
    text = _summary()

    assert "Si può continuare:" in text and "altre sezioni" in text and "l'altra edizione potrebbe coprire il dettaglio" in text


def test_the_summary_never_repeats_the_text_already_given() -> None:
    assert SECRET_TEXT not in _summary() and "philosophy" not in _summary()


def test_a_lead_only_page_says_the_article_is_not_open_and_keywords_are_not_in_the_lead() -> None:
    lead = _page(total_chars=None, outline=None, omitted=[], keywords=[{"keyword": "debut", "status": "not_in_lead", "sections": []}])

    text = _summary([lead], reasons=("more_in_page",))

    assert "Lette solo le introduzioni" in text and "«debut» non nell'introduzione (articolo non ancora aperto)" in text


def test_the_summary_stays_within_its_limit() -> None:
    many = _page(omitted=[{"title": f"Section {i}", "chars": 100} for i in range(300)])

    assert len(_summary([many] * 5)) <= PLANNER_SUMMARY_CHARS


def test_the_trace_page_keeps_its_language_and_public_url() -> None:
    (step,) = build_wikipedia_trace(["https://en.wikipedia.org/w/api.php"], 0, [], [], [_page()])

    assert step["data"]["pages"][0]["language"] == "en"
    assert step["data"]["pages"][0]["url"] == "https://en.wikipedia.org/wiki/Park_Chan-wook"
