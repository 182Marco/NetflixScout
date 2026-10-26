"""The Phase 5 protocol cannot drift silently: frozen cases, written thresholds, blind sheets."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

PHASE5 = Path(__file__).resolve().parents[1] / "docs" / "qdrant_migration" / "phase5"
PROTOCOL = PHASE5.parent / "protocol.md"


def _load():
    spec = importlib.util.spec_from_file_location("ab_phase5", PHASE5 / "ab.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["ab_phase5"] = module
    spec.loader.exec_module(module)
    return module


def test_frozen_cases_match_the_hash_recorded_before_measuring():
    recorded = (PHASE5 / "cases.sha256").read_text().splitlines()[0]
    digest, _, name = recorded.partition("  ")
    assert name == "cases.json"
    assert hashlib.sha256((PHASE5 / "cases.json").read_bytes()).hexdigest() == digest


def test_cases_cover_the_planned_categories():
    spec = json.loads((PHASE5 / "cases.json").read_text())
    cases = spec["cases"]
    assert len(cases) == 28 and len({c["id"] for c in cases}) == 28
    assert spec["k"] == 10 and spec["fetch_k"] == 50 and spec["text_repeat"] == 1
    categories = {c["category"] for c in cases}
    assert categories >= {"single_pos_neg", "positive_only", "negative_only", "multi_positive", "multi_negative",
                          "multi_both", "ambiguous_partial", "ambiguous_all", "absent_partial", "absent_all",
                          "no_references", "no_valid_reference", "constraints", "constraints_homonyms"}
    for case in cases:
        for ref in case["like"] + case["avoid"]:
            assert ref["expected_status"] in ("resolved", "ambiguous", "not_in_index")


def test_thresholds_in_the_code_are_the_ones_written_in_the_protocol():
    ab = _load()
    assert (ab.NEG_DROP_MEAN, ab.NEG_DROP_SHARE) == (0.02, 0.60)
    assert (ab.TEXT_MEAN_TOL, ab.TEXT_CASE_TOL, ab.POS_MEAN_TOL, ab.POS_REF_TOL) == (0.02, 0.05, 0.02, 0.05)
    text = PROTOCOL.read_text(encoding="utf-8")
    assert "calo medio del coseno medio ai negativi >= 0,02" in text and ">= 60% di quei casi" in text
    assert "nessuna variante migliora abbastanza la baseline" in text
    assert "recall@10 >= 0,95" in text


def test_measurement_refuses_when_a_frozen_file_changed(tmp_path):
    ab = _load()
    (tmp_path / "cases.json").write_text('{"cases": []}')
    (tmp_path / "base").mkdir()
    (tmp_path / "base" / "q01.vec.npy").write_bytes(b"vec")
    (tmp_path / "cases.sha256").write_text(
        f"{hashlib.sha256(b'{}').hexdigest()}  cases.json\n")  # does not match
    with pytest.raises(SystemExit, match="differs from the hash"):
        ab.verify_frozen(tmp_path, tmp_path / "base")
    (tmp_path / "cases.sha256").write_text(
        f"{hashlib.sha256((tmp_path / 'cases.json').read_bytes()).hexdigest()}  cases.json\n"
        f"{hashlib.sha256(b'vec').hexdigest()}  baseline/q01.vec.npy\n")
    ab.verify_frozen(tmp_path, tmp_path / "base")  # unchanged -> accepted
    (tmp_path / "base" / "q01.vec.npy").write_bytes(b"other")
    with pytest.raises(SystemExit):
        ab.verify_frozen(tmp_path, tmp_path / "base")


def test_blind_sheets_do_not_reveal_the_variants():
    sheets = (PHASE5 / "qualitative_sheets.md").read_text(encoding="utf-8")
    for word in ("average_vector", "best_score", "Variante A", "Variante B", "Variante C"):
        assert word not in sheets
    key = json.loads((PHASE5 / "qualitative_key.json").read_text())
    assert key["keys"] and all(sorted(v.values()) == ["X", "Y", "Z"] for v in key["keys"].values())
