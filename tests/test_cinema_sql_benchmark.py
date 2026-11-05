"""The phase-5 benchmark itself: well-formed questions, the baseline mapped one to one, and a verification that really catches a wrong answer."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from cinema_db.harness.tool_eval import run_benchmark as bench
from cinema_db.harness.tool_eval.questions import MANUAL, QUESTIONS
from tool.cinema_db.config import CinemaDbConfig
from tool.cinema_db.models import CinemaSqlInput
from tool.cinema_db.tool import CinemaSqlTool

ROOT = Path(__file__).resolve().parents[1]
needs_db = pytest.mark.skipif(not bench.DB.is_file(), reason="the local cinema database is not built")


def test_the_questions_are_well_formed_and_the_baseline_is_mapped_one_to_one():
    keys = [q.key for q in QUESTIONS]
    assert len(keys) == len(set(keys)) and keys.count("B01") == 1
    baseline = json.loads((ROOT / "docs/cinema_db/baseline.json").read_text(encoding="utf-8"))["rows"]
    mapped = {q.baseline_no: q for q in QUESTIONS if q.baseline_no}
    assert sorted(mapped) == list(range(1, 31))
    for number, row in enumerate(baseline, 1):
        assert mapped[number].text == row["question"], number  # the same 30 questions, in the same order
    for q in QUESTIONS:
        assert q.coverage in {"full", "partial", "none"} and q.reason
        assert (q.coverage == "none") == (not q.steps), q.key
        for step in q.steps:
            if step.pick is None:
                CinemaSqlInput(query="x", **step.arguments)  # every planned step is a valid request
        if q.coverage == "partial":
            assert q.external, q.key  # a partial answer says which external tool is still needed
    assert set(MANUAL) <= set(keys) and all(MANUAL[k] for k in MANUAL)
    assert all(MANUAL.get(q.key) for q in QUESTIONS if q.coverage != "none"), "every executed question has a manual reading"


def test_the_questions_that_cannot_be_settled_locally_are_declared_so():
    unsettled = {q.key for q in QUESTIONS if not q.settles_the_question}
    assert unsettled == {"B05", "B17"}  # the database does not say remake


@needs_db
def test_the_independent_verification_catches_a_wrong_answer():
    tool = CinemaSqlTool(config=CinemaDbConfig(db_path=str(bench.DB), max_queries_per_turn=40, default_limit=25))
    raw = sqlite3.connect(f"file:{bench.DB}?mode=ro", uri=True)
    args = {"operation": "filmography", "person": "Christopher Nolan", "role": "director"}
    metadata = tool.run(query="x", params=args)["metadata"]["cinema_db"]
    assert bench.verify(raw, args, metadata) == []
    wrong = {**metadata, "total": metadata["total"] + 1}
    assert bench.verify(raw, args, wrong) == ["total 14 != 13"]
    foreign = {**metadata, "works": metadata["works"] + [{"work_id": 415700, "title": "Il padrino"}]}
    assert "lists a work the person has no such credit for" in bench.verify(raw, args, foreign)
    cast_args = {"operation": "cast", "title": "Il padrino"}
    cast = tool.run(query="x", params=cast_args)["metadata"]["cinema_db"]
    assert bench.verify(raw, cast_args, cast) == [] and bench.verify(raw, cast_args, {**cast, "total": 1}) == ["cast total 1 != 40"]
    raw.close()


@needs_db
def test_a_step_that_picks_a_candidate_that_is_not_there_is_reported_not_guessed():
    tool = CinemaSqlTool(config=CinemaDbConfig(db_path=str(bench.DB), max_queries_per_turn=40, default_limit=25))
    raw = sqlite3.connect(f"file:{bench.DB}?mode=ro", uri=True)
    question = next(q for q in QUESTIONS if q.key == "B10")
    impossible = type(question)(**{**question.__dict__, "steps": (question.steps[0], bench.Step({"operation": "find_work"}, pick={"year": 1066}))})
    record = bench.evaluate(impossible, tool, raw)
    assert record["verdict"] == "incorrect" and "could not pick the intended candidate" in record["problems"]
    raw.close()


@needs_db
def test_the_comparison_with_the_baseline_adds_up(monkeypatch):
    monkeypatch.setattr(bench, "RUNS", 1)
    tool = CinemaSqlTool(config=CinemaDbConfig(db_path=str(bench.DB), max_queries_per_turn=40, default_limit=25))
    raw = sqlite3.connect(f"file:{bench.DB}?mode=ro", uri=True)
    records = [bench.evaluate(q, tool, raw) for q in QUESTIONS]
    raw.close()
    assert not [r["key"] for r in records if r["verdict"] == "incorrect"]  # every verified answer matches the base tables
    comparison = bench.baseline_comparison(records)
    totals, rows = comparison["totals"], comparison["rows"]
    assert len(rows) == 30 and totals["now"] == 96 and totals["assumed_after"] == 49  # the baseline's own figures
    assert totals["verified_after"] >= totals["assumed_after"] and totals["verified_after"] < totals["now"]
    assert {r["no"] for r in rows if r["coverage"] == "full" and not r["answered_locally"]} == {5}  # La cosa: no remake relation in the data
    assert all(not r["answered_locally"] for r in rows if r["coverage"] == "none") and all(r["http_verified_after"] == r["http_now"] for r in rows if r["coverage"] == "none")
    assert sum(r["verdict"] == "needs_disambiguation" for r in rows) == 5


@needs_db
def test_a_ambiguous_question_costs_a_second_step_and_a_not_applicable_one_costs_nothing(monkeypatch):
    monkeypatch.setattr(bench, "RUNS", 1)
    tool = CinemaSqlTool(config=CinemaDbConfig(db_path=str(bench.DB), max_queries_per_turn=40, default_limit=25))
    raw = sqlite3.connect(f"file:{bench.DB}?mode=ro", uri=True)
    by_key = {q.key: bench.evaluate(q, tool, raw) for q in QUESTIONS if q.key in {"B01", "B05", "B19"}}
    raw.close()
    assert [by_key[k]["verdict"] for k in ("B01", "B05", "B19")] == ["correct", "needs_disambiguation", "not_applicable"]
    assert len(by_key["B05"]["steps"]) == 2 and len(by_key["B01"]["steps"]) == 1 and by_key["B19"]["queries"] == 0
