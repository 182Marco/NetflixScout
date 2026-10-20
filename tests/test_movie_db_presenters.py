from __future__ import annotations

import json

import pytest

from presenters import OutputChannel, present
from presenters.movie_db_view import db_query_view, format_sql
from presenters.terminal.renderer import STEP_RENDERERS
from presenters.web.movie_db import serialize_db_query_step
from turn import STEP_DB_QUERY, TraceStep, TurnResult

SQL = "SELECT m.title FROM movies m WHERE m.year >= ? AND m.clean_title LIKE ? ESCAPE '\\' LIMIT ?"
STEP = TraceStep(
    kind=STEP_DB_QUERY,
    title="Query DB",
    data={"queries": [{"sql": SQL, "params": [1990, "%L'odio%", 5]}]},
)


def _turn(*steps: TraceStep) -> TurnResult:
    return TurnResult(query="q", language="it", blocked=False, answer="Risposta.", tool="movie_db_search", steps=list(steps))


def test_format_sql_inlines_params_for_display() -> None:
    assert format_sql(SQL, [1990, "%L'odio%", 5]) == (
        "SELECT m.title FROM movies m WHERE m.year >= 1990 AND m.clean_title LIKE '%L''odio%' ESCAPE '\\' LIMIT 5"
    )


def test_format_sql_ignores_question_marks_in_literals_and_mismatches() -> None:
    assert format_sql("SELECT '?' WHERE a = ?", [None]) == "SELECT '?' WHERE a = NULL"
    assert format_sql("SELECT ?", [1, 2]) == "SELECT ?"


def test_db_query_kind_is_registered_and_fallback_is_kept(capsys) -> None:
    assert STEP_DB_QUERY in STEP_RENDERERS

    present(_turn(STEP, TraceStep(kind="future_tool_step", title="Passo nuovo", data={"esito": "ok"})), OutputChannel.terminal)

    out = capsys.readouterr().out
    assert "QUERY DB — 1 QUERY ESEGUITE" in out
    assert "🧾 SELECT m.title FROM movies m WHERE m.year >= 1990" in out
    assert "PASSO NUOVO" in out
    assert out.index("QUERY DB") < out.index("Risposta.")


def test_terminal_shows_only_queries_not_rows(capsys) -> None:
    step = TraceStep(kind=STEP_DB_QUERY, title="Query DB", data={"queries": []})

    present(_turn(step), OutputChannel.terminal)

    out = capsys.readouterr().out
    assert "Nessuna query eseguita." in out
    assert "CHUNK" not in out


def test_web_serializer_is_json_ready_and_matches_terminal(capsys) -> None:
    payload = serialize_db_query_step(STEP)

    assert json.loads(json.dumps(payload)) == payload
    assert set(payload) == {"kind", "title", "queries"}
    assert payload["queries"][0]["params"] == [1990, "%L'odio%", 5]

    present(_turn(STEP), OutputChannel.terminal)
    terminal_text = " ".join(capsys.readouterr().out.split())
    for query in db_query_view(STEP).queries:
        assert query.display_sql == payload["queries"][0]["display_sql"]
        assert query.display_sql in terminal_text.replace("🧾 ", "")


def test_web_channel_is_still_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        present(_turn(STEP), OutputChannel.web)
