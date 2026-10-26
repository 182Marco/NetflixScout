from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

spec = importlib.util.spec_from_file_location("cmp", Path(__file__).resolve().parents[1] / "docs/qdrant_migration/rebuild/compare_indexes.py")
cmp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cmp)


def pt(i, vec, **payload):
    v = np.asarray(vec, dtype=float)
    return {"id": f"u{i}", "payload": {"legacy_id": i, "document": "d", **payload}, "vector": v / np.linalg.norm(v)}


def test_identical_indexes():
    a = {"x": pt("x", [1, 0]), "y": pt("y", [0, 1], title="T")}
    r = cmp.compare(a, {k: dict(v) for k, v in a.items()})
    assert r["identical_ids_and_payloads"] and r["cosine"]["min"] > 0.9999 and not r["issues"]


def test_differences_are_reported():
    a = {"x": pt("x", [1, 0]), "y": pt("y", [0, 1], title="T"), "z": pt("z", [1, 1])}
    b = {"x": pt("x", [1, 0.2]), "y": pt("y", [0, 1], title="OTHER"), "w": pt("w", [1, 1])}
    r = cmp.compare(a, b)
    assert r["only_in_a"] == 1 and r["only_in_b"] == 1 and r["issues"]["payload"] == 1
    assert not r["identical_ids_and_payloads"] and r["cosine"]["below_0.9999"] >= 1


def test_zero_or_wrong_dimension_vectors_are_flagged():
    a = {"x": pt("x", [1, 0, 0])}
    b = {"x": pt("x", [1, 0])}
    assert cmp.compare(a, b)["issues"]["dimension"] == 1
