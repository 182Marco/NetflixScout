"""Shared view, terminal and web forms of the `wikidata_calls` step (offline)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from wikidata_support import doc_step

from presenters.terminal.renderer import STEP_RENDERERS
from presenters.terminal.wikidata.renderer import render_wikidata_calls
from presenters.web.payload import STEP_SERIALIZERS
from presenters.web.wikidata.serializer import serialize_wikidata_calls_step
from presenters.wikidata_view import CODE_LABELS, KIND_LABELS, LABELS, wikidata_calls_view
from turn import STEP_WIKIDATA_CALLS, TraceStep


def _step(**data) -> TraceStep:
    base = doc_step().model_dump()["data"]
    return TraceStep(kind=STEP_WIKIDATA_CALLS, title="Wikidata", data={**base, **data})


def test_both_channels_register_the_step() -> None:
    assert STEP_WIKIDATA_CALLS in STEP_RENDERERS and STEP_WIKIDATA_CALLS in STEP_SERIALIZERS


def test_the_view_has_source_licence_calls_work_and_the_relations_with_their_links() -> None:
    view = wikidata_calls_view(_step(), "it")

    assert view.source == "Fonte: Wikidata, dati riformulati dall'assistente, licenza CC0 1.0"
    assert view.license is not None and view.license.url == "https://creativecommons.org/publicdomain/zero/1.0/"
    assert len(view.calls) == 2 and view.calls[0].method == "GET"
    assert view.status == "ok" and view.work is not None and view.work.name == "Sample Film (1982)"
    assert view.work.summary == "film, IMDb tt9000001, TMDb 9001"
    assert view.work.url.startswith("https://www.wikidata.org/wiki/Q")
    assert [(g.label, [i.text for i in g.items]) for g in view.groups] == [
        ("Basata su", ["Sample Novel (1968, opera letteraria)"]),
        ("Opere basate su questa", ["Sample Remake (2017, film)"]),
    ]
    assert all(i.url.startswith("https://www.wikidata.org/wiki/") for g in view.groups for i in g.items)


def test_alternatives_show_year_director_and_ids() -> None:
    step = _step(
        status="ambiguous", reason="ambiguous", work=None, relations={},
        candidates=[{"title": "Crash", "year": 1996, "kind": "film", "url": "https://www.wikidata.org/wiki/Q1", "directors": ["David Cronenberg"], "imdb_id": "tt0115964", "tmdb_id": 884}],
    )

    view = wikidata_calls_view(step, "en")

    assert view.status_label == "Several works match: no data assigned" and view.reason == "several works with this title"
    assert [c.text for c in view.candidates] == ["Crash (1996, film, director David Cronenberg, IMDb tt0115964, TMDb 884)"]


def test_franchise_members_show_what_was_cut_and_what_could_not_be_read() -> None:
    step = _step(
        franchises=[{"title": "Saga", "url": None, "kind": None, "works": [{"title": "One", "year": 1980, "kind": "film", "url": None}], "omitted": 4}],
        unavailable={"franchise": "turn_limit"},
    )

    view = wikidata_calls_view(step, "en")

    franchise = view.groups[-1]
    assert franchise.label == "Franchise or series: Saga" and [i.text for i in franchise.items] == ["One (1980, film)", "+4 more not shown"]
    assert view.unavailable == ["franchise: per-turn call limit"]


@pytest.mark.parametrize("language", ["it", "en", "de", "fr"])
def test_every_language_renders_and_unknown_ones_read_english(language, capsys) -> None:
    step = _step()

    render_wikidata_calls(step, language)
    printed = capsys.readouterr().out
    payload = serialize_wikidata_calls_step(step, language)

    assert payload["kind"] == STEP_WIKIDATA_CALLS and payload["source"] in printed
    assert all(f"GET {call['url']}" in printed for call in payload["calls"])
    assert payload["license"]["url"] in printed and payload["work"]["url"] in printed


def test_the_tables_have_the_same_keys_in_every_language() -> None:
    for table in (LABELS, KIND_LABELS, CODE_LABELS):
        assert set(table["it"]) == set(table["en"]) == set(table["de"])


def test_garbage_in_the_step_never_breaks_the_view_and_links_must_be_https_on_the_right_host() -> None:
    step = TraceStep(
        kind=STEP_WIKIDATA_CALLS,
        title="t",
        data={
            "status": "???",
            "work": {"title": "x\x1b[31m", "url": "javascript:alert(1)"},
            "relations": {"sources": [None, 3, {"title": "y", "url": "http://www.wikidata.org/wiki/Q1"}], "next": "no"},
            "candidates": "no",
            "license": {"name": "CC0 1.0", "url": "http://evil.test/"},
            "calls": ["http://plain.test/", {"method": "GET", "url": "https://ok.test/?apikey=LEAK"}],
        },
    )

    view = wikidata_calls_view(step, "en")
    dumped = json.dumps(view.model_dump(mode="json"))

    assert view.status == "error" and view.work.url is None and view.license is None
    assert [i.url for g in view.groups for i in g.items] == [None]
    assert "\x1b" not in dumped and "javascript" not in dumped and "LEAK" not in dumped and "evil.test" not in dumped


def test_the_presenters_do_not_import_the_tool_package() -> None:
    root = Path(__file__).resolve().parent.parent / "presenters"
    for path in [root / "wikidata_view.py", *root.glob("terminal/wikidata/*.py"), *root.glob("web/wikidata/*.py")]:
        assert not re.search(r"^\s*(from|import)\s+tool\b", path.read_text(encoding="utf-8"), re.M), path


def test_a_partial_list_of_alternatives_is_told_apart_from_a_complete_one(capsys) -> None:
    row = {"title": "Crash", "year": 1996, "kind": "film", "url": "https://www.wikidata.org/wiki/Q1", "directors": [], "imdb_id": None, "tmdb_id": None}
    base = {"status": "ambiguous", "reason": "ambiguous", "work": None, "relations": {}, "candidates": [row]}

    complete = wikidata_calls_view(_step(**base, candidates_omitted=0, incomplete=False), "it")
    omitted = wikidata_calls_view(_step(**base, candidates_omitted=4, incomplete=False), "en")
    cut = wikidata_calls_view(_step(**base, candidates_omitted=0, incomplete=True), "de")

    assert complete.partial is False and complete.partial_label is None and len(complete.candidates) == 1
    assert omitted.partial is True and [c.text for c in omitted.candidates][-1] == "+4 more not shown"
    assert omitted.partial_label == "Partial list: other works with this title may exist"
    assert cut.partial is True and cut.partial_label.startswith("Teilliste")

    render_wikidata_calls(_step(**base, candidates_omitted=4, incomplete=False), "it")
    printed = capsys.readouterr().out
    assert "+4 altre non mostrate" in printed and "Elenco parziale" in printed
    render_wikidata_calls(_step(**base), "it")
    assert "Elenco parziale" not in capsys.readouterr().out


def test_a_partial_flag_without_alternatives_shows_nothing() -> None:
    view = wikidata_calls_view(_step(candidates=[], candidates_omitted=3, incomplete=True), "it")

    assert view.candidates == [] and view.partial is False
