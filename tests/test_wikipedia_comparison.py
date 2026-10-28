"""A film compared with the work it comes from needs both pages. The rule says so (text); the loop makes it
possible without any change to the orchestrator: two `wikipedia_search` steps, the second page read before the
answer, nothing read twice, and a turn where the planner stops after one page is untouched."""
from __future__ import annotations

import json

import pytest
from stream_support import reply
from wikipedia_support import by_mode, make_tool

import app as app_module
from orchestrator import LLMOrchestrator
from turn import TOOL_PARAM_TURN_ID

INSTRUCTIONS = app_module.CONFIG["orchestrator"]["instructions"]
RULE = INSTRUCTIONS[INSTRUCTIONS.index("1c) ") : INSTRUCTIONS.index("2) movie_db_search")]

FILM_TEXT = "Blade Runner is a 1982 film.\n\n== Plot ==\nDeckard hunts replicants.\n\n== Pre-production ==\nThe script dropped religion."
NOVEL_TEXT = "Do Androids Dream of Electric Sheep? is a 1968 novel.\n\n== Plot ==\nDeckard owns an electric sheep.\n\n== Themes ==\nEmpathy and religion (Mercerism)."


def _rows(lead: str, title: str, index: int):
    return {"pageid": index, "ns": 0, "title": title, "index": 1, "extract": lead}


def _handler(language, params):
    """Answers the search and the article of either work, by the title or the phrase asked."""
    asked = params.get("gsrsearch") or params.get("titles") or ""
    film = "blade runner" in asked.lower()
    title, text = ("Blade Runner", FILM_TEXT) if film else ("Do Androids Dream of Electric Sheep?", NOVEL_TEXT)
    if "gsrsearch" in params:
        return {"query": {"pages": [_rows(text.split("\n")[0], title, 1)]}}
    return {"query": {"pages": [_rows(text, title, 0)]}}


class _Client:
    def __init__(self, texts):
        self.texts, self.calls, self.responses = list(texts), [], self


    def create(self, **kwargs):
        self.calls.append(kwargs)
        return reply(self.texts.pop(0), kwargs)


def _plan(topic: str, *, kind: str, more: bool, parts=None, **extra) -> str:
    return json.dumps(
        {
            "standalone_query": "differenze tra il film e il romanzo",
            "tool_name": "wikipedia_search",
            "confidence": 0.95,
            "more_steps": more,
            "parts": parts or [],
            "arguments": {"topic": topic, "kind": kind, "depth": "full", **extra},
        }
    )


PARTS = [{"part": "il film", "tool": "wikipedia_search"}, {"part": "il romanzo d'origine", "tool": "wikipedia_search"}]


def _turn(texts):
    tool, transport = make_tool(_handler, default_language="en")
    client = _Client(texts)
    orch = LLMOrchestrator(config=app_module.build_runtime_config(), tools=[tool], client=client)
    return orch, transport, client


# --- the rule ------------------------------------------------------------------------------------------------


def test_the_rule_asks_for_both_sources_and_a_second_step_for_a_comparison() -> None:
    for phrase in (
        "Confronto tra un film e il romanzo o l'opera da cui deriva: servono entrambe le fonti",
        "Elenca in parts due voci wikipedia_search (la pagina del film e la pagina dell'opera d'origine",
        "ognuna con il proprio titolo inglese se noto",
        "imposta more_steps true nel primo passo e leggi la seconda pagina prima di rispondere",
        "se una delle due pagine è già stata letta in questo turno e basta, non rileggerla e cerca solo l'altra",
        "Una pagina letta di una sola opera non basta per confrontare",
        "ciò che riguarda l'altra va dichiarato non supportato",
    ):
        assert phrase in RULE


def test_the_two_sources_are_asked_only_for_comparisons_and_the_other_rules_are_untouched() -> None:
    assert RULE.count("servono entrambe le fonti") == 1
    assert "Regia, cast, durata, uscita, sinossi breve" in RULE  # simple structured questions still stay with TMDb
    assert "wikipedia" not in INSTRUCTIONS[INSTRUCTIONS.index("1) tmdb_search") : INSTRUCTIONS.index("1b) ")].lower()


# --- the loop makes it possible --------------------------------------------------------------------------------


def test_a_comparison_reads_the_film_then_the_novel_and_answers_after_both() -> None:
    orch, transport, client = _turn(
        [
            _plan("Blade Runner", kind="film", more=True, parts=PARTS, year=1982),
            _plan("Do Androids Dream of Electric Sheep?", kind="topic", more=False),
            "Confronto.",
        ]
    )

    decision = orch.run(query="differenze tra Blade Runner e il romanzo", conversation_history=[])

    assert decision["tools"] == ["wikipedia_search", "wikipedia_search"]
    read = [c["result"]["metadata"]["wikipedia"]["pages"][0]["title"] for c in decision["calls"]]
    assert read == ["Blade Runner", "Do Androids Dream of Electric Sheep?"]
    assert len(client.calls) == 3  # first plan, second plan, the answer: nothing else
    final_prompt = client.calls[-1]["input"][-1]["content"]
    assert "Deckard hunts replicants" in final_prompt and "electric sheep" in final_prompt  # both sides reach the answer
    assert decision["planning"]["fallbacks"] == [] and decision["planning"]["stop_reason"] == "complete"


def test_a_source_already_read_in_the_turn_is_not_downloaded_again() -> None:
    orch, transport, _ = _turn(
        [
            _plan("Blade Runner", kind="film", more=True, parts=PARTS),
            _plan("Blade Runner", kind="film", more=True, page="Blade Runner", language="en", sections=["Plot"]),
            _plan("Do Androids Dream of Electric Sheep?", kind="topic", more=False),
            "ok",
        ]
    )

    decision = orch.run(query="differenze tra Blade Runner e il romanzo", conversation_history=[])

    searches = [c[1].get("gsrsearch") for c in transport.calls if "gsrsearch" in c[1]]
    titles = [c[1]["titles"] for c in transport.calls if "titles" in c[1]]
    assert len(decision["calls"]) == 3
    assert searches.count('"Blade Runner" film') == 1 and titles.count("Blade Runner") == 1  # the film: one search, one article
    assert len(transport.calls) == 4  # film search + article, novel search + article


def test_a_turn_that_stops_after_one_page_is_left_alone() -> None:
    orch, transport, client = _turn([_plan("Blade Runner", kind="film", more=False), "ok"])

    decision = orch.run(query="differenze tra Blade Runner e il romanzo", conversation_history=[])

    assert decision["tools"] == ["wikipedia_search"] and len(transport.calls) == 2 and len(client.calls) == 2


def test_the_second_page_is_a_separate_search_of_the_work_not_a_section_of_the_film() -> None:
    orch, transport, _ = _turn(
        [_plan("Blade Runner", kind="film", more=True, parts=PARTS), _plan("Do Androids Dream of Electric Sheep?", kind="topic", more=False), "ok"]
    )

    orch.run(query="differenze tra Blade Runner e il romanzo", conversation_history=[])

    searches = [c[1]["gsrsearch"] for c in transport.calls if "gsrsearch" in c[1]]
    assert searches == ['"Blade Runner" film', '"Do Androids Dream of Electric Sheep?"']


def test_both_runs_share_the_turn_budget() -> None:
    orch, transport, _ = _turn(
        [_plan("Blade Runner", kind="film", more=True, parts=PARTS), _plan("Do Androids Dream of Electric Sheep?", kind="topic", more=False), "ok"]
    )

    decision = orch.run(query="differenze", conversation_history=[])

    ids = {c["result"]["trace"][0]["data"]["calls"][0]["url"].split("?")[0] for c in decision["calls"]}
    assert ids == {"https://en.wikipedia.org/w/api.php"}  # one host, and the HTTP count of the turn is the sum of both
    assert len(transport.calls) == 4
