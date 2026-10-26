"""The blind evaluation of Phase 5: rules, saved scores and the key join cannot drift silently."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

PHASE5 = Path(__file__).resolve().parents[1] / "docs" / "qdrant_migration" / "phase5"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, PHASE5 / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_level_thresholds():
    m = _load("score_qualitative")
    assert [m.level(x) for x in (0, 0.29, 0.3, 0.69, 0.7, 1)] == [0, 0, 1, 1, 2, 2]
    assert m.facts_level(0) == 2 and m.facts_level(1) == 1 and m.facts_level(2) == 0


def test_avoid_level_penalises_any_clear_resemblance():
    m = _load("score_qualitative")
    assert m.avoid_level([0, 0, 0, 0, 0]) == 2
    assert m.avoid_level([0.5, 0, 0, 0, 0]) == 1
    assert m.avoid_level([1, 0, 0, 0, 0]) == 0
    assert m.avoid_level([0.5, 0.5, 0.5, 0.5, 0]) == 0  # mean 0.4


def test_saved_scores_match_their_hashes_and_the_judgments():
    for line in (PHASE5 / "qualitative_scores.sha256").read_text().splitlines():
        digest, _, name = line.partition("  ")
        assert hashlib.sha256((PHASE5 / name).read_bytes()).hexdigest() == digest, name
    m = _load("score_qualitative")
    data = json.loads((PHASE5 / "qualitative_judgments.json").read_text())
    saved = json.loads((PHASE5 / "qualitative_scores.json").read_text())["scores"]
    assert len(saved) == 23
    for case, entry in data["cases"].items():
        for label in "XYZ":
            expected = m.score_list(entry[label])
            assert {k: saved[case][label][k] for k in ("pertinenza", "vicinanza", "assenza", "fatti")} == {
                k: expected[k] for k in ("pertinenza", "vicinanza", "assenza", "fatti")}


def test_judgments_are_well_formed():
    data = json.loads((PHASE5 / "qualitative_judgments.json").read_text())
    assert "NOT a human" in data["evaluator"] and "Imperfect" in data["blindness"]
    for case, entry in data["cases"].items():
        for label in "XYZ":
            for key in ("r", "p", "n"):
                values = entry[label][key]
                assert values is None or (len(values) == 5 and set(values) <= {0, 0.5, 1})


def test_join_refuses_when_the_saved_scores_changed(tmp_path, monkeypatch):
    m = _load("join_key")
    (tmp_path / "qualitative_scores.json").write_text('{"scores": {}}')
    (tmp_path / "qualitative_scores.sha256").write_text(f"{hashlib.sha256(b'other').hexdigest()}  qualitative_scores.json\n")
    monkeypatch.setattr(m, "HERE", tmp_path)
    with pytest.raises(SystemExit, match="changed after the evaluation was saved"):
        m.main()
