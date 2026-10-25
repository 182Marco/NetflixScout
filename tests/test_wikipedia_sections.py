from __future__ import annotations

import pytest

from tool.wikipedia.models import Section
from tool.wikipedia.sections import (
    count_term,
    is_distinctive,
    cut_at_sentence,
    is_prose,
    keyword_report,
    outline,
    query_terms,
    question_terms,
    score,
    scoring_terms,
    select_sections,
    split_sections,
)

ARTICLE = """Park Chan-wook è un regista sudcoreano. Ha diretto Oldboy.

== Biografia ==
Nato a Seul nel 1963, studiò filosofia all'università Sogang.

=== Infanzia ===
Crebbe in una famiglia borghese.

== Carriera ==
Esordì nel 1992 con The Moon Is... the Sun's Dream. Il successo arrivò con Joint Security Area.

== Filmografia ==
Elenco dei film diretti.

== Note ==
Nota 1.

== Collegamenti esterni ==
Sito ufficiale.
"""


def _sections():
    return split_sections(ARTICLE, "it")


def _titles(selection):
    return [d.section.title for d in selection.delivered]


def test_split_sections_keeps_the_lead_and_every_heading_with_its_level() -> None:
    sections = _sections()

    assert [(s.title, s.level) for s in sections] == [
        ("Introduzione", 1),
        ("Biografia", 2),
        ("Infanzia", 3),
        ("Carriera", 2),
        ("Filmografia", 2),
        ("Note", 2),
        ("Collegamenti esterni", 2),
    ]
    assert sections[0].text.startswith("Park Chan-wook è un regista") and "== " not in sections[0].text
    assert sections[1].text == "Nato a Seul nel 1963, studiò filosofia all'università Sogang."


def test_an_article_without_headings_is_one_lead_in_the_language_of_the_edition() -> None:
    assert [(s.title, s.chars) for s in split_sections("Solo testo.", "it")] == [("Introduzione", 11)]
    assert split_sections("Only text.", "en")[0].title == "Introduction"
    assert split_sections("  \n ", "en") == []


def test_repeated_headings_stay_selectable_by_name() -> None:
    sections = split_sections("Lead.\n\n== Cast ==\nA\n\n== Cast ==\nB\n", "en")

    assert [s.title for s in sections] == ["Introduction", "Cast", "Cast (2)"]


def test_headings_without_text_are_dropped() -> None:
    assert [s.title for s in split_sections("Lead.\n\n== Vuota ==\n\n== Piena ==\nTesto\n", "it")] == ["Introduzione", "Piena"]


def test_lists_notes_and_links_are_not_prose() -> None:
    prose = {s.title for s in _sections() if is_prose(s, "it")}

    assert prose == {"Introduzione", "Biografia", "Infanzia", "Carriera", "Filmografia"}


def test_query_terms_drop_function_words_and_repeats() -> None:
    assert query_terms("Parlami della vita e della carriera di Park Chan-wook", "Park Chan-wook") == [
        "vita", "carriera", "park", "chan", "wook",
    ]


def test_the_words_of_the_topic_do_not_count_as_words_of_the_question() -> None:
    assert question_terms("Come è iniziata la carriera di Park Chan-wook", "Park Chan-wook") == ["iniziata", "carriera"]
    assert question_terms("Park Chan-wook", "Park Chan-wook") == []


def test_score_weights_titles_above_text_and_caps_repeats() -> None:
    carriera = Section(title="Carriera", level=2, text="x")
    other = Section(title="Altro", level=2, text="carriera " * 10)

    assert score(carriera, ["carriera"]) == 3
    assert score(other, ["carriera"]) == 3  # capped at three hits in the text
    assert score(other, ["assente"]) == 0


def _select(depth, *, wanted=(), terms=(), already=(), budget=10_000):
    return select_sections(
        _sections(), depth=depth, wanted=list(wanted), terms=list(terms), already=set(already), budget=budget, language="it"
    )


def test_intro_delivers_only_the_lead() -> None:
    selection = _select("intro")

    assert _titles(selection) == ["Introduzione"]
    assert [s.title for s in selection.omitted] == ["Biografia", "Infanzia", "Carriera", "Filmografia"]
    assert not selection.budget_hit


def test_sections_delivers_what_matches_the_question_in_article_order() -> None:
    selection = _select("sections", terms=["carriera", "joint"])

    assert _titles(selection) == ["Carriera"]


def test_sections_without_a_match_falls_back_to_the_lead() -> None:
    assert _titles(_select("sections", terms=["inesistente"])) == ["Introduzione"]


def test_full_delivers_every_prose_section_in_article_order() -> None:
    selection = _select("full", terms=["carriera"])

    assert _titles(selection) == ["Introduzione", "Biografia", "Infanzia", "Carriera", "Filmografia"]
    assert selection.omitted == ()


def test_named_sections_are_delivered_even_if_they_are_not_prose_and_unknown_ones_are_reported() -> None:
    selection = _select("sections", wanted=["note", "Premi"])

    assert _titles(selection) == ["Note"] and selection.unknown == ("Premi",)


def test_sections_already_delivered_in_the_turn_are_not_sent_again() -> None:
    selection = _select("full", already={"introduzione", "biografia"})

    assert _titles(selection) == ["Infanzia", "Carriera", "Filmografia"]
    assert "Biografia" not in [s.title for s in selection.omitted]


def test_the_budget_stops_the_delivery_and_the_rest_is_reported() -> None:
    sections = _sections()
    budget = sections[0].chars + sections[1].chars  # lead and Biografia, nothing more

    selection = _select("full", budget=budget)

    assert _titles(selection) == ["Introduzione", "Biografia"]
    assert selection.budget_hit
    assert [s.title for s in selection.omitted] == ["Infanzia", "Carriera", "Filmografia"]


def test_a_first_section_too_big_for_the_budget_is_cut_at_a_sentence_not_skipped() -> None:
    long_text = "Prima frase. " + "Seconda frase molto lunga. " * 100
    sections = [Section(title="Introduzione", level=1, text=long_text)]

    selection = select_sections(sections, depth="intro", wanted=[], terms=[], already=set(), budget=800, language="it")

    (delivered,) = selection.delivered
    assert delivered.truncated and len(delivered.text) <= 800 and delivered.text.endswith(".")
    assert [s.title for s in selection.omitted] == ["Introduzione"]  # it still has text to give
    assert selection.budget_hit


def test_with_too_little_room_nothing_is_cut() -> None:
    sections = [Section(title="Introduzione", level=1, text="x" * 2000)]

    selection = select_sections(sections, depth="intro", wanted=[], terms=[], already=set(), budget=300, language="it")

    assert selection.delivered == () and selection.budget_hit


def test_cut_at_sentence() -> None:
    assert cut_at_sentence("Una. Due. Tre.", 100) == "Una. Due. Tre."
    assert cut_at_sentence("Una frase. Due frasi. Tre", 22) == "Una frase. Due frasi."
    assert cut_at_sentence("senzapunti" * 10, 20) == "senzapuntisenzapunti"


def test_outline_lists_prose_sections_with_their_state() -> None:
    rows = outline(_sections(), {"introduzione"}, "it")

    assert [(r["title"], r["delivered"]) for r in rows] == [
        ("Introduzione", True), ("Biografia", False), ("Infanzia", False), ("Carriera", False), ("Filmografia", False),
    ]
    assert rows[1]["chars"] == len(_sections()[1].text)


@pytest.mark.parametrize("depth", ["intro", "sections", "full"])
def test_selection_is_deterministic(depth) -> None:
    assert _select(depth, terms=["carriera"]) == _select(depth, terms=["carriera"])


# --- keywords: matching, ranking and the report -------------------------------------------------

EN_ARTICLE = """Park Chan-wook is a South Korean film director.

== Early life ==
Born in Seoul in 1963, he studied philosophy at Sogang University.

== Career ==
He debuted in 1992. His breakthrough was Joint Security Area, which he directed in 2000.

== Filmography ==
List of films directed.
"""


def _en():
    return split_sections(EN_ARTICLE, "en")


def test_count_term_matches_whole_words_prefixes_from_four_letters_and_phrases() -> None:
    assert count_term("he directed films and directs", "direct") == 2
    assert count_term("he directed", "dir") == 0  # too short for a prefix
    assert count_term("he dir the film", "dir") == 1
    assert count_term("military service in seoul", "military service") == 1
    assert count_term("a military and service", "military service") == 0
    assert count_term("anything", "") == 0


def test_scoring_terms_put_the_planners_keywords_first_and_skip_the_topic() -> None:
    terms = scoring_terms(["Early Life", "birth"], "Dove è nato Park Chan-wook?", "Park Chan-wook")

    assert terms == ["early life", "birth", "dove", "nato"]


def test_english_keywords_pick_the_right_section_for_an_italian_question() -> None:
    sections = _en()

    without = select_sections(sections, depth="sections", wanted=[], terms=question_terms("Quando ha esordito?", "Park Chan-wook"),
                              already=set(), budget=10_000, language="en")
    with_keywords = select_sections(sections, depth="sections", wanted=[], terms=scoring_terms(["debut", "breakthrough"], "Quando ha esordito?", "Park Chan-wook"),
                                    already=set(), budget=10_000, language="en")

    assert [d.section.title for d in without.delivered] == ["Introduction"]  # nothing matches: the lead
    assert [d.section.title for d in with_keywords.delivered] == ["Career"]


def test_keyword_report_tells_read_unread_and_absent() -> None:
    rows = keyword_report(["philosophy", "military service", "Joint Security", "dubbing"], _en(), {"early life"}, whole_article=True)

    assert {r["keyword"]: (r["status"], r["sections"]) for r in rows} == {
        "philosophy": ("read", []),
        "military service": ("absent", []),
        "Joint Security": ("unread", ["Career"]),
        "dubbing": ("absent", []),
    }


def test_with_only_the_lead_known_nothing_is_called_absent() -> None:
    lead = [Section(title="Introduction", level=1, text="Park Chan-wook is a South Korean film director.")]

    rows = keyword_report(["Seoul", "birthplace"], lead, {"introduction"}, whole_article=False)

    assert [(r["keyword"], r["status"]) for r in rows] == [("Seoul", "not_in_lead"), ("birthplace", "not_in_lead")]
    lead = [Section(title="Introduction", level=1, text="Park Chan-wook is a South Korean film director born in Seoul.")]
    assert [r["status"] for r in keyword_report(["Seoul"], lead, {"introduction"}, whole_article=False)] == ["read"]


def test_a_keyword_found_only_in_a_section_not_delivered_lists_at_most_three() -> None:
    sections = [Section(title=f"Part {i}", level=2, text="oscar night") for i in range(5)]

    (row,) = keyword_report(["oscar"], sections, set(), whole_article=True)

    assert row["status"] == "unread" and row["sections"] == ["Part 0", "Part 1", "Part 2"]


# --- distinctive keywords and inflections ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("keyword", "expected"),
    [
        ("episodes", False), ("segments", False), ("actors", False), ("release order", False), ("cast", False),
        ("three stories", False), ("main characters", False), ("episodi", False), ("registi", False),
        ("Joint Security Area", True), ("Hoichi", True), ("military service", True), ("1992", True),
        ("Sympathy for Mr. Vengeance", True), ("dubbing", True), ("", False),
        # words seen as false signs in the live runs
        ("protagonists", False), ("continuations", False), ("connected", False), ("original titles", False),
        ("film adaptation", False), ("literary sources", False), ("narrative changes", False), ("collegati", False),
        ("fonti letterarie", False), ("titolo originale", False), ("protagonisti", False), ("continuazioni", False),
        ("Andrej Tarkovskij", True),
    ],
)
def test_only_keywords_that_name_something_specific_are_distinctive(keyword, expected) -> None:
    assert is_distinctive(keyword) is expected


@pytest.mark.parametrize(
    ("text", "term", "count"),
    [
        ("the episode is short", "episodes", 1),
        ("two episodes aired", "episode", 1),
        ("he directed and directs", "directing", 2),
        ("military services were", "military service", 1),
        ("a glass of glasses", "glass", 2),
        ("class and classes", "cla", 0),
        ("class and classes", "class", 2),
        ("this is it", "its", 0),
    ],
)
def test_matching_tolerates_inflections_but_not_unrelated_words(text, term, count) -> None:
    assert count_term(text, term) == count


def test_generic_keywords_are_left_out_of_the_report_and_still_rank_sections() -> None:
    sections = _en()

    rows = keyword_report(["episodes", "actors", "Joint Security Area", "dubbing"], sections, {"career"}, whole_article=True)

    assert [(r["keyword"], r["status"]) for r in rows] == [("Joint Security Area", "read"), ("dubbing", "absent")]
    ranked = select_sections(sections, depth="sections", wanted=[], terms=scoring_terms(["career"], "q", "x"), already=set(),
                             budget=10_000, language="en")
    assert [d.section.title for d in ranked.delivered] == ["Career"]
