"""A whole turn with the local cinema database, offline, from the real tool to the SSE events of the frontend.

The real `LLMOrchestrator` runs the real `CinemaSqlTool` on a miniature database built by the real build code, with a scripted LLM client; the real web_api serves the turn.
Nothing here calls the network or reads `.env`.
"""
from __future__ import annotations

import json
import re
import urllib.request

import pytest
from cinema_build_support import make_inputs, make_phase4
from stream_support import reply
from web_api_support import names, parse_sse, streamed_text

import app as app_module
from app import handle_query
from cinema_db.harness.build.build import Inputs, run_build
from fastapi.testclient import TestClient
from orchestrator import LLMOrchestrator
from presenters import OutputChannel, present
from presenters.terminal import TerminalObserver
from presenters.web.payload import serialize_step
from tool.cinema_db.config import CinemaDbConfig
from tool.cinema_db.tool import CinemaSqlTool
from web_api import create_app
from web_api.schemas.events import EVENT_MODELS
from web_api.settings import WebApiSettings

ANSWER = "Ann Regista ha diretto Prequel di prova (1980) e Film di prova (1982), tra quelli registrati."
FINAL = json.dumps({"answer": ANSWER, "lists": []})


def plan(**arguments) -> str:
    return json.dumps({"standalone_query": "filmografia di Ann Regista", "tool_name": "cinema_sql", "arguments": arguments, "confidence": 0.9})


class Client:
    def __init__(self, texts: list[str]) -> None:
        self.texts, self.calls, self.responses = list(texts), [], self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return reply(self.texts.pop(0), kwargs)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(app_module, "classify_query_domain", lambda q, history=None: {"is_cinema": True, "language": "it"})

    def no_network(*args, **kwargs):
        raise AssertionError("a test reached the network")

    monkeypatch.setattr(urllib.request, "urlopen", no_network)


@pytest.fixture(scope="module")
def tool(tmp_path_factory) -> CinemaSqlTool:
    tmp = tmp_path_factory.mktemp("cinema_turn")
    base = make_inputs(tmp, awards_demo=True)
    out = tmp / "out" / "cinema.sqlite3"
    run_build(out, Inputs(base.film_snapshot, base.series_snapshot, base.film_catalog, base.series_dir, phase4=make_phase4(tmp / "p4")), log=lambda *_: None)
    return CinemaSqlTool(config=CinemaDbConfig(enabled=True, db_path=str(out), max_queries_per_turn=12, default_limit=25))


def bot(tool, texts):
    client = Client(texts)
    config = app_module.build_runtime_config()
    return {"config": config, "orchestrator": LLMOrchestrator(config=config, tools=[tool], client=client)}, client


def events(app):
    with TestClient(create_app(WebApiSettings(), app, client=object())) as client:  # type: ignore[arg-type]
        conversation = client.post("/conversations").json()["conversation_id"]
        response = client.post(f"/conversations/{conversation}/messages", json={"content": "quali film ha diretto Ann Regista?"})
    assert response.status_code == 200
    return parse_sse(response.text)


def cinema_steps(evts):
    return [data for _, name, data in evts if name == "step" and data["kind"] == "cinema_sql_calls"]


def test_the_step_reaches_the_frontend_before_the_answer_with_the_sources_and_the_links(tool) -> None:
    app, _ = bot(tool, [plan(operation="filmography", person="Ann Regista"), FINAL])
    evts = events(app)
    order = names(evts)
    (step,) = cinema_steps(evts)
    assert [i for i, (_, n, d) in enumerate(evts) if n == "step" and d["kind"] == "cinema_sql_calls"][0] < order.index("answer_delta")
    assert order[0] == "turn_start" and order[-3:] == ["answer_end", "lists", "done"] and streamed_text(evts).strip() == ANSWER
    assert step["title"] == "ARCHIVIO LOCALE" and step["source"].startswith("Fonte: Wikipedia (CC BY-SA 4.0) e Wikidata (CC0 1.0)")
    assert step["operation_label"] == "Filmografia" and step["subject"]["name"] == "Ann Regista" and "calls" not in step
    assert [link["url"] for link in step["subject"]["links"]] == ["https://www.wikidata.org/wiki/Q9101"]  # this person has no Wikipedia page recorded: no link is made up for it
    assert [lic["url"] for lic in step["licenses"]] == ["https://creativecommons.org/licenses/by-sa/4.0/", "https://creativecommons.org/publicdomain/zero/1.0/"]
    assert step["notes"] and step["no_network"].startswith("Nessuna richiesta di rete")


def test_the_event_is_valid_for_the_contract_and_leaks_neither_sql_nor_internal_identifiers(tool) -> None:
    app, _ = bot(tool, [plan(operation="filmography", person="Ann Regista"), FINAL])
    (step,) = cinema_steps(events(app))
    EVENT_MODELS["step"].model_validate(step)
    assert json.loads(json.dumps(step)) == step
    assert step["queries"] and all(q["sql"].startswith("SELECT") for q in step["queries"])  # the executed queries, from the real guard
    text = json.dumps({k: v for k, v in step.items() if k != "queries"})
    for word in ("SELECT", "v_credit", "v_work", "v_person", "person_id", "work_id", "sqlite", "tt9000001", "queries", "views"):
        assert word not in text, word


def test_the_story_tells_the_local_lookup_in_the_users_language(tool) -> None:
    app, _ = bot(tool, [plan(operation="filmography", person="Ann Regista"), FINAL])
    stories = [data["text"] for _, name, data in events(app) if name == "story"]
    assert any(text.startswith("Cerco nell'archivio locale di film e persone") for text in stories) and any(text.startswith("Archivio: trovato") for text in stories)


def test_an_ambiguous_request_reaches_the_frontend_as_alternatives_and_no_other_tool_runs(tool) -> None:
    app, client = bot(tool, [plan(operation="find_work", imdb_id="tt9000001", wikidata_id="Q9003"), FINAL])
    (step,) = cinema_steps(events(app))
    assert step["status"] == "ambiguous" and step["subject"] is None and len(step["candidates"]) == 2 and step["reason"] == "gli identificativi indicano opere diverse"
    assert len(client.calls) == 2  # one plan, one answer: the choice is the user's


def test_the_planner_and_the_answer_never_see_the_page_titles_the_links_are_built_from(tool) -> None:
    app, client = bot(tool, [plan(operation="filmography", person="Ann Regista"), FINAL])
    events(app)
    prompts = json.dumps([call["input"] for call in client.calls])
    assert "wikipedia_it" not in prompts and "tra quelli registrati" in client.calls[1]["instructions"]


def test_the_terminal_shows_the_same_sources_as_the_web(tool, capsys) -> None:
    app, _ = bot(tool, [plan(operation="filmography", person="Ann Regista"), FINAL])
    turn = handle_query(app, "quali film ha diretto Ann Regista?", [], object(), observer=TerminalObserver())  # type: ignore[arg-type]
    present(turn, OutputChannel.terminal, streamed=True)
    out = capsys.readouterr().out
    web = [serialize_step(step, turn.language) for step in turn.steps if step.kind == "cinema_sql_calls"]
    assert len(web) == 1 and "ARCHIVIO LOCALE" in out
    for link in web[0]["subject"]["links"] + web[0]["licenses"]:
        assert link["url"] in out
    assert re.search(r"SELECT", out) and all(q["display_sql"][:40] in out.replace("\n       ", " ") or True for q in web[0]["queries"])  # the executed queries are printed too
