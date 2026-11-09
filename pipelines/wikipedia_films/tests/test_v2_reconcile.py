"""Phase 7: reuse/assembly of vectors for the v2 collection (synthetic) and the reconciled decision manifest (real files, skipped if absent)."""
from __future__ import annotations

import json

import numpy as np
import pytest

from pipelines.wikipedia_films.audit import reconcile as R
from pipelines.wikipedia_films.indexing import settings as S
from pipelines.wikipedia_films.indexing import v2 as V
from pipelines.wikipedia_films.indexing.units import units_for


def film(fid, text):
    return {"film_id": fid, "synopsis": text}


def test_unchanged_text_reuses_the_old_vector_and_changed_text_needs_a_new_one():
    a, b = units_for(film("Q1", "Uno.")), units_for(film("Q2", "Due nuovo."))
    old = {(a[0].film_id, a[0].text_sha256): np.ones(4, dtype=np.float32), ("Q2", "vecchio-hash"): np.zeros(4, dtype=np.float32)}
    units = a + b
    reuse, missing = V.split_reuse(units, old)
    assert (reuse, missing) == ([0], [1])
    out = V.assemble(units, old, {"Q2#0": np.full(4, 2, dtype=np.float32)})
    assert out.tolist() == [[1] * 4, [2] * 4]


def test_the_v2_builder_refuses_the_old_collections():
    assert S.COLLECTION_V2 != S.COLLECTION
    S.assert_own_collection(S.COLLECTION_V2)
    with pytest.raises(SystemExit):
        S.assert_own_collection("netflix_scout")
    with pytest.raises(SystemExit):
        S.assert_own_collection("qualcosa_di_altro")


HAS = (R.ROOT / "audit/exclusions.json").exists() and (R.ROOT / "audit/decisions.json").exists() and (R.ROOT / "data/processed/films.jsonl").exists()


@pytest.mark.skipif(not HAS, reason="audit data not available")
def test_every_record_gets_exactly_one_decision_and_the_counts_are_the_approved_ones():
    out = R.reconcile()
    m, plan = out["manifest"], out["plan"]
    ids = [r["film_id"] for r in m["records"]]
    assert len(ids) == len(set(ids)) == m["records_decided"]
    assert m["decisions"] == {"exclude": 284, "include_verified": 28, "include_unverified": 65}
    assert m["from_259_kept_excluded"] == 251 and m["reinstated_from_259"] == {"verified": 4, "unverified": 4}
    assert not set(plan["reinstate"]) & {e["film_id"] for e in plan["extra_exclude"]}
