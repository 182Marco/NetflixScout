"""Pure parts of the calibration script, and its refusal to spend money without authorization."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / "docs/qdrant_migration/catalog/calibration/calibrate.py"
spec = importlib.util.spec_from_file_location("calibrate", PATH)
cal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cal)


def test_classes():
    o = [f"c{i}" for i in range(10)]
    assert cal.classify_query(o, o)["class"] == "unchanged"
    e = ["tmdb:movie:1"] + o[:9]
    got = cal.classify_query(o, e)
    assert got["class"] == "intrusion" and got["entered"] == ["tmdb:movie:1"] and got["left"] == ["c9"]
    assert cal.classify_query(o, e, "tmdb:movie:1")["class"] == "target_found"
    assert cal.classify_query(o, e, "tmdb:movie:1")["rank_in_e"] == 1


def test_rules():
    reg = [
        {"id": "s1", "type": "side", "top_o": ["a", "b"], "top_e": ["tmdb:1", "a"], "class": "intrusion"},
        {"id": "s2", "type": "side", "top_o": ["a", "c"], "top_e": ["a", "c"], "class": "unchanged"},
        {"id": "t1", "type": "target", "kind": "new", "top_o": [], "top_e": ["tmdb:1"], "rank_in_o": None, "rank_in_e": 1},
        {"id": "t2", "type": "target", "kind": "shared", "top_o": ["a"], "top_e": ["a"], "rank_in_o": 1, "rank_in_e": 1},
    ]
    undecided = cal.apply_rules(reg)
    assert undecided["R1"]["ok"] is None and undecided["R2"]["ok"] is True and undecided["R3"]["ok"] is True
    bad = cal.apply_rules([{**r, "tmdb_relevance": 0} if r["id"] == "s1" else r for r in reg], {"s1": "cmu_migliore"})
    assert bad["R1"]["ok"] is False
    assert cal.apply_rules(reg, {"s1": "pari"})["R1"]["ok"] is True


def test_paid_step_refuses_without_authorization(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv(cal.AUTH_ENV, raising=False)
    q = tmp_path / "q.json"
    q.write_text(json.dumps([{"text": "x"}]))
    assert cal.main(["embed-queries", "--queries", str(q), "--out", str(tmp_path / "o.json")]) == 2
    assert not (tmp_path / "o.json").exists()


def test_plan_runs_offline(capsys):
    assert cal.main(["plan"]) == 0 and "PAID" in capsys.readouterr().out
