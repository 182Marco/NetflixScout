"""A whole turn through the real orchestrator with the catalog on: same answer prompt, trace carries the outcome.

Fake LLM, fake TMDb transport, embedded Qdrant in a temp folder, counting fake embedding.
"""
from __future__ import annotations

import json

import pytest
from stream_support import reply
from tmdb_support import MOVIE_ID, make_tool, movie_payload, search_movie_payload
from test_catalog_app import DIM, LONG, CountingEmbed, config, details, qdrant_folder  # noqa: F401

import app as app_module
from orchestrator import LLMOrchestrator
from presenters import OutputChannel, present
from tool.tmdb.tool import TMDB_TOOL_NAME

PLAN = {
    "standalone_query": "Chi ha diretto Interstellar?",
    "tool_name": TMDB_TOOL_NAME,
    "arguments": {"requests": [{"operation": "movie_details", "title": "Interstellar", "facets": ["credits"]}]},
    "confidence": 0.9,
}


class FakeClient:
    def __init__(self):
        self.outputs = [json.dumps(PLAN), "Risposta finale."]
        self.calls = []
        self.responses = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return reply(self.outputs.pop(0), kwargs)


def single_result():
    data = search_movie_payload()
    return {**data, "total_results": 1, "results": [r for r in data["results"] if r["id"] == MOVIE_ID]}


def turn_with(enrichers, monkeypatch, search=None):
    monkeypatch.setattr(app_module, "classify_query_domain", lambda q, history=None: {"is_cinema": True, "language": "it"})
    payload = details()
    tool, transport = make_tool({"/search/movie": search or single_result(), f"/movie/{MOVIE_ID}": payload})
    client = FakeClient()
    cfg = app_module.build_runtime_config()
    orch = LLMOrchestrator(config=cfg, tools=[tool], client=client, enrichers=enrichers(tool))
    turn = app_module.handle_query({"config": cfg, "orchestrator": orch}, "Chi ha diretto Interstellar?", history=[])
    return turn, client, transport


def test_the_catalog_changes_only_the_trace_and_never_the_final_prompt(monkeypatch, qdrant_folder):  # noqa: F811
    fake = CountingEmbed()
    monkeypatch.setattr(app_module, "embed", fake)
    off, off_client, off_transport = turn_with(lambda tool: {}, monkeypatch)
    on, on_client, on_transport = turn_with(
        lambda tool: {TMDB_TOOL_NAME: app_module.build_catalog_enricher(config(qdrant_folder), tool)}, monkeypatch)

    assert on.answer == off.answer == "Risposta finale."
    assert on_client.calls[-1]["input"] == off_client.calls[-1]["input"]  # the model never learns about the catalog
    assert [s.kind for s in on.steps] == [s.kind for s in off.steps]
    catalog = on.steps[-1].data["catalog"]
    assert catalog == [{"status": "inserted", "tmdb_id": MOVIE_ID}] and "catalog" not in off.steps[-1].data
    # Italian turn: one extra TMDb call for the English record, everything else identical.
    assert on_transport.paths.count(f"/movie/{MOVIE_ID}") == off_transport.paths.count(f"/movie/{MOVIE_ID}") + 1
    assert fake.calls and "enrichment_error" not in on_client.calls[-1]["input"][-1]["content"]


@pytest.mark.parametrize("channel", [OutputChannel.terminal, OutputChannel.web])
def test_both_channels_present_the_turn_with_the_catalog_entry(monkeypatch, qdrant_folder, channel, capsys):  # noqa: F811
    monkeypatch.setattr(app_module, "embed", CountingEmbed())
    turn, _, _ = turn_with(
        lambda tool: {TMDB_TOOL_NAME: app_module.build_catalog_enricher(config(qdrant_folder), tool)}, monkeypatch)
    out = present(turn, channel, streamed=True) if channel is OutputChannel.terminal else present(turn, channel)
    text = json.dumps(out, default=str) if out is not None else capsys.readouterr().out
    assert "api_key=***" in text or channel is OutputChannel.terminal


def test_an_ambiguous_title_is_never_written(monkeypatch, qdrant_folder):  # noqa: F811
    """Two films with the same title: TMDb picks the most popular and reports the others; not certain, so no write."""
    fake = CountingEmbed()
    monkeypatch.setattr(app_module, "embed", fake)
    turn, client, _ = turn_with(
        lambda tool: {TMDB_TOOL_NAME: app_module.build_catalog_enricher(config(qdrant_folder), tool)},
        monkeypatch, search=search_movie_payload())
    assert "catalog" not in turn.steps[-1].data and fake.calls == []
    assert "enrichment_error" not in client.calls[-1]["input"][-1]["content"]
