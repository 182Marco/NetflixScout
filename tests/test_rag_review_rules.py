"""The manual-review rules fixed before the new battery. Synthetic grades only: the registered grades of review.md are never recomputed here."""
from __future__ import annotations

import pytest

from movie_db.harness.evaluation import rag_review_rules as R


def test_the_classes_cover_exactly_the_24_cases_of_the_battery_and_match_the_documented_analysis() -> None:
    import json
    from pathlib import Path
    ids = [c["id"] for c in json.loads((Path(R.__file__).parent / "rag_semantic_cases.json").read_text())["cases"]]
    assert sorted(R.CLASSES) == sorted(ids) and len(ids) == 24
    assert sorted(c for c, k in R.CLASSES.items() if k == R.SINGLE) == ["S01", "S03", "S04", "S05", "S10"]
    assert [c for c, k in R.CLASSES.items() if k == R.EXCLUDED] == ["S06"] and R.CLASSES["F08"] == R.NOTE and R.CLASSES["S08"] == R.EMPTY


def test_open_requests_keep_the_original_rule() -> None:
    assert R.verdict("F01", ["1", "2", "2"]) and R.verdict("F02", ["2", "2", "2"])
    assert not R.verdict("F09", ["2", "0", "1"]) and not R.verdict("S02", ["2", "1", "1"])
    assert not R.verdict("F10", ["2", "2", "0x"]) and not R.verdict("S07", ["0x", "2", "2"])        # a zero caused by an exclusion fails
    assert R.verdict("F03", ["2", "0", "2"])                                                         # a plain 0 does not
    assert not R.verdict("F04", ["2", "?", "1"])


def test_single_answer_requests_need_the_answer_first_and_no_exclusion_violation() -> None:
    assert R.verdict("S01", ["2", "1", "1"]) and R.verdict("S10", ["2", "1", "0"]) and R.verdict("S04", ["2", "0"])
    assert not R.verdict("S01", ["1", "2", "2"])                       # the right answer is not first
    assert not R.verdict("S03", ["2", "2", "0x"])                      # an exclusion/filter violation in the top 3
    assert R.verdict("S05", ["2", "1"])                                # fewer than three results are judged on what exists
    assert R.verdict("S01", ["?", "2", "2"]) is None                   # unknown first title: undecided, never a pass


def test_note_empty_and_excluded_cases() -> None:
    assert R.verdict("F08", ["1", "1", "1"], {"note": True}) and not R.verdict("F08", ["2", "2", "2"], {"note": False})
    assert R.verdict("S08", None, {"empty": True, "note": True}) and not R.verdict("S08", None, {"empty": True, "note": False})
    assert not R.verdict("S08", None, {"empty": False, "note": True})
    assert R.verdict("S06", ["2", "2", "2"]) is None


def test_invalid_or_missing_grades_are_refused() -> None:
    for bad in (None, [], ["3", "1", "1"], ["x"]):
        with pytest.raises(ValueError):
            R.verdict("F01", bad)


def _all(grade: list[str]) -> tuple[dict, dict]:
    votes = {c: list(grade) for c, k in R.CLASSES.items() if k in (R.OPEN, R.SINGLE)}
    checks = {"F08": {"note": True}, "S08": {"empty": True, "note": True}}
    return votes, checks


def test_the_summary_reports_the_evaluable_denominator_and_both_series_thresholds_without_choosing() -> None:
    votes, checks = _all(["2", "2", "2"])
    s = R.summarize(votes, checks)
    assert s["film"]["evaluable"] == 12 and s["film"]["relevant"] == 12 and s["film"]["threshold"] == (10, 12) and s["film"]["met"]
    assert s["series"]["cases"] == 12 and s["series"]["evaluable"] == 11 and s["series"]["excluded"] == ["S06"] and s["series"]["relevant"] == 11
    assert s["series"]["threshold_original"] == (9, 12) and s["series"]["threshold_proposed_pending_confirmation"] == (9, 11)
    assert s["series"]["met_original_9_of_12"] and s["series"]["met_proposed_9_of_11"]


def test_the_two_series_readings_can_differ_only_by_the_denominator_not_by_the_count() -> None:
    votes, checks = _all(["2", "2", "2"])
    for c in ("S02", "S07", "S09"):                                    # three open series cases fail
        votes[c] = ["1", "1", "1"]
    s = R.summarize(votes, checks)["series"]
    assert s["relevant"] == 8 and s["met_original_9_of_12"] is False and s["met_proposed_9_of_11"] is False and s["not_relevant"] == ["S02", "S07", "S09"]


def test_undecided_cases_block_any_pass_declaration() -> None:
    votes, checks = _all(["2", "2", "2"])
    votes["S01"] = ["?", "2", "2"]
    s = R.summarize(votes, checks)["series"]
    assert s["undecided"] == ["S01"] and s["met_original_9_of_12"] is None and s["met_proposed_9_of_11"] is None


def test_the_film_threshold_is_the_original_ten_of_twelve() -> None:
    votes, checks = _all(["2", "2", "2"])
    for c in ("F01", "F02"):
        votes[c] = ["0", "0", "0"]
    f = R.summarize(votes, checks)["film"]
    assert f["relevant"] == 10 and f["met"] is True
    votes["F03"] = ["0", "0", "0"]
    assert R.summarize(votes, checks)["film"]["met"] is False
