"""OMDb presenters: one shared view, two channels, three languages, no import of the tool package."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from presenters.omdb_view import omdb_calls_view
from presenters.terminal.omdb.renderer import render_omdb_calls
from presenters.web.omdb.serializer import serialize_omdb_calls_step
from presenters.terminal.renderer import STEP_RENDERERS
from presenters.web.payload import STEP_SERIALIZERS
from tool.omdb.ratings import extract_ratings
from tool.omdb.trace import build_omdb_trace
from turn import STEP_OMDB_CALLS, TraceStep

from omdb_support import record

CALLS = [{"method": "GET", "url": "https://www.omdbapi.com/?i=tt1000001&r=json&apikey=***"}]


def _step(**overrides) -> TraceStep:
    data = build_omdb_trace(
        CALLS,
        status="ok",
        title="Sample Movie",
        year="2016",
        work_type="movie",
        imdb_id="tt1000001",
        ratings=extract_ratings(record(rotten=None)),
    )[0]
    data["data"].update(overrides)
    return TraceStep(**data)


def test_both_channels_know_the_step() -> None:
    assert STEP_OMDB_CALLS in STEP_RENDERERS and STEP_OMDB_CALLS in STEP_SERIALIZERS


def test_scores_say_what_they_measure_and_missing_ones_say_so() -> None:
    view = omdb_calls_view(_step(), "it")
    rows = {row.source_label: row for row in view.ratings}

    assert rows["IMDb"].value == "7.9/10" and rows["IMDb"].kind_label == "pubblico" and rows["IMDb"].votes == "720.000 voti"
    assert rows["Metascore"].value == "81/100" and rows["Metascore"].kind_label == "critica"
    assert rows["Rotten Tomatoes"].value == "non disponibile" and not rows["Rotten Tomatoes"].available
    assert "OMDb" in view.source and view.work == "Sample Movie (2016)"


@pytest.mark.parametrize("language", ["it", "en", "de", "fr", None])
def test_every_language_has_complete_labels(language) -> None:
    view = omdb_calls_view(_step(), language)

    assert view.labels["title"] and view.status_label and all(row.value for row in view.ratings)


def test_ambiguous_titles_list_the_alternatives_and_no_score() -> None:
    step = _step(
        status="ambiguous",
        ratings=[],
        candidates=[{"title": "Sample Movie", "year": "1984", "type": "movie", "imdb_id": "tt1000001"}],
    )
    view = omdb_calls_view(step, "en")

    assert view.ratings == [] and view.candidates[0].text.startswith("Sample Movie (1984)")
    assert "no score assigned" in view.status_label


def test_an_error_shows_its_reason_in_words() -> None:
    view = omdb_calls_view(_step(status="error", reason="quota_exceeded", ratings=[]), "it")

    assert view.reason == "limite giornaliero raggiunto" and view.status_label == "Errore"


def test_unknown_status_and_garbage_data_do_not_break_the_view() -> None:
    step = TraceStep(kind=STEP_OMDB_CALLS, title="x", data={"status": "???", "ratings": [None, {"source": 3}, {"source": "imdb", "status": "available", "value": "x"}], "calls": ["http://x", 3]})
    view = omdb_calls_view(step, "en")

    assert view.status == "error" and view.calls == []
    assert [row.available for row in view.ratings] == [False, False]


def test_control_characters_of_api_text_are_removed_for_display() -> None:
    step = _step(title="Sa\x1b[31mmple\x07", year="20\n16")
    view = omdb_calls_view(step, "en")

    assert "\x1b" not in (view.work or "") and "\x07" not in (view.work or "")


def test_terminal_and_web_show_the_same_data(capsys) -> None:
    step = _step()
    render_omdb_calls(step, "it")
    printed = capsys.readouterr().out
    payload = serialize_omdb_calls_step(step, "it")

    assert payload["kind"] == STEP_OMDB_CALLS and payload["source"] in printed
    for row in payload["ratings"]:
        assert row["source_label"] in printed and row["value"] in printed
    assert "GET https://www.omdbapi.com/?i=tt1000001&r=json&apikey=***" in printed
    assert payload["calls"] == CALLS


def test_the_presenters_do_not_import_the_tool_package() -> None:
    root = Path(__file__).resolve().parents[1] / "presenters"
    for path in [root / "omdb_view.py", *(root / "terminal" / "omdb").glob("*.py"), *(root / "web" / "omdb").glob("*.py")]:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            module = node.module if isinstance(node, ast.ImportFrom) and node.level == 0 else None
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [module or ""]
            assert not any(name.split(".")[0] in {"tool", "omdb"} for name in names), path.name
