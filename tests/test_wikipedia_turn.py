"""A whole turn with Wikipedia, offline, from the tool to the SSE events of the frontend.

The real `LLMOrchestrator` runs the real `WikipediaTool` (fake HTTP transport, `urlopen` blocked)
with a scripted LLM client; the real web_api serves the turn. Nothing here calls the network or
reads `.env`.
"""
from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

import pytest
from stream_support import reply
from web_api_support import names, parse_sse, streamed_text
from wikipedia_support import EN_ARTICLE_TEXT, by_mode, doc_step, lookup_answer, make_tool, page, article_answer

import app as app_module
from app import handle_query
from fastapi.testclient import TestClient
from orchestrator import LLMOrchestrator
from presenters import OutputChannel, present
from presenters.terminal import TerminalObserver
from presenters.web.payload import serialize_step
from web_api import create_app
from web_api.schemas.events import EVENT_MODELS
from web_api.settings import WebApiSettings

DOC = (Path(__file__).resolve().parents[1] / "web_api" / "FRONTEND_API.md").read_text(encoding="utf-8")
LEAD = "Park Chan-wook è un regista sudcoreano. Ha diretto Oldboy."
ANSWER = "Park Chan-wook esordì nel 1992; il successo arrivò con Joint Security Area."
FINAL = json.dumps({"answer": ANSWER, "lists": []})
URL = "https://it.wikipedia.org/wiki/Park_Chan-wook"


def _plan(**arguments) -> str:
    return json.dumps(
        {"standalone_query": "carriera di Park Chan-wook", "tool_name": "wikipedia_search", "arguments": arguments, "confidence": 0.9}
    )


# The planner reads the first result, asks for the career section, reads that and is done.
SCRIPT = [
    _plan(topic="Park Chan-wook", kind="person", depth="intro"),
    _plan(topic="Park Chan-wook", kind="person", depth="sections", page="Park Chan-wook", language="it", sections=["Carriera"]),
    '{"done": true}',
    FINAL,
]


class _Client:
    def __init__(self, texts: list[str]) -> None:
        self.texts = list(texts)
        self.calls: list[dict] = []
        self.responses = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return reply(self.texts.pop(0), kwargs)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(app_module, "classify_query_domain", lambda q, history=None: {"is_cinema": True, "is_italian": True})

    def no_network(*args, **kwargs):
        raise AssertionError("a test reached the network")

    monkeypatch.setattr(urllib.request, "urlopen", no_network)


def _bot(script=SCRIPT, *, handler=None, default_language="it"):
    handler = handler or by_mode(lookup=lookup_answer(page("Park Chan-wook", LEAD)), article=article_answer())
    tool, transport = make_tool(handler, default_language=default_language)
    client = _Client(script)
    orchestrator = LLMOrchestrator(config=app_module.build_runtime_config(), tools=[tool], client=client)
    return {"config": app_module.build_runtime_config(), "orchestrator": orchestrator}, transport, client


def _events(bot):
    with TestClient(create_app(WebApiSettings(), bot, client=object())) as client:  # type: ignore[arg-type]
        conversation = client.post("/conversations").json()["conversation_id"]
        response = client.post(f"/conversations/{conversation}/messages", json={"content": "parlami della carriera di Park Chan-wook"})
    assert response.status_code == 200
    return parse_sse(response.text)


def _steps(events):
    return [data for _, name, data in events if name == "step" and data["kind"] == "wikipedia_calls"]


def test_the_two_wikipedia_steps_reach_the_frontend_before_the_answer() -> None:
    bot, transport, _ = _bot()

    events = _events(bot)

    order = names(events)
    first_delta = order.index("answer_delta")
    positions = [i for i, (_, name, data) in enumerate(events) if name == "step" and data["kind"] == "wikipedia_calls"]
    assert len(positions) == 2 and max(positions) < first_delta
    assert order[0] == "turn_start" and order[-3:] == ["answer_end", "lists", "done"]
    assert streamed_text(events).strip() == ANSWER
    # The lookup and the article: two requests for the whole turn, none for the second step.
    assert [c[1].get("generator") is not None for c in transport.calls] == [True, False]


def test_the_first_step_carries_the_sources_and_the_credit() -> None:
    bot, _, _ = _bot()

    first, _ = _steps(_events(bot))

    assert first["title"] == "WIKIPEDIA — 1 pagina"
    assert first["source"] == "Fonte: Wikipedia, testo riformulato e abbreviato, licenza CC BY-SA 4.0"
    (shown,) = first["pages"]
    assert (shown["title"], shown["language"], shown["url"], shown["verification"]) == ("Park Chan-wook", "it", URL, "confirmed")
    assert shown["sections"] == ["Introduzione"]
    assert first["license"] == {"name": "CC BY-SA 4.0", "url": "https://creativecommons.org/licenses/by-sa/4.0/"}
    assert first["calls"] == ["https://it.wikipedia.org/w/api.php"] and first["reused"] == 0


def test_the_second_step_opens_the_article_and_reads_only_what_was_not_read() -> None:
    bot, _, _ = _bot()

    _, second = _steps(_events(bot))

    assert len(second["calls"]) == 1 and second["reused"] == 0  # the article is downloaded here
    assert second["opens"][0]["result"] == "letta"
    assert second["pages"][0]["sections"] == ["Carriera"] and second["pages"][0]["url"] == URL
    # The lead was read by the first step: only Biografia and Filmografia are left.
    assert second["pages"][0]["omitted"] == 2
    assert second["license"]["url"].startswith("https://creativecommons.org/")


def test_a_third_step_on_the_same_page_is_served_from_the_cache() -> None:
    third = _plan(topic="Park Chan-wook", kind="person", depth="sections", page="Park Chan-wook", language="it", sections=["Biografia"])
    bot, transport, _ = _bot([*SCRIPT[:2], third, '{"done": true}', FINAL])

    steps = _steps(_events(bot))

    assert len(steps) == 3 and len(transport.calls) == 2
    assert steps[2]["calls"] == [] and steps[2]["reused"] == 1
    assert steps[2]["pages"][0]["sections"] == ["Biografia"] and steps[2]["pages"][0]["omitted"] == 1
    assert steps[2]["labels"]["none"] == "Nessuna chiamata a Wikipedia in questo passo: dati già in cache."


def test_every_step_event_is_valid_for_the_documented_contract_and_json_clean() -> None:
    bot, _, _ = _bot()

    for step in _steps(_events(bot)):
        EVENT_MODELS["step"].model_validate(step)
        assert json.loads(json.dumps(step)) == step
        assert "api_key" not in json.dumps(step) and "marcomilza" not in json.dumps(step)


def test_wikipedia_text_and_urls_do_not_leak_into_the_events_or_lists() -> None:
    bot, _, _ = _bot()

    events = _events(bot)

    lists = next(data for _, name, data in events if name == "lists")
    assert lists == {"lists": []}
    for _, name, data in events:
        if name in ("story", "status", "answer_end"):
            assert "regista sudcoreano" not in json.dumps(data)


def test_the_planner_saw_what_was_read_and_what_was_left_out() -> None:
    bot, _, client = _bot()

    _events(bot)

    second_plan_prompt = client.calls[1]["input"][-1]["content"]
    assert "può dare altro (more_in_page)" in second_plan_prompt
    assert "Lette solo le introduzioni" in second_plan_prompt
    third_plan_prompt = client.calls[2]["input"][-1]["content"]
    assert "Carriera* (" in third_plan_prompt and "Non lette:" in third_plan_prompt
    final_prompt = client.calls[3]["input"][-1]["content"]
    assert "Joint Security Area" in final_prompt and "wikipedia.org" not in final_prompt


def test_the_story_tells_both_steps() -> None:
    bot, _, _ = _bot()

    stories = [data["text"] for _, name, data in _events(bot) if name == "story"]

    assert sum(text.startswith("Cerco su Wikipedia") for text in stories) == 2
    assert sum(text.startswith("Wikipedia: trovato") for text in stories) == 2


def test_the_terminal_shows_the_same_sources_as_the_web(capsys) -> None:
    bot, _, _ = _bot()
    turn = handle_query(bot, "parlami della carriera di Park Chan-wook", [], object(), observer=TerminalObserver())  # type: ignore[arg-type]
    present(turn, OutputChannel.terminal, streamed=True)
    out = capsys.readouterr().out
    web_steps = [serialize_step(step, turn.language) for step in turn.steps if step.kind == "wikipedia_calls"]

    assert len(web_steps) == 2
    for step in web_steps:
        assert step["pages"][0]["url"] in out and step["license"]["url"] in out
        assert step["pages"][0]["title"] in out and ", ".join(step["pages"][0]["sections"]) in out
    assert out.count("WIKIPEDIA — 1 PAGINA") == 2


def test_a_wikipedia_turn_without_follow_up_costs_one_planner_call() -> None:
    bot, transport, client = _bot([_plan(topic="Park Chan-wook", kind="person", depth="full"), FINAL])

    events = _events(bot)

    assert len(client.calls) == 2 and len(_steps(events)) == 1
    assert len(transport.calls) == 2  # search, then the whole article


def test_the_documented_example_is_what_the_serializer_produces() -> None:
    match = re.search(r"```json step=wikipedia_calls\n(.*?)\n```", DOC, re.S)

    assert match is not None
    assert json.loads(match.group(1)) == serialize_step(doc_step(), "it")


# --- English first, Italian only when the planner decides ------------------------------------------

TITLE_IT = "Il ragazzo e l'airone"
HERON_LEAD = "Il ragazzo e l'airone è un film d'animazione del 2023 diretto da Hayao Miyazaki."


def _heron(language, params):
    """English finds nothing for the Italian title; the Italian edition has the page."""
    return lookup_answer() if language == "en" else lookup_answer(page(TITLE_IT, HERON_LEAD, index=1))


def test_english_is_searched_first_and_italian_only_when_the_planner_asks_for_it() -> None:
    script = [
        _plan(topic=TITLE_IT, kind="film"),
        _plan(topic=TITLE_IT, kind="film", language="it"),
        '{"done": true}',
        FINAL,
    ]
    bot, transport, client = _bot(script, handler=_heron, default_language="en")

    events = _events(bot)

    first, second = _steps(events)
    assert transport.languages == ["en", "it"]  # one request each, in this order
    assert first["calls"] == ["https://en.wikipedia.org/w/api.php"] and first["pages"] == []
    assert first["searches"][0]["language"] == "en"
    assert second["calls"] == ["https://it.wikipedia.org/w/api.php"]
    (shown,) = second["pages"]
    assert (shown["language"], shown["title"], shown["url"]) == ("it", TITLE_IT, "https://it.wikipedia.org/wiki/Il_ragazzo_e_l%27airone")
    # What the planner is told before the second step: the edition used, why it is not enough, what is left.
    second_plan = client.calls[1]["input"][-1]["content"]
    assert "edizione usata: en" in second_plan and "edizione it non ancora consultata" in second_plan
    assert "nessuna pagina trovata" in second_plan
    # After the Italian step it sees both editions asked and no text it was already given.
    third_plan = client.calls[2]["input"][-1]["content"]
    assert "consultate nel turno: en, it" in third_plan and HERON_LEAD not in third_plan
    assert HERON_LEAD in client.calls[3]["input"][-1]["content"]  # the final answer has the text
    assert streamed_text(events).strip() == ANSWER


def test_there_is_no_second_edition_when_english_covers_the_question() -> None:
    plan = _plan(topic="Park Chan-wook", kind="person", depth="full", keywords=["debut", "Joint Security Area"])
    handler = by_mode(lookup=lookup_answer(page("Park Chan-wook", "Park Chan-wook is a director.")), article=article_answer(text=EN_ARTICLE_TEXT))
    bot, transport, client = _bot([plan, FINAL], handler=handler, default_language="en")

    events = _events(bot)

    (only,) = _steps(events)
    assert set(transport.languages) == {"en"} and len(transport.calls) == 2  # search and article
    assert only["pages"][0]["language"] == "en" and only["pages"][0]["url"].startswith("https://en.wikipedia.org/")
    assert len(client.calls) == 2  # one planner call and the answer: no review, no second edition
    assert names(events)[-3:] == ["answer_end", "lists", "done"]


def test_an_absent_detail_in_the_whole_english_article_lets_the_planner_try_italian() -> None:
    en_article = by_mode(lookup=lookup_answer(page("Park Chan-wook", "Park Chan-wook is a director.")), article=article_answer(text=EN_ARTICLE_TEXT))

    def handler(language, params):
        return en_article(language, params) if language == "en" else by_mode(
            lookup=lookup_answer(page("Park Chan-wook", LEAD)), article=article_answer()
        )(language, params)

    script = [
        _plan(topic="Park Chan-wook", kind="person", depth="full", keywords=["debut", "dubbing"]),
        _plan(topic="Park Chan-wook", kind="person", depth="sections", language="it", keywords=["doppiaggio"]),
        '{"done": true}',
        FINAL,
    ]
    bot, transport, client = _bot(script, handler=handler, default_language="en")

    events = _events(bot)

    assert "«dubbing» assenti dall'articolo" in client.calls[1]["input"][-1]["content"]
    assert [s["pages"][0]["language"] for s in _steps(events)] == ["en", "it"]
    assert transport.languages == ["en", "en", "it", "it"]
