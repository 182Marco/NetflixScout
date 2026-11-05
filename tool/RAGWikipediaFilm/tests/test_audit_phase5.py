"""Phase 5 audit helpers: sample determinism, the doubtful table and the Wilson interval. Data-dependent tests skip without data."""
from __future__ import annotations

import pytest

from tool.RAGWikipediaFilm.audit import doubtful_review as DR
from tool.RAGWikipediaFilm.audit import sample_findings as SF
from tool.RAGWikipediaFilm.audit import sample_review as SR

HAS_DATA = (SR.ROOT / "data/audit/classification.jsonl").exists() and (SR.ROOT / "data/processed/films.jsonl").exists()
needs_data = pytest.mark.skipif(not HAS_DATA, reason="local audit data not available")


def test_wilson_interval_contains_the_estimate_and_zero_is_one_sided():
    lo, hi = SF.wilson(1, 60)
    assert lo < 1 / 60 < hi
    assert SF.wilson(0, 40)[0] == 0.0 and 0.05 < SF.wilson(0, 40)[1] < 0.1


def test_a_full_census_has_no_sampling_error():
    out = SF.summary()["other"]
    assert out["ci95_pct"][0] == out["ci95_pct"][1] == out["rate"]


def test_every_reviewed_decision_is_valid():
    assert set(DR.D) == set(range(71))
    assert {d for _, d, _, _ in DR.D.values()} <= {DR.INC, DR.EXC, DR.HOLD}
    assert {c for _, _, c, _ in DR.D.values()} <= {"alta", "media", "bassa"}


@needs_data
def test_sample_is_deterministic_and_inside_the_population():
    cl, _ = SR.load()
    a, b = SR.draw(cl), SR.draw(cl)
    assert {k: [r["film_id"] for r in v] for k, v in a.items()} == {k: [r["film_id"] for r in v] for k, v in b.items()}
    pop = {r["film_id"] for r in SR.population(cl)}
    assert pop >= {r["film_id"] for v in a.values() for r in v}
    assert sum(len(v) for v in a.values()) == 233


@needs_data
def test_doubtful_table_matches_the_classification():
    rows = DR.table()
    assert len(rows) == 71 and len({r["film_id"] for r in rows}) == 71


# ---- Phase 6 decision tables ----
from tool.RAGWikipediaFilm.audit import decisions as DC  # noqa: E402


def test_decision_words_and_confidences_are_valid():
    ok = {DC.INC, DC.EXC, DC.HOLD}
    assert {v[0] for v in DC.DOUBTFUL_IDX.values()} <= ok and {v[0] for v in DC.HYBRIDS.values()} <= ok
    assert {v[0] for v in DC.REINSTATE.values()} <= ok
    assert {v[1] for v in DC.HYBRIDS.values()} | {v[1] for v in DC.DOUBTFUL_IDX.values()} <= {"alta", "media", "bassa"}
    assert len(DC.HYBRIDS) == 46 and len(DC.DOUBTFUL_IDX) == 27


@needs_data
def test_decision_tables_match_the_data_and_do_not_overlap():
    rev, hy = DC.revised_table(), DC.hybrid_table()
    assert len(rev) == 27 and len(hy) == 46
    assert not {r["film_id"] for r in rev} & {r["film_id"] for r in hy}
    assert len(DC.reinstate_table()) == len(DC.REINSTATE)
