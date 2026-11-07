"""Block L0 of phase 8 is reproducible offline: fixed questions, its own data folder, a report that reads the new timings. No network, no OpenAI."""
from __future__ import annotations

import json
import re

import pytest

from cinema_db.harness.tool_eval import run_l0
from cinema_db.harness.tool_eval import run_live7


def test_the_twelve_questions_exist_and_are_development_questions() -> None:
    assert len(run_l0.L0_KEYS) == 12 == len(set(run_l0.L0_KEYS))
    assert [q.key for q in run_l0.selected()] == list(run_l0.L0_KEYS)
    assert not any(re.fullmatch(r"F\d\d", key) for key in run_l0.L0_KEYS)  # the sealed final sample (F01-F20) is never used here


def test_it_writes_nowhere_near_the_phase_7_data_and_needs_live_to_run() -> None:
    assert run_l0.BASE != run_live7.DATA and run_l0.BASE.name == "phase8_l0"
    with pytest.raises(SystemExit):
        run_l0.main(["run", "--label", "T"])  # no --live: refuses before touching the network or the disk


def test_plan_calls_nothing_and_estimates_tokens(capsys) -> None:
    run_l0.main(["plan"])
    out = capsys.readouterr().out
    assert "Nothing was called" in out and "24 runs" in out


def test_the_report_reads_every_measure_the_owner_asked_for(tmp_path, monkeypatch) -> None:
    turn = {"wall_s": 12.0, "timings": {
        "classifier_ms": 800, "planner_calls": 2, "planner_ms": 6000,
        "planner": [{"kind": "first", "ms": 3500, "input_tokens": 14700, "output_tokens": 300}, {"kind": "next", "ms": 2500, "input_tokens": 15500, "output_tokens": 40}],
        "tools": [{"tool": "cinema_sql", "ms": 20, "sql_ms": 1.5, "http_calls": 0}, {"tool": "omdb_search", "ms": 900, "sql_ms": 0, "http_calls": 2}],
        "tool_ms": 920, "sql_ms": 1.5, "answer_ms": 4000, "answer_first_delta_ms": 700, "answer_tokens": {"input_tokens": 3200, "output_tokens": 410}}}
    runs = tmp_path / "runs.jsonl"
    runs.write_text(json.dumps({"key": "B13", "mode": "on", "rep": 1, "tools": ["cinema_sql", "omdb_search"], "turns": [turn]}) + "\n"
                    + json.dumps({"key": "E05", "mode": "on", "rep": 1, "error": "TimeoutError"}) + "\n", encoding="utf-8")
    monkeypatch.setattr(run_l0, "RUNS", runs)

    b = run_l0.breakdown(json.loads(runs.read_text().splitlines()[0]))
    assert (b["planner_calls"], b["planner_ms"], b["planner_in"], b["planner_out"]) == (2, 6000, 30200, 340)
    assert (b["tool_ms"], b["sql_ms"], b["http"], b["answer_in"], b["answer_out"]) == (920, 1.5, 2, 3200, 410)
    text = run_l0.report_text()
    assert "1 esecuzioni valide (1 con errore)" in text and "| B13 | 1 | cinema_sql>omdb_search |" in text
    assert "Dove va il tempo" in text and "`first`" in text and "`next`" in text
    assert run_l0.done() == {("B13", 1)}  # an errored run is repeated


def test_each_state_has_its_own_folder_and_a_label_is_required(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(run_l0, "BASE", tmp_path)
    for name in ("DATA", "RUNS", "OUT_MD"):
        monkeypatch.setattr(run_l0, name, getattr(run_l0, name))  # restored after the test
    with pytest.raises(SystemExit):
        run_l0.main(["run", "--live"])  # no label: nothing is run
    with pytest.raises(SystemExit):
        run_l0.use_label("../escape")
    run_l0.use_label("A")
    a = (run_l0.DATA, run_l0.RUNS, run_l0.OUT_MD)
    run_l0.use_label("B")
    assert a[0] != run_l0.DATA and a[1] != run_l0.RUNS and a[2] != run_l0.OUT_MD
    assert run_l0.DATA == tmp_path / "B" and run_l0.OUT_MD.name == "PHASE8_L0_B.md"


def test_a_folder_with_runs_of_another_commit_refuses_new_runs(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(run_l0, "BASE", tmp_path)
    for name in ("DATA", "RUNS", "OUT_MD"):
        monkeypatch.setattr(run_l0, name, getattr(run_l0, name))
    run_l0.use_label("A")
    run_l0.DATA.mkdir(parents=True)
    run_l0.RUNS.write_text(json.dumps({"key": "B01", "rep": 1, "git_head": "0" * 40}) + "\n", encoding="utf-8")
    monkeypatch.setattr(run_l0.P6, "build", lambda mode: pytest.fail("the app must not even be built"))
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    with pytest.raises(SystemExit, match="another --label"):
        run_l0.main(["run", "--live", "--label", "A"])
