"""Offline tests of the live planner evaluation under film/series/both. SIMULATED: the planner is a scripted client (what the real model chooses is what the live run
measures); the orchestrator loop, the guard, the stubs, the grader and the call cap are the real code."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from movie_db.harness.evaluation import preference_routing_cases as PC
from movie_db.harness.evaluation import run_preference_routing_eval as E
from stream_support import reply


class Scripted:
    def __init__(self, plans):
        self.plans, self.responses, self.calls = list(plans), self, []

    def create(self, **kw):
        self.calls.append(kw)
        r = reply(json.dumps(self.plans.pop(0) if self.plans else {"done": True}), kw)
        r.usage = SimpleNamespace(input_tokens=10, output_tokens=2)
        return r


def plan(tool, conflicts=None, args=None, **kw):
    return {"standalone_query": "q", "tool_name": tool, "arguments": args or {}, "confidence": 0.9, "conflicts": conflicts or [], **kw}


def cell(case_id, value):
    return next(c for c in PC.cells() if c[0].id == case_id and c[1] == value)


def run(case_id, value, plans, cap=60):
    client = E.CountingClient(Scripted(plans), cap)
    orch, executed, _ = E.build_runtime(client)
    case, v, expect = cell(case_id, value)
    return E.run_cell(orch, executed, client, case, v, expect), client


def test_the_matrix_is_what_the_document_describes():
    cs = PC.cells()
    assert {c.id for c, _, _ in cs} == {f"Q{n:02d}" for n in range(1, 23)} and len(cs) == 52
    assert all(c.critical for c, _, _ in cs[:5]) and {v for _, v, _ in cs} == {"film", "series", "both"}
    assert any(e.conflict for _, _, e in cs) and any(e.one_rag for _, _, e in cs)


def test_a_coherent_plan_is_correct_and_the_tool_really_ran():
    row, client = run("Q03", "film", [plan("rag_search", args={"query": "Film come Matrix ma senza i seguiti", "k_finale": 3})])
    assert row["grade"]["correct"] and [e["tool"] for e in row["executed"]] == ["rag_search"] and not row["blocked_attempts"] and client.total == 1


def test_a_conflict_is_correct_only_when_declared_and_nothing_ran():
    row, _ = run("Q05", "film", [plan(None, conflicts=[{"setting": "content_type", "requested": "una serie"}])])
    assert row["grade"]["correct"] and row["executed"] == [] and row["conflicts"]


def test_a_forbidden_proposal_is_blocked_counted_against_the_planner_and_never_executed():
    row, client = run("Q04", "film", [plan("series_rag_search", args={"query": "x"}), plan(None, conflicts=[{"setting": "content_type", "requested": "serie"}])])
    assert row["executed"] == [] and len(row["blocked_attempts"]) == 1 and row["blocked_attempts"][0]["tool"] == "series_rag_search"
    assert not row["grade"]["correct"] and row["grade"]["guard_rescued"] and client.total == 2


def test_tvmaze_for_seasons_and_the_rags_stay_out():
    ok, _ = run("Q05", "both", [plan("tvmaze_search", args={"title": "Breaking Bad", "facets": ["seasons"]})])
    assert ok["grade"]["correct"]
    bad, _ = run("Q05", "both", [plan("series_rag_search", args={"query": "stagioni di Breaking Bad"})])
    assert not bad["grade"]["correct"] and any("required tool not executed: tvmaze_search" in p for p in bad["grade"]["problems"])


def test_both_two_rags_in_a_combined_request_and_exactly_one_otherwise():
    row, _ = run("Q13", "both", [plan("rag_search", args={"query": "memoria"}, more_steps=True, parts=[{"part": "film", "tool": "rag_search"}, {"part": "serie", "tool": "series_rag_search"}]),
                                 plan("series_rag_search", args={"query": "memoria"}, more_steps=False)])
    assert {e["tool"] for e in row["executed"]} == set(PC.RAGS)
    assert not E.grade(PC.Expect(one_rag=True), [{"tool": "rag_search"}, {"tool": "series_rag_search"}], [], [])["correct"]
    assert E.grade(PC.Expect(one_rag=True), [{"tool": "rag_search"}], [], [])["correct"]


def test_movielens_lists_are_cinema_sql_and_the_operation_is_checked():
    args = {"operation": "movielens", "ml_mode": "top_rated"}
    ok, _ = run("Q10", "both", [plan("cinema_sql", args=args)])
    assert ok["grade"]["correct"]
    wrong, _ = run("Q10", "both", [plan("cinema_sql", args={"operation": "ratings"})])
    assert any("movielens not executed" in p for p in wrong["grade"]["problems"])


def test_the_type_of_ratings_and_by_tag_follows_the_content_type_and_is_checked():
    """FASE 23: not only the operation, also the arguments passed to cinema_sql."""
    tag = {"operation": "movielens", "ml_mode": "by_tag", "tag": "time travel"}
    ok, _ = run("Q20", "film", [plan("cinema_sql", args={**tag, "type": "film"})])
    assert ok["grade"]["correct"]
    filled, _ = run("Q20", "film", [plan("cinema_sql", args=tag)])  # no type under a film-only setting: the guard fills it in, and the executed call carries it
    assert filled["grade"]["correct"] and filled["executed"][0]["arguments"]["type"] == "film"
    wrong, _ = run("Q20", "film", [plan("cinema_sql", args={**tag, "type": "series"})])  # the other kind is refused by the guard
    assert wrong["blocked_attempts"] and not wrong["grade"]["correct"]
    both, _ = run("Q20", "both", [plan("cinema_sql", args={**tag, "type": "film"})])  # both: no kind named, so no kind must be passed
    assert not both["grade"]["correct"]
    free, _ = run("Q20", "both", [plan("cinema_sql", args=tag)])
    assert free["grade"]["correct"]
    ratings, _ = run("Q19", "series", [plan("cinema_sql", args={"operation": "ratings", "type": "series"})])
    assert ratings["grade"]["correct"]


def test_an_explicit_request_of_the_other_kind_is_a_conflict_for_tags():
    cells = {(c.id, v): e for c, v, e in PC.cells()}
    assert cells[("Q21", "film")].conflict and cells[("Q22", "series")].conflict and not cells[("Q21", "both")].conflict


def test_the_call_cap_stops_before_the_extra_call(monkeypatch):
    client = E.CountingClient(Scripted([plan("rag_search", args={"query": "x"}, more_steps=True, parts=[{"part": "a", "tool": "rag_search"}, {"part": "b", "tool": "tmdb_search"}])]), 1)
    orch, executed, _ = E.build_runtime(client)
    case, v, expect = cell("Q09", "film")
    with pytest.raises(E.CallCapReached):
        E.run_cell(orch, executed, client, case, v, expect)
    assert client.total == 1


def test_run_refuses_without_live_or_authorisation(monkeypatch, capsys):
    monkeypatch.delenv(E.AUTH_ENV, raising=False)
    assert E.main(["run", "--label", "t"]) == 2
    assert E.main(["run", "--live", "--label", "t"]) == 2


def test_summary_requires_every_critical_cell_and_no_blocked_step():
    good = {"id": "Q03", "value": "film", "critical": True, "grade": {"correct": True, "guard_rescued": False, "redundant_calls": 0, "problems": []}, "blocked_attempts": [],
            "planner_calls": 1, "tokens": {"input": 5, "output": 1}, "ms": 100}
    assert E.summarize([good])["passed"]
    bad = {**good, "id": "Q04", "grade": {**good["grade"], "correct": False, "problems": ["x"]}}
    s = E.summarize([good, bad])
    assert not s["passed"] and s["critical_failures"] == ["Q04/film"] and s["overall"]["pct"] == 50.0


def test_reconcile_keeps_the_first_run_and_the_reruns_apart(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "OUT_ROOT", tmp_path)

    def row(i, v, ok, calls=1):
        return {"id": i, "value": v, "planner_calls": calls, "executed": [], "conflicts": [], "grade": {"correct": ok, "problems": [] if ok else ["x"]}}

    for label, rows in (("a", [row("Q1", "film", True), row("Q2", "film", False, 2)]), ("b", [row("Q2", "film", True, 1)])):
        (tmp_path / label).mkdir()
        (tmp_path / label / "run.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    out = E.reconcile(["a", "b"])
    assert out["planner_calls_total"] == 4 and out["first_run_correct"] == 1 and out["latest_correct"] == 2
    assert out["failed_in_first_run"] == ["Q2/film"] and out["still_failing_after_reruns"] == [] and list(out["reruns"]) == ["Q2/film"]
    assert (tmp_path / "a" / "run.jsonl").read_text().count("\n") == 1  # historical files untouched
