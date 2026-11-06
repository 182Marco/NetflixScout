"""The structure of the live evaluation (offline: nothing here calls the API): which questions, the safety against embeddings and paid calls, the report arithmetic."""
from __future__ import annotations

import json

import pytest

from cinema_db.harness.tool_eval import run_live as live
from cinema_db.harness.tool_eval.questions import QUESTIONS


def test_the_runs_cover_the_baseline_and_the_benchmark_without_duplicates_and_skip_only_what_would_embed() -> None:
    questions = live.live_questions()
    keys = [q.key for q in questions]
    assert len(keys) == len(set(keys)) == 47
    benchmark = {q.key for q in QUESTIONS}
    assert benchmark - set(keys) == {"B24", "B25"} == set(live.SKIPPED)  # recommendations by theme go to the film index, which makes embeddings
    assert {f"B{n:02d}" for n in range(1, 31)} - {"B24", "B25"} <= set(keys) and {f"E{n:02d}" for n in range(1, 10)} <= set(keys)
    assert set(live.MUST) <= set(keys) and set(live.EXPECT_LOCAL) <= set(keys)
    kinds = {q.kind for q in questions}
    assert {"local", "partial", "external", "guard", "multi", "language"} <= kinds


def test_the_scenarios_the_integration_must_get_right_are_in_the_runs() -> None:
    by_key = {q.key: q for q in live.live_questions()}
    assert by_key["X05"].kind == "multi" and len(by_key["X05"].turns) == 2  # a namesake asked, then settled
    assert by_key["X06"].preferences == {"preferred_sources": "reviews"} and by_key["X07"].preferences == {"content_type": "series"}
    assert "Which films" in by_key["X10"].turns[0] and "Wer hat" in by_key["X11"].turns[0]  # English and German
    assert by_key["B19"].kind == "external" and by_key["B22"].kind == "external"  # streaming and ratings keep their tools


def test_running_or_judging_needs_the_explicit_live_flag() -> None:
    for command in ("run", "judge"):
        with pytest.raises(SystemExit, match="--live"):
            live.main([command])


def test_the_runs_never_allow_the_film_index_nor_fall_back_to_it() -> None:
    import inspect

    source = inspect.getsource(live.build)
    assert '"fallback_tool": "tmdb_search"' in source and '"rag_search" not in app["orchestrator"]._allowed_tool_names()' in source
    assert "rag_search" not in source.split('"allowed_tools": [')[1].split("]")[0]


def test_the_fact_check_is_case_insensitive_and_needs_one_word_of_every_group() -> None:
    assert live.has_facts("Il regista è Christopher NOLAN, con Murphy", (("nolan",), ("murphy", "caine")))
    assert not live.has_facts("Solo Nolan", (("nolan",), ("murphy", "caine")))
    assert live.has_facts("anything", ())


def test_the_report_adds_up_the_measurements_and_keeps_judgment_and_facts_apart(tmp_path, monkeypatch) -> None:
    runs, judgments = tmp_path / "runs.jsonl", tmp_path / "judgments.jsonl"
    monkeypatch.setattr(live, "RUNS", runs)
    monkeypatch.setattr(live, "JUDGMENTS", judgments)

    def row(key, mode, tools, http, sql, wall, answer):
        return {"key": key, "mode": mode, "kind": "local", "turns_text": ["q"], "tools": tools, "tool_steps": len(tools), "http": http, "sql_queries": sql, "wall_s": wall, "answer": answer, "conflicts": []}

    lines = [row("B02", "off", ["tmdb_search"], 2, 0, 6.0, "Hampton Fancher e David Webb Peoples"), row("B02", "on", ["cinema_sql"], 0, 3, 5.0, "Hampton Fancher"),
             row("B12", "off", ["tmdb_search"], 2, 0, 6.0, "Hans Zimmer"), row("B12", "on", ["cinema_sql", "tmdb_search"], 2, 3, 9.0, "Hans Zimmer"), {"key": "B01", "mode": "on", "error": "Timeout"}]
    runs.write_text("".join(json.dumps(r) + "\n" for r in lines), encoding="utf-8")
    judgments.write_text(json.dumps({"key": "B02", "winner": "off", "on_errors": ["incomplete"], "off_errors": [], "reason": "r"}) + "\n", encoding="utf-8")

    data = live.report()
    s = data["summary"]
    assert s["questions"] == 2 and s["totals"]["off"] == {"http": 4, "tool_steps": 2, "sql_queries": 0, "wall_s": 12.0} and s["totals"]["on"] == {"http": 2, "tool_steps": 3, "sql_queries": 6, "wall_s": 14.0}
    assert s["cinema_used"] == 2 and s["judge"] == {"off": 1, "not judged": 1}
    assert s["facts"] == {"off": {"present": 2, "missing": 0}, "on": {"present": 1, "missing": 1}}  # B02 on misses Peoples: the mechanical check flags it, the judge agrees
    text = live.markdown(data)
    assert "| B02 |" in text and "CINEMA" in text and "Valutazione live" in text and "quattro cose diverse" in text
