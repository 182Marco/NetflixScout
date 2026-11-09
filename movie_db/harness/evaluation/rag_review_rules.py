"""The manual-review rules of the semantic battery, written down BEFORE the new run (FASE 19K). Pure functions; no model, no I/O.

Classes are fixed from the catalogue analysis of FASE 19J (docs/cinema_db/PROGRESS.md), not from any result of the new run:
- OPEN   : many legitimate answers.              Relevant if the top 3 contain at least two grades of 2 and no `0x`.
- SINGLE : one legitimate answer in the catalogue. Relevant if position 1 is graded 2 and the top 3 contain no `0x`.
- NOTE   : F08, relevant if the tool reported the contradiction note (the automatic check `note`).
- EMPTY  : S08, relevant if the result is empty with the expected note (the automatic checks `empty` and `note`).
- EXCLUDED: S06, outside the quantitative evaluation (the main One Piece page is hidden by a product decision of 2026-11-08); its grades are recorded, not counted.

Grades: 0, 1, 2, `0x` (a zero caused by a stated exclusion or filter), `?` (unknown title: never counts as a 2 and blocks a SINGLE verdict until resolved).
Thresholds: film 10 of 12 (original, unchanged). Series: the original is 9 of 12; with S06 outside the count the evaluable denominator is 11 and the threshold is
PENDING the owner's confirmation: `SERIES_THRESHOLD_ORIGINAL` and `SERIES_THRESHOLD_PROPOSED` are both reported, none is chosen here."""
from __future__ import annotations

from typing import Any

OPEN, SINGLE, NOTE, EMPTY, EXCLUDED = "open", "single", "note", "empty", "excluded"
CLASSES: dict[str, str] = {
    **{f"F{n:02d}": OPEN for n in range(1, 13)}, "F08": NOTE,
    "S01": SINGLE, "S02": OPEN, "S03": SINGLE, "S04": SINGLE, "S05": SINGLE, "S06": EXCLUDED, "S07": OPEN, "S08": EMPTY,
    "S09": OPEN, "S10": SINGLE, "S11": OPEN, "S12": OPEN,
}
THRESHOLD_FILM = (10, 12)
SERIES_THRESHOLD_ORIGINAL = (9, 12)
SERIES_THRESHOLD_PROPOSED = (9, 11)       # same absolute 9 and never looser than the original ratio (75 %): ceil(0.75 * 11) = 9; 8/11 (72.7 %) would be looser
GRADES = ("0", "1", "2", "0x", "?")


def verdict(case_id: str, votes: list[str] | None, checks: dict[str, bool] | None = None) -> bool | None:
    """True/False for a counted case, None when the case is outside the count or cannot be decided yet (unknown grade). `votes` = grades of positions 1-3."""
    kind = CLASSES[case_id]
    checks = checks or {}
    if kind == EXCLUDED:
        return None
    if kind == NOTE:
        return bool(checks.get("note"))
    if kind == EMPTY:
        return bool(checks.get("empty")) and bool(checks.get("note"))
    top = list(votes or [])[:3]
    if not top or any(v not in GRADES for v in top):
        raise ValueError(f"{case_id}: missing or invalid grades {top}")
    if kind == SINGLE:
        if top[0] == "?":
            return None
        return top[0] == "2" and "0x" not in top
    return top.count("2") >= 2 and "0x" not in top and ("?" not in top or top.count("2") >= 2)


def summarize(votes: dict[str, list[str]], checks: dict[str, dict[str, bool]]) -> dict[str, Any]:
    """Counts per kind with the denominator actually evaluable. Series thresholds are both reported; nothing is declared passed here."""
    out: dict[str, Any] = {}
    for kind, prefix in (("film", "F"), ("series", "S")):
        ids = [c for c in CLASSES if c.startswith(prefix)]
        counted = [c for c in ids if CLASSES[c] != EXCLUDED]
        results = {c: verdict(c, votes.get(c), checks.get(c)) for c in counted}
        out[kind] = {"cases": len(ids), "evaluable": len(counted), "undecided": sorted(c for c, v in results.items() if v is None),
                     "relevant": sum(1 for v in results.values() if v), "not_relevant": sorted(c for c, v in results.items() if v is False),
                     "excluded": sorted(c for c in ids if CLASSES[c] == EXCLUDED)}
    f, s = out["film"], out["series"]
    f["threshold"] = THRESHOLD_FILM
    f["met"] = None if f["undecided"] else f["relevant"] >= THRESHOLD_FILM[0]
    s["threshold_original"], s["threshold_proposed_pending_confirmation"] = SERIES_THRESHOLD_ORIGINAL, SERIES_THRESHOLD_PROPOSED
    s["met_original_9_of_12"] = None if s["undecided"] else s["relevant"] >= SERIES_THRESHOLD_ORIGINAL[0]
    s["met_proposed_9_of_11"] = None if s["undecided"] else s["relevant"] >= SERIES_THRESHOLD_PROPOSED[0]
    return out
