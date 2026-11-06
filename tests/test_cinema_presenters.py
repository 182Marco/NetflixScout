"""The `cinema_sql_calls` step in the shared view, the terminal and the web: provenance and links, nothing internal, three languages (offline)."""
from __future__ import annotations

import json

import pytest
from cinema_build_support import make_inputs, make_phase4
from cinema_view_support import SQL, ambiguous_step, doc_step

from cinema_db.harness.build.build import Inputs, run_build
from presenters import cinema_view
from presenters.cinema_view import CODE_LABELS, KINDS, LABELS, NOTES, OPERATIONS, cinema_calls_view, wikidata_url, wikipedia_url
from presenters.terminal.cinema.renderer import render_cinema_sql_calls
from presenters.terminal.renderer import STEP_RENDERERS
from presenters.web.cinema.serializer import serialize_cinema_sql_calls_step
from presenters.web.payload import STEP_SERIALIZERS, serialize_step
from tool.cinema_db import constants
from tool.cinema_db.config import CinemaDbConfig
from tool.cinema_db.operations import OPERATIONS as TOOL_OPERATIONS
from tool.cinema_db.tool import CinemaSqlTool
from turn import STEP_CINEMA_SQL_CALLS, TraceStep

INTERNAL = (SQL, "v_work", "v_credit", "person_id", "work_id", "views", "SELECT", "sqlite", "imdb_id", "tt9")  # outside `queries`


def test_both_channels_register_the_step() -> None:
    assert STEP_CINEMA_SQL_CALLS in STEP_RENDERERS and STEP_CINEMA_SQL_CALLS in STEP_SERIALIZERS


def test_the_source_is_wikipedia_and_wikidata_with_licence_links_and_no_network_is_said() -> None:
    view = cinema_calls_view(doc_step(), "it")
    assert view.source == "Fonte: Wikipedia (CC BY-SA 4.0) e Wikidata (CC0 1.0), dati di un archivio locale riformulati dall'assistente"
    assert [(lic.name, lic.url) for lic in view.licenses] == [("CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0/"), ("CC0 1.0", "https://creativecommons.org/publicdomain/zero/1.0/")]
    assert view.no_network == "Nessuna richiesta di rete: i dati vengono dall'archivio locale" and view.local == "4 ricerche locali, 7 ms"
    assert view.operation_label == "Filmografia" and view.status == "ok" and view.counts == "Mostrati 2 di 5"


def test_the_entity_links_are_public_pages_built_only_from_recorded_identifiers() -> None:
    view = cinema_calls_view(doc_step(), "it")
    assert view.subject is not None and view.subject.name == "Ann Regista (*1950)" and view.subject.summary == "persona"
    assert [(link.label, link.url) for link in view.subject.links] == [("Pagina Wikipedia", "https://it.wikipedia.org/wiki/Ann_Regista"), ("Elemento Wikidata", "https://www.wikidata.org/wiki/Q9101")]
    assert wikipedia_url("L'amore_(film)") == "https://it.wikipedia.org/wiki/L'amore_(film)" and wikipedia_url("Più bello") == "https://it.wikipedia.org/wiki/Pi%C3%B9_bello"
    assert wikipedia_url("") is None and wikipedia_url(None) is None and wikipedia_url("a\x00b") is None and wikipedia_url("a\nb") is None
    assert wikidata_url("Q9101") == "https://www.wikidata.org/wiki/Q9101" and wikidata_url("Q9101/../x") is None and wikidata_url("tt0000001") is None and wikidata_url(None) is None
    step = doc_step()
    step.data["subject"] = {**step.data["subject"], "wikipedia_it": None, "wikidata_id": "not an id"}
    assert cinema_calls_view(step, "it").subject.links == []  # a missing or invalid identifier gives no link, never a guessed one


def test_the_payload_carries_the_executed_queries_and_nothing_else_internal() -> None:
    for step in (doc_step(), ambiguous_step()):
        for language in ("it", "en", "de", "fr"):
            payload = serialize_cinema_sql_calls_step(step, language)
            queries = payload.pop("queries")
            assert [(q["sql"], q["params"], q["rows"], q["ms"]) for q in queries] == [(SQL, [13], 1, 2)]  # exactly what the guard ran, nothing planned
            assert queries[0]["display_sql"] == "SELECT work_id, title FROM v_work WHERE work_id = 13 LIMIT 1"
            assert set(queries[0]) == {"sql", "params", "display_sql", "rows", "ms", "detail"}  # no view list, no truncation flag
            rest = json.dumps(payload, ensure_ascii=False)
            for word in INTERNAL:
                assert word not in rest, (language, word)
    assert set(serialize_step(doc_step(), "it")) >= {"kind", "title", "source", "labels", "subject", "licenses", "notes", "status_label", "queries"} and "calls" not in serialize_step(doc_step(), "it")


def test_the_parameters_are_cleaned_cut_and_credentials_masked_and_no_query_means_none_shown() -> None:
    step = doc_step()
    step.data["queries"] = [{"sql": "SELECT title FROM v_work WHERE title = ? AND year = ? AND wikidata_id = ?", "params": ["It's\x07 ok", 1999, "sk-" + "a" * 40], "rows": 0, "ms": 1},
                            {"sql": "  ", "params": []}, "not a dict", {"sql": "SELECT 1", "params": ["ab " * 200]}]
    view = cinema_calls_view(step, "it")
    assert [q.params[0] for q in view.queries] == ["It's ok", ("ab " * 200).strip()[:119] + "…"] and view.queries[0].params[2] == "***"
    assert "***" in view.queries[0].display_sql and "sk-" not in view.queries[0].display_sql and "\x07" not in view.queries[0].display_sql
    step.data["queries"] = []
    assert cinema_calls_view(step, "it").queries == []


def test_the_limits_of_the_data_are_shown_in_the_language_and_unknown_codes_are_dropped() -> None:
    it = cinema_calls_view(doc_step(), "it")
    assert it.notes == [NOTES["it"]["filmography"], NOTES["it"]["limit"], NOTES["it"]["ids_partial"]]  # "not_a_known_note" is not shown
    assert cinema_calls_view(doc_step(), "en").notes[1] == "The list was cut at the limit shown." and cinema_calls_view(doc_step(), "de").status_label == "Daten im lokalen Archiv gefunden"
    assert cinema_calls_view(doc_step(), "fr").title == LABELS["en"]["title"]  # every other language reads English, as the fixed texts do


def test_an_ambiguous_result_lists_alternatives_without_data_and_says_how_many_were_not_listed() -> None:
    view = cinema_calls_view(ambiguous_step(), "it")
    assert view.status == "ambiguous" and view.status_label == "Più corrispondenze: nessun dato assegnato" and view.subject is None and view.reason == "gli identificativi indicano opere diverse"
    assert view.candidates == ["Crash (1996, film, David Cronenberg)", "Crash (2008–2009, serie)", "+3 altre non mostrate"] and view.partial is True
    assert cinema_calls_view(ambiguous_step(), "en").candidates[-1] == "+3 more not shown"


def test_a_step_with_missing_or_hostile_data_still_renders() -> None:
    hostile = TraceStep(kind=STEP_CINEMA_SQL_CALLS, title="x", data={"status": "weird", "operation": "nope", "reason": "a\x00b\x07c", "subject": {"title": "Evil\x1b[31m title"}, "candidates": ["not a dict", None], "notes": [None, 3]})
    view = cinema_calls_view(hostile, "it")
    assert view.status == "error" and view.operation_label is None and view.reason == "abc" and view.subject.name == "Evil[31m title"
    assert cinema_calls_view(TraceStep(kind=STEP_CINEMA_SQL_CALLS, title="x", data={}), "it").status == "error"


def test_the_terminal_prints_the_same_content(capsys: pytest.CaptureFixture[str]) -> None:
    render_cinema_sql_calls(doc_step(), "it")
    out = capsys.readouterr().out
    for fragment in ("ARCHIVIO LOCALE", "Fonte: Wikipedia (CC BY-SA 4.0) e Wikidata (CC0 1.0)", "Filmografia", "Ann Regista (*1950)", "https://it.wikipedia.org/wiki/Ann_Regista",
                     "https://www.wikidata.org/wiki/Q9101", "Mostrati 2 di 5", "Limiti dei dati", "https://creativecommons.org/licenses/by-sa/4.0/"):
        assert fragment in out, fragment
    assert "SELECT work_id, title FROM v_work WHERE work_id = 13 LIMIT 1" in out and "Query SQL eseguite" in out  # the executed query, values inlined for reading
    rest = out.replace("SELECT work_id, title FROM v_work WHERE work_id = 13 LIMIT 1", "")
    assert not any(word in rest for word in INTERNAL if word != SQL)


def test_every_table_of_texts_is_complete_in_every_language_and_covers_what_the_tool_can_say() -> None:
    for table in (LABELS, OPERATIONS, KINDS, NOTES, CODE_LABELS):
        assert set(table) == {"it", "en", "de"}
    for key in ("title", "source", "no_network", "local", "ok", "empty", "ambiguous", "unverified", "not_found", "error"):
        assert all(key in LABELS[lang] for lang in LABELS)
    assert set(LABELS["it"]) == set(LABELS["en"]) == set(LABELS["de"]) and set(NOTES["it"]) == set(NOTES["en"]) == set(NOTES["de"])
    assert set(OPERATIONS["it"]) == set(OPERATIONS["en"]) == set(OPERATIONS["de"]) == set(TOOL_OPERATIONS)  # an operation of the tool without a label would show nothing
    assert set(NOTES["it"]) == set(constants.NOTES)  # every note the tool can attach has a translation
    assert set(KINDS["it"]) >= {"film", "short", "tv_film", "series", "miniseries", "person"}


@pytest.fixture(scope="module")
def real_step(tmp_path_factory) -> TraceStep:
    """The step the REAL tool produces on the miniature database, to prove the shape the view reads is the shape the trace writes."""
    tmp = tmp_path_factory.mktemp("cinema_presenter")
    base = make_inputs(tmp, awards_demo=True)
    out = tmp / "out" / "cinema.sqlite3"
    run_build(out, Inputs(base.film_snapshot, base.series_snapshot, base.film_catalog, base.series_dir, phase4=make_phase4(tmp / "p4")), log=lambda *_: None)
    tool = CinemaSqlTool(config=CinemaDbConfig(enabled=True, db_path=str(out), max_queries_per_turn=40, default_limit=25))
    result = tool.run(query="q", params={"operation": "cast", "title": "Film di prova"})
    return TraceStep(**result["trace"][0])


def test_the_real_trace_of_the_tool_renders_with_public_links_and_nothing_internal(real_step: TraceStep) -> None:
    payload = serialize_cinema_sql_calls_step(real_step, "it")
    text = json.dumps(payload, ensure_ascii=False)
    assert payload["status"] == "ok" and payload["operation_label"] == "Cast" and payload["subject"]["name"] == "Film di prova (1982)"
    assert [link["url"] for link in payload["subject"]["links"]] == ["https://it.wikipedia.org/wiki/Film_di_prova", "https://www.wikidata.org/wiki/Q9001"]
    assert payload["queries"] and all(q["sql"].startswith("SELECT") and q["rows"] is not None for q in payload["queries"])  # the SQL the guard really ran
    rest = json.dumps({k: v for k, v in payload.items() if k != "queries"}, ensure_ascii=False)
    for word in ("SELECT", "v_credit", "v_work", "work_id", "person_id", "tt9000001", "queries"):
        assert word not in rest, word
    assert payload["notes"] and "Il cast non ha un ordine di rilievo" in payload["notes"][0]


def test_the_view_module_has_no_dependency_on_the_tool_or_the_channels() -> None:
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path(cinema_view.__file__).read_text(encoding="utf-8"))
    roots = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} | {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module and n.level == 0}
    assert roots <= {"__future__", "re", "typing", "urllib", "pydantic", "turn"}
