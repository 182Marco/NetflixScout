"""Reference resolution and steered search, on controlled vectors (in-memory Qdrant, no network)."""
from __future__ import annotations

import numpy as np
import pytest

from tool.rag.FromQueryEmbeddingToRes import vectorstore
from tool.rag.FromQueryEmbeddingToRes.references import (
    ReferenceInput, ReferenceSet, drop_references, resolve_reference, resolve_references)
from tool.rag.FromQueryEmbeddingToRes.store import StorePoint
from tool.rag.FromQueryEmbeddingToRes.store.base import IndexMeta
from tool.rag.FromQueryEmbeddingToRes.store.collection import QdrantCollection
from tool.rag.FromQueryEmbeddingToRes.store.qdrant_store import QdrantStore, open_client

DIM = 6


def _vec(*head):
    v = np.zeros(DIM, dtype=np.float32)
    v[: len(head)] = head
    return v.tolist()


def _p(i, vec, title, year, movie_id, genres="Drama"):
    meta = {"title": title, "movie_id": movie_id, "genres": genres, "source": "plots"}
    if year is not None:
        meta["release_year"] = str(year)
    return StorePoint(id=f"p{i}", vector=vec, document=f"plot {title}", metadata=meta)


# axis 0 = sci-fi space, axis 1 = romance, axis 2 = horror, axis 3 = crime
POINTS = [
    _p(0, _vec(1, 0, 0, 0), "Star Hero", 1999, "m0", "Science Fiction"),
    _p(1, _vec(0.9, 0.2, 0, 0), "Space Opera", 2001, "m1", "Science Fiction"),
    _p(2, _vec(0.8, 0, 0.5, 0), "Space Horror", 1980, "m2", "Science Fiction; Horror"),
    _p(3, _vec(0.2, 1, 0, 0), "Love Story", 1950, "m3", "Romance"),
    _p(4, _vec(0, 0.1, 1, 0), "Dark House", 1975, "m4", "Horror"),
    _p(5, _vec(0, 0, 0.9, 0.2), "Dark House", 2005, "m5", "Horror"),   # remake: same title
    _p(6, _vec(0, 0, 0, 1), "Crime Boss", 1972, "m6", "Crime"),
    _p(7, _vec(0, 0, 0.1, 0.9), "Crime Boss", None, "m7", "Crime"),     # same title, unknown year
    _p(8, _vec(0.7, 0.7, 0, 0), "Moon Romance", 2009, "m8", "Romance"),
    _p(9, _vec(0.3, 0, 0, 0.9), "Heist", 1995, "m9", "Crime"),
]


@pytest.fixture()
def col():
    client = open_client("memory")
    store = QdrantStore(client, "t", IndexMeta("m", DIM))
    store.create()
    store.upsert(POINTS)
    return QdrantCollection(store, exact=True)


def _refs(col, like=(), avoid=(), **kw):
    return resolve_references(col.store, [ReferenceInput(*r) if isinstance(r, tuple) else r for r in like],
                              [ReferenceInput(*r) if isinstance(r, tuple) else r for r in avoid], **kw)


# ---- resolution rules
def test_unique_title_resolves_with_or_without_year(col):
    r = resolve_reference(col.store, ReferenceInput("star hero"), "positive")
    assert (r.status, r.movie_id, r.source) == ("resolved", "m0", "index") and len(r.vector) == DIM
    assert resolve_reference(col.store, ReferenceInput("Star Hero", 1999), "positive").status == "resolved"
    assert resolve_reference(col.store, ReferenceInput("Star Hero", 2000), "positive").status == "resolved"  # +-1


def test_year_outside_the_window_is_not_a_different_film_of_the_same_title(col):
    r = resolve_reference(col.store, ReferenceInput("Star Hero", 2010), "positive")
    assert r.status == "not_in_index" and r.vector is None
    assert [c["title"] for c in r.candidates] == ["Star Hero"]  # reported, never used


def test_homonyms_need_a_year_and_the_closest_unique_wins(col):
    amb = resolve_reference(col.store, ReferenceInput("Dark House"), "positive")
    assert amb.status == "ambiguous" and amb.vector is None and len(amb.candidates) == 2
    one = resolve_reference(col.store, ReferenceInput("Dark House", 2005), "positive")
    assert (one.status, one.movie_id) == ("resolved", "m5")
    assert resolve_reference(col.store, ReferenceInput("Dark House", 1976), "positive").movie_id == "m4"


def test_two_equally_close_years_stay_ambiguous(col):
    store = col.store
    store.upsert([_p(20, _vec(0, 0, 0, 0, 1), "Twin", 2000, "t1"), _p(21, _vec(0, 0, 0, 0, 0, 1), "Twin", 2002, "t2")])
    assert resolve_reference(store, ReferenceInput("Twin", 2001), "positive").status == "ambiguous"
    assert resolve_reference(store, ReferenceInput("Twin", 2000), "positive").movie_id == "t1"


def test_missing_and_empty_titles_are_not_in_index(col):
    assert resolve_reference(col.store, ReferenceInput("Interstellar"), "positive").status == "not_in_index"
    assert resolve_reference(col.store, ReferenceInput("   "), "negative").status == "not_in_index"


def test_limits_mark_the_extra_references(col):
    s = _refs(col, like=[("Star Hero",), ("Space Opera",), ("Love Story",), ("Heist",)], max_positive=2)
    assert [e.status for e in s.entries] == ["resolved", "resolved", "ignored_over_limit", "ignored_over_limit"]


def test_trace_never_exposes_vectors(col):
    s = _refs(col, like=[("Star Hero",)], avoid=[("Dark House",)])
    trace = s.trace()
    for entry in trace["references"]:
        assert "vector" not in entry and not any(isinstance(v, list) and v and isinstance(v[0], float) for v in entry.values())
    assert s.trace()["references"][1]["status"] == "ambiguous"


# ---- exclusion rules (user decision: same-title films are excluded too)
def test_resolved_reference_excludes_its_homonyms_and_traces_them(col):
    s = _refs(col, avoid=[("Dark House", 1975)])
    assert s.excluded_movie_ids() == ["m4", "m5"]
    assert [x["movie_id"] for x in s.trace()["excluded_same_title"]] == ["m5"]


def test_ambiguous_reference_excludes_nothing_by_title(col):
    s = _refs(col, avoid=[("Dark House",)])
    assert s.excluded_movie_ids() == [] and not s.active
    rows = [{"movie_id": "m4", "title": "Dark House", "release_year": "1975"}]
    assert drop_references(list(rows), s) == rows


def test_missing_reference_excludes_by_exact_title_and_year_when_known(col):
    s = _refs(col, like=[("Interstellar", 2014)])
    rows = [{"movie_id": "x1", "title": "Interstellar", "release_year": "2014"},
            {"movie_id": "x2", "title": "Interstellar", "release_year": "1999"},
            {"movie_id": "x3", "title": "The Interstellar Hotel", "release_year": "2014"}]
    kept = drop_references(rows, s)
    assert [r["movie_id"] for r in kept] == ["x2", "x3"] and s.removed[0]["reason"] == "reference_title"
    s2 = _refs(col, like=[("Interstellar",)])
    assert [r["movie_id"] for r in drop_references(list(rows), s2)] == ["x3"]


def test_guard_removes_a_reference_that_a_branch_returned(col):
    s = _refs(col, like=[("Star Hero",)])
    rows = [{"movie_id": "m0", "title": "Star Hero", "release_year": "1999"},
            {"movie_id": "m1", "title": "Space Opera", "release_year": "2001"}]
    assert [r["movie_id"] for r in drop_references(rows, s)] == ["m1"]


# ---- steered search
def _search(col, query_vec, refs=None, monkeypatch=None, **kw):
    vectorstore.embed = lambda texts, backend=None, model=None: np.array([query_vec], dtype=np.float32)
    return vectorstore.search(col, "domanda", kw.pop("k", 6), backend="local", model="m", references=refs, **kw)


@pytest.fixture(autouse=True)
def _restore_embed():
    original = vectorstore.embed
    yield
    vectorstore.embed = original


def test_no_references_is_exactly_the_plain_search(col):
    q = _vec(0.6, 0.6, 0, 0)
    plain = _search(col, q)
    for refs in (None, _refs(col), _refs(col, like=[("Interstellar",)]), _refs(col, like=[("Dark House",)])):
        again = _search(col, q, refs)
        assert [r["id"] for r in again] == [r["id"] for r in plain]
        assert [r["score"] for r in again] == pytest.approx([r["score"] for r in plain])


def test_average_vector_steers_towards_positives_and_away_from_negatives(col):
    q = _vec(0.6, 0.6, 0, 0)  # halfway between sci-fi and romance
    plain = [r["title"] for r in _search(col, q)]
    titles = [r["title"] for r in _search(col, q, _refs(col, like=[("Star Hero",)], avoid=[("Love Story",)]))]
    assert "Love Story" not in titles and "Star Hero" not in titles  # references never returned
    assert titles.index("Space Opera") < titles.index("Moon Romance")
    assert plain != titles


def test_best_score_demotes_what_is_closer_to_a_negative_than_to_any_positive(col):
    """best_score compares the best positive with the best negative: a candidate that is very close
    to ANY positive (the text vector counts) is not penalised by a negative, unlike average_vector."""
    col.store.upsert([_p(30, _vec(0.1, 1, 0, 0), "Love Story Too", 1951, "m30", "Romance")])
    q = _vec(0.6, 0.6, 0, 0)
    refs = _refs(col, like=[("Star Hero",)], avoid=[("Love Story",)], strategy="best_score")
    titles = [r["title"] for r in _search(col, q, refs, k=10)]
    assert "Love Story" not in titles and "Star Hero" not in titles
    assert titles.index("Space Opera") < titles.index("Love Story Too")  # nearer a negative than a positive
    assert titles.index("Moon Romance") < titles.index("Love Story Too")  # near the text vector: kept


def test_reference_and_its_homonym_never_appear(col):
    refs = _refs(col, avoid=[("Dark House", 1975)], like=[("Star Hero",)])
    got = _search(col, _vec(0, 0, 1, 0.1), refs, k=10)
    assert "Dark House" not in [r["title"] for r in got]
    assert {"m4", "m5", "m0"}.isdisjoint({r["movie_id"] for r in got})


def test_constraints_still_apply_to_a_steered_search(col):
    refs = _refs(col, like=[("Star Hero",)])
    got = _search(col, _vec(0.6, 0.6, 0, 0), refs, k=10, excluded_genres=["Horror"])
    assert got and not any("Horror" in r["genres"] for r in got)
    boosted = _search(col, _vec(0.6, 0.6, 0, 0), refs, k=10, genres=["Romance"], genre_boost=1.0, fetch_k=10)
    assert boosted[0]["genres"] == "Romance"


def test_text_repeat_weights_the_text_against_the_references(col):
    q = _vec(0, 0, 0, 1)  # crime text
    light = _search(col, q, _refs(col, like=[("Star Hero",)], text_repeat=1))
    heavy = _search(col, q, _refs(col, like=[("Star Hero",)], text_repeat=5))
    assert heavy[0]["genres"] == "Crime"
    assert [r["id"] for r in light] != [r["id"] for r in heavy]


def test_negative_only_still_has_the_text_as_positive(col):
    got = _search(col, _vec(0.6, 0.6, 0, 0), _refs(col, avoid=[("Love Story",)]))
    assert got and "Love Story" not in [r["title"] for r in got]


def test_a_collection_that_cannot_recommend_refuses_reference_search(col):
    class NoRecommend:
        def query(self, **kw):
            raise AssertionError("not reached")

    with pytest.raises(RuntimeError, match="can `recommend`"):
        vectorstore.embed = lambda texts, backend=None, model=None: np.array([_vec(1)], dtype=np.float32)
        vectorstore.search(NoRecommend(), "q", 3, backend="local", model="m", references=_refs(col, like=[("Star Hero",)]))


def test_reference_config_defaults():
    from app import CONFIG
    ref = CONFIG["rag"]["reference"]
    assert ref["enabled"] is True and ref["strategy"] == "best_score"
    assert (ref["max_positive"], ref["max_negative"], ref["text_repeat"]) == (2, 2, 1)


def test_empty_reference_set_dataclass():
    s = ReferenceSet(entries=[])
    assert not s.active and s.positives() == [] and s.negatives() == [] and s.excluded_movie_ids() == []
