from __future__ import annotations

from rag.FromQueryEmbeddingToRes.models import SearchMode
from rag.FromQueryEmbeddingToRes.retrieval_params import resolve_retrieval

DEFAULTS = {
    "search_mode": SearchMode.semantic,
    "k_largo": 10,
    "k_finale": 3,
    "fetch_k": 50,
    "genre_boost": 0.15,
    "rrf_costante": 60,
    "limits": {"k_finale": {"min": 1, "max": 10}},
}


def test_no_overrides_keeps_defaults():
    effective, overridden = resolve_retrieval(DEFAULTS, {"query": "x", "turn_id": "t"})
    assert overridden == {}
    assert effective["k_finale"] == 3 and effective["rrf_costante"] == 60
    assert "limits" not in effective


def test_k_finale_is_clamped_and_pools_stay_coherent():
    effective, overridden = resolve_retrieval(DEFAULTS, {"k_finale": 99})
    assert effective["k_finale"] == 10 and effective["k_largo"] == 10
    assert overridden == {"k_finale": 10}
    assert resolve_retrieval(DEFAULTS, {"k_finale": 0})[0]["k_finale"] == 1


def test_invalid_values_and_other_settings_are_ignored():
    for bad in ("tre", True, float("nan"), float("inf")):
        effective, overridden = resolve_retrieval(DEFAULTS, {"k_finale": bad})
        assert effective["k_finale"] == 3 and overridden == {}
    effective, overridden = resolve_retrieval(
        DEFAULTS, {"search_mode": "bm25", "k_largo": 50, "fetch_k": 100, "genre_boost": 0.4}
    )
    assert overridden == {} and effective["search_mode"] == SearchMode.semantic and effective["k_largo"] == 10


def test_defaults_are_not_mutated():
    snapshot = {**DEFAULTS, "limits": dict(DEFAULTS["limits"])}
    resolve_retrieval(DEFAULTS, {"k_finale": 5})
    assert DEFAULTS == snapshot
