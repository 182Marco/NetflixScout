"""The prepared v2/v3 planner evaluation: offline checks of the cases, the judging and the guards (nothing is called)."""
from __future__ import annotations

import typing

import pytest

from cinema_db.harness.tool_eval import run_v3_eval as E
from tool.cinema_db.models import Operation


def test_cases_are_distinct_scenarios_with_valid_expectations():
    assert len({c.key for c in E.CASES}) == len(E.CASES) == 14 and len({c.scenario for c in E.CASES}) == len(E.CASES)
    tools = {"cinema_sql", "tmdb_search", "omdb_search", "movie_db_search", "wikidata_search", "wikipedia_search"}
    operations = set(typing.get_args(Operation))
    for c in E.CASES:
        assert set(c.first) <= tools and set(c.forbidden) <= tools and set(c.ops) <= operations and set(c.v2_ops) <= operations
        assert not (set(c.first) & set(c.forbidden))


def test_the_routing_judge_separates_the_states():
    ratings = next(c for c in E.CASES if c.key == "V05")
    assert E.judge_routing(ratings, "v3", "cinema_sql", "ratings")["first_ok"]
    assert not E.judge_routing(ratings, "v3", "movie_db_search", None)["first_ok"]  # forbidden: a single title's ratings must not go to MovieLens
    assert E.judge_routing(ratings, "v2", "tmdb_search", None)["first_ok"]  # v2 has no ratings operation: a route that is not forbidden is acceptable (the report lists it)
    assert not E.judge_routing(ratings, "v2", "movie_db_search", None)["first_ok"]
    metascore = next(c for c in E.CASES if c.key == "V06")
    assert E.judge_routing(metascore, "v3", "omdb_search", None)["first_ok"] and not E.judge_routing(metascore, "v3", "cinema_sql", "ratings")["first_ok"]


def test_the_full_judge_counts_external_steps_and_the_declared_level():
    uncertain = next(c for c in E.CASES if c.key == "V02")
    good = {"tools": ["cinema_sql", "tmdb_search"], "answer": "Identificata con buona probabilità: regia X, anno 1932."}
    assert E.judge_full(uncertain, "v3", good) == {"external_steps": 1, "within_external_budget": True, "forbidden_used": [], "must_ok": True, "level_ok": True}
    bad = {"tools": ["cinema_sql", "tmdb_search", "wikipedia_search"], "answer": "Regia X."}
    judged = E.judge_full(uncertain, "v3", bad)
    assert not judged["within_external_budget"] and not judged["level_ok"]


def test_nothing_runs_without_the_flag_and_the_authorisation(monkeypatch):
    monkeypatch.delenv("CINEMA_V3_EVAL_AUTHORIZED", raising=False)
    for stage in ("routing", "full"):
        with pytest.raises(SystemExit, match="--live"):
            E.main([stage])
        with pytest.raises(SystemExit, match="CINEMA_V3_EVAL_AUTHORIZED"):
            E.main([stage, "--live"])


def test_the_plan_and_the_empty_report_are_offline(capsys):
    assert E.main(["plan"]) == 0
    out = capsys.readouterr().out
    assert "Nothing was called" in out and "14 cases x 2 states" in out
    assert "preparata, non eseguita" in E.report_text() or E.RUNS.is_file()
