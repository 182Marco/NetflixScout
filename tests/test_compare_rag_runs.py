"""Offline tests of the run comparison used to decide which manual-review cells must be graded again."""
from __future__ import annotations

from movie_db.harness.evaluation.compare_rag_runs import compare


def row(*titles, valid=True):
    return {"items": [{"title": t} for t in titles], "grade": {"valid": valid}}


def test_identical_runs_need_no_regrading() -> None:
    old = {"F01": row("A", "B", "C", "D"), "S01": row("X", "Y", "Z")}
    out = compare(old, {k: dict(v) for k, v in old.items()})
    assert out["cells_to_regrade"] == [] and out["unchanged_cells"] == 6 and {c["status"] for c in out["cases"].values()} == {"IDENTICAL"}


def test_only_the_positions_whose_title_changed_are_regraded() -> None:
    out = compare({"F02": row("A", "B", "C")}, {"F02": row("A", "X", "C", "Q")})
    assert out["cells_to_regrade"] == [["F02", 2]] and out["unchanged_cells"] == 2 and out["cases"]["F02"]["status"] == "CHANGED"


def test_a_reordering_counts_as_a_change_and_positions_four_and_five_do_not_matter() -> None:
    out = compare({"F03": row("A", "B", "C", "D", "E")}, {"F03": row("B", "A", "C", "Z", "Y")})
    assert out["cells_to_regrade"] == [["F03", 1], ["F03", 2]]


def test_fewer_or_more_results_and_missing_cases() -> None:
    out = compare({"S04": row("A", "B"), "S08": row()}, {"S04": row("A"), "S09": row("N")})
    assert out["cells_to_regrade"] == [["S04", 2]] and out["missing"] == ["S08"] and out["new_only"] == ["S09"]
    assert out["cases"]["S08"]["status"] == "MISSING"
