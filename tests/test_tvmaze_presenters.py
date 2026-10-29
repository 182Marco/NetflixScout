"""Terminal and web presenters of the TVmaze step: same data, source and licence links, languages, and
a whole planned turn from the tool to both channels (offline)."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from stream_support import reply
from tvmaze_support import doc_step, make_tool, routes_for

import app as app_module
from orchestrator import LLMOrchestrator
from presenters import OutputChannel, present
from presenters.terminal.renderer import STEP_RENDERERS
from presenters.tvmaze_view import tvmaze_calls_view
from presenters.web.payload import STEP_SERIALIZERS, to_payload
from turn import STEP_TVMAZE_CALLS, TraceStep

ROOT = Path(__file__).resolve().parents[1]


def test_terminal_and_web_are_registered_for_the_same_kind() -> None:
    assert STEP_TVMAZE_CALLS in STEP_RENDERERS and STEP_TVMAZE_CALLS in STEP_SERIALIZERS


def test_the_web_form_is_the_shared_view_with_the_attribution_links() -> None:
    payload = STEP_SERIALIZERS[STEP_TVMAZE_CALLS](doc_step(), "it")

    assert payload["kind"] == "tvmaze_calls" and payload == {"kind": "tvmaze_calls", **tvmaze_calls_view(doc_step(), "it").model_dump(mode="json")}
    assert payload["show"]["url"] == "https://www.tvmaze.com/shows/1/sample-show"
    assert payload["license"]["url"] == "https://creativecommons.org/licenses/by-sa/4.0/"
    assert "TVmaze" in payload["source"] and "CC BY-SA 4.0" in payload["source"]
    assert [c["method"] for c in payload["calls"]] == ["GET", "GET"]


def test_the_terminal_prints_the_source_every_call_the_series_page_and_the_licence(capsys) -> None:
    STEP_RENDERERS[STEP_TVMAZE_CALLS](doc_step(), "it")
    out = capsys.readouterr().out

    assert "TVMAZE" in out and "Fonte: TVmaze" in out and "CC BY-SA 4.0" in out
    assert out.count("Chiamato: GET https://api.tvmaze.com/") == 2
    assert "https://www.tvmaze.com/shows/1/sample-show" in out
    assert "Licenza: CC BY-SA 4.0 — https://creativecommons.org/licenses/by-sa/4.0/" in out
    assert "prossimo episodio" in out


@pytest.mark.parametrize("language", ["it", "en", "de", "fr", None])
def test_every_language_has_a_complete_label_set(language) -> None:
    view = tvmaze_calls_view(doc_step(), language)
    assert view.source and view.status_label and all(view.labels.values())


def test_only_links_to_the_expected_hosts_are_offered() -> None:
    step = TraceStep(
        kind=STEP_TVMAZE_CALLS,
        title="t",
        data={
            "status": "ok",
            "show": {"name": "X", "url": "https://evil.example/x"},
            "license": {"name": "CC", "url": "javascript:alert(1)"},
            "calls": [],
        },
    )
    view = tvmaze_calls_view(step, "en")
    assert view.show is not None and view.show.url is None and view.license is None


def test_a_step_without_data_does_not_break_and_alternatives_are_listed(capsys) -> None:
    STEP_RENDERERS[STEP_TVMAZE_CALLS](TraceStep(kind=STEP_TVMAZE_CALLS, title="t", data={}), "it")
    assert "Nessuna chiamata a TVmaze" in capsys.readouterr().out
    view = tvmaze_calls_view(
        TraceStep(
            kind=STEP_TVMAZE_CALLS,
            title="t",
            data={"status": "ambiguous", "candidates": [{"name": "The Office", "year": "2001", "channel": "BBC Two"}]},
        ),
        "en",
    )
    assert view.status == "ambiguous" and view.candidates[0].text == "The Office (2001, BBC Two)" and view.show is None


def test_presenters_do_not_import_the_tool_package() -> None:
    for path in [ROOT / "presenters" / "tvmaze_view.py", *(ROOT / "presenters").glob("*/tvmaze/*.py")]:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            module = node.module if isinstance(node, ast.ImportFrom) else None
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [module or ""]
            assert not any(n == "tool" or n.startswith("tool.") for n in names), path


class _Client:
    def __init__(self, plan: dict) -> None:
        self.outputs = [json.dumps(plan), "Risposta finale."]
        self.responses = self

    def create(self, **kwargs):
        return reply(self.outputs.pop(0), kwargs)


def test_a_planned_tvmaze_turn_reaches_both_channels(monkeypatch, capsys) -> None:
    monkeypatch.setattr(app_module, "classify_query_domain", lambda q, history=None: {"is_cinema": True, "language": "it"})
    tool, transport = make_tool(routes_for())
    plan = {
        "standalone_query": "Cast di Sample Show",
        "tool_name": "tvmaze_search",
        "arguments": {"title": "Sample Show", "facets": ["cast"]},
        "confidence": 0.9,
    }
    config = app_module.build_runtime_config()
    built = {"config": config, "orchestrator": LLMOrchestrator(config=config, tools=[tool], client=_Client(plan))}

    turn = app_module.handle_query(built, "Chi recita in Sample Show?", [])
    present(turn, OutputChannel.terminal)
    web = to_payload(turn)

    assert turn.tool == "tvmaze_search" and STEP_TVMAZE_CALLS in [step.kind for step in turn.steps]
    out = capsys.readouterr().out
    assert "TVmaze" in out and "https://www.tvmaze.com/shows/1/sample-show" in out and "CC BY-SA 4.0" in out
    (step,) = [s for s in web["steps"] if s["kind"] == "tvmaze_calls"]
    assert [c["url"] for c in step["calls"]] == [call[3] for call in transport.calls]
    assert step["show"]["url"] == "https://www.tvmaze.com/shows/1/sample-show"
    assert any("TVmaze" in line["text"] for line in web["story"])
