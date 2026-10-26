"""The parity metrics (recall, ties vs significant differences) behave as protocol.md defines them."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "docs" / "qdrant_migration" / "phase4" / "parity.py"


def _load():
    spec = importlib.util.spec_from_file_location("parity_phase4", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["parity_phase4"] = module
    spec.loader.exec_module(module)
    return module


def _sim(table):
    return lambda i: table[i]


def test_recall():
    m = _load()
    assert m.recall(["a", "b", "c"], ["a", "c", "z"], 3) == 2 / 3
    assert m.recall(["a", "b", "c"], ["a", "c", "z"], 1) == 1.0


def test_identical_lists_have_no_differences():
    m = _load()
    out = m.compare(["a", "b", "c"], ["a", "b", "c"], 3, _sim({"a": 0.9, "b": 0.8, "c": 0.7}))
    assert out == {"overlap": 1.0, "set_ties": 0, "set_significant": 0, "inversion_ties": 0, "inversion_significant": 0}


def test_a_swap_between_equal_similarities_is_a_tie():
    m = _load()
    sim = _sim({"a": 0.9, "b": 0.8, "x": 0.7, "y": 0.7 - 5e-5})  # difference below the 1e-4 tolerance
    out = m.compare(["a", "b", "x"], ["a", "b", "y"], 3, sim)
    assert (out["set_ties"], out["set_significant"]) == (1, 0)


def test_a_swap_between_different_similarities_is_significant():
    m = _load()
    sim = _sim({"a": 0.9, "b": 0.8, "x": 0.7, "y": 0.6})
    out = m.compare(["a", "b", "x"], ["a", "b", "y"], 3, sim)
    assert (out["set_ties"], out["set_significant"]) == (0, 1)  # one swap, counted once (not per element)
    assert out["overlap"] == 2 / 3


def test_inversions_split_by_tolerance():
    m = _load()
    sim = _sim({"a": 0.9, "b": 0.9 - 5e-5, "c": 0.5})
    assert m.compare(["a", "b"], ["b", "a"], 2, sim)["inversion_ties"] == 1
    sim = _sim({"a": 0.9, "b": 0.5})
    assert m.compare(["a", "b"], ["b", "a"], 2, sim)["inversion_significant"] == 1


def test_thresholds_are_the_ones_fixed_in_the_protocol():
    m = _load()
    assert (m.R10_MIN, m.R50_MIN, m.TOL) == (0.95, 0.90, 1e-4)
    text = (SCRIPT.parents[1] / "protocol.md").read_text(encoding="utf-8")
    assert ">= 0,95" in text and ">= 0,90" in text and "1e-4" in text
