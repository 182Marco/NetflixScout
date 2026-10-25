"""A long first page must not leave the second source of a comparison with a sliver, and a page already
read in the turn must not be opened again in place of the work asked now. Sizes are those of the live
run of 2026-10-25 (Blade Runner 49,328 characters, its novel 14,501); all offline."""
from __future__ import annotations

from wikipedia_support import lookup_answer, make_tool, page

from turn import TOOL_PARAM_TURN_ID

TURN = {TOOL_PARAM_TURN_ID: "turn-1"}


def _article(title: str, sections: int, size: int) -> str:
    body = [f"{title} lead."]
    for number in range(sections):
        body.append(f"== Section {number} ==\n" + (f"{title} text {number}. " * (size // 20))[:size])
    return "\n\n".join(body)


FILM = _article("Blade Runner", 20, 2_500)
NOVEL = _article("Do Androids Dream of Electric Sheep?", 7, 2_000)


def _handler(pages: dict[str, str], titles_found: dict[str, list[str]]):
    """Search answers the titles listed for the phrase; an article answers by exact title."""

    def handler(language, params):
        if "gsrsearch" in params:
            asked = params["gsrsearch"].lower()
            found = next((titles for key, titles in titles_found.items() if key in asked), [])
            return lookup_answer(*[page(t, pages[t].split("\n")[0], index=i + 1) for i, t in enumerate(found)])
        title = params["titles"]
        return lookup_answer(page(title, pages[title], index=0)) if title in pages else {"query": {"pages": []}}

    return handler


def _meta(result):
    return result["metadata"]["wikipedia"]


def _tool(pages, found, **kwargs):
    return make_tool(_handler(pages, found), default_language="en", **kwargs)


def _run(tool, **arguments):
    return tool.run(query="differenze", params={**TURN, "depth": "full", **arguments}, conversation_history=[])


def test_a_long_first_page_leaves_room_for_the_second_source() -> None:
    tool, transport = _tool(
        {"Blade Runner": FILM, "Do Androids Dream of Electric Sheep?": NOVEL},
        {"blade runner": ["Blade Runner"], "do androids": ["Do Androids Dream of Electric Sheep?"]},
    )
    first = _run(tool, topic="Blade Runner", kind="film")
    second = _run(tool, topic="Do Androids Dream of Electric Sheep?", kind="topic")

    film, novel = _meta(first)["pages"][0], _meta(second)["pages"][0]
    assert film["delivered_chars"] <= 24_000 < film["total_chars"]
    assert novel["delivered_chars"] >= 13_000 and not novel["truncated"] and novel["omitted"] == []
    assert _meta(second)["context"]["used"] <= 40_000
    # What the share left out is not "out of budget": it can be asked for.
    assert "omitted_by_budget" not in first["follow_up"]["reasons"]
    assert "more_in_page" in first["follow_up"]["reasons"]


def test_both_sources_fit_and_the_comparison_is_whole() -> None:
    small_film, small_novel = _article("Film", 4, 1_500), _article("Novel", 4, 1_500)
    tool, transport = _tool({"Film": small_film, "Novel": small_novel}, {"film": ["Film"], "novel": ["Novel"]})
    first = _run(tool, topic="Film", kind="film")
    second = _run(tool, topic="Novel", kind="topic")

    assert [p["truncated"] for r in (first, second) for p in _meta(r)["pages"]] == [False, False]
    assert _meta(first)["pages"][0]["omitted"] == [] and _meta(second)["pages"][0]["omitted"] == []
    assert len(transport.calls) == 4


def test_a_page_of_the_share_or_less_is_delivered_whole_as_before() -> None:
    text = _article("Film", 9, 2_500)  # about 22,500 characters
    tool, _ = _tool({"Film": text}, {"film": ["Film"]})
    page_meta = _meta(_run(tool, topic="Film", kind="film"))["pages"][0]
    assert page_meta["delivered_chars"] == page_meta["total_chars"] and page_meta["omitted"] == []


def test_sections_asked_by_name_are_not_held_to_the_share() -> None:
    names = [f"Section {n}" for n in range(10)]  # 10 x 2,500 = 25,000 > the share
    tool, _ = _tool({"Blade Runner": FILM}, {"blade runner": ["Blade Runner"]})
    result = _run(tool, topic="Blade Runner", kind="film", page="Blade Runner", sections=names)
    assert _meta(result)["pages"][0]["delivered_chars"] > 24_000


def test_the_intro_is_not_changed() -> None:
    tool, _ = _tool({"Blade Runner": FILM}, {"blade runner": ["Blade Runner"]})
    result = tool.run(query="q", params={**TURN, "topic": "Blade Runner", "kind": "film", "depth": "intro"}, conversation_history=[])
    assert _meta(result)["pages"][0]["sections_delivered"] == ["Introduction"]


def test_when_the_turn_runs_out_before_the_share_it_is_still_reported_as_budget() -> None:
    tool, _ = _tool({"Blade Runner": FILM}, {"blade runner": ["Blade Runner"]}, context_chars=4_000)
    result = _run(tool, topic="Blade Runner", kind="film")
    assert "omitted_by_budget" in result["follow_up"]["reasons"]


# --- which page is opened ---------------------------------------------------------------------------------


def _pair():
    pages = {"The Shining (film)": _article("Shining film", 4, 2_000), "The Shining (novel)": _article("Shining novel", 4, 2_000)}
    return _tool(pages, {"the shining": ["The Shining (film)", "The Shining (novel)"]})


def test_the_work_asked_now_is_opened_when_the_film_page_was_already_read() -> None:
    tool, transport = _pair()
    first = _run(tool, topic="The Shining", kind="film", year=1980)
    second = _run(tool, topic="The Shining", kind="topic")

    assert _meta(first)["pages"][0]["title"] == "The Shining (film)"
    assert _meta(second)["pages"][0]["title"] == "The Shining (novel)"
    assert "already_delivered" not in _meta(second)["pages"][0]["notes"]


def test_the_same_request_reuses_the_page_without_a_download_and_says_nothing_new_came() -> None:
    tool, transport = _pair()
    _run(tool, topic="The Shining", kind="film", year=1980)
    downloads = [c for c in transport.calls if "titles" in c[1]]
    again = _run(tool, topic="The Shining", kind="film", year=1980)

    page_meta = _meta(again)["pages"][0]
    assert page_meta["title"] == "The Shining (film)" and page_meta["delivered_chars"] == 0
    assert "already_delivered" in page_meta["notes"]
    assert [c for c in transport.calls if "titles" in c[1]] == downloads


def test_when_only_the_page_already_read_is_confirmed_it_is_reused_and_flagged() -> None:
    pages = {"The Shining (film)": _article("Shining film", 4, 2_000)}
    tool, transport = _tool(pages, {"the shining": ["The Shining (film)"]})
    _run(tool, topic="The Shining", kind="film", year=1980)
    second = _run(tool, topic="The Shining", kind="topic")

    assert _meta(second)["pages"][0]["title"] == "The Shining (film)"
    assert "already_delivered" in _meta(second)["pages"][0]["notes"]
    assert len([c for c in transport.calls if "titles" in c[1]]) == 1


def test_a_single_source_turn_opens_the_first_confirmed_page_as_before() -> None:
    tool, _ = _pair()
    assert _meta(_run(tool, topic="The Shining", kind="film"))["pages"][0]["title"] == "The Shining (film)"


# --- the plot of a page asked for differences -------------------------------------------------------------


def test_a_question_about_an_adaptation_reads_the_plot_first() -> None:
    from tool.wikipedia.models import Section
    from tool.wikipedia.sections import select_sections

    sections = [Section(title="Intro", level=1, text="Blade Runner " * 50)] + [
        Section(title=f"Production {n}", level=2, text="Blade Runner Dick " * 100) for n in range(5)
    ] + [Section(title="Plot", level=2, text="Deckard hunts. " * 100)]
    terms = ["blade runner", "dick", "adaptation"]
    chosen = select_sections(sections, depth="full", wanted=[], terms=terms, already=set(), budget=2_500, language="en")
    assert "Plot" in [d.section.title for d in chosen.delivered]
    plain = select_sections(sections, depth="full", wanted=[], terms=["blade runner", "dick"], already=set(), budget=2_500, language="en")
    assert "Plot" not in [d.section.title for d in plain.delivered]
