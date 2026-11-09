"""Offline tests: shard plan and resume of `embed`, payload/ids of `index`, filters and navigation of `retrieval` (in-memory Qdrant, fake embedder)."""
from __future__ import annotations

import numpy as np
import pytest
from qdrant_client import QdrantClient, models

from pipelines.wikipedia_series import embed as E
from pipelines.wikipedia_series import index as I
from tool.rag.series import retrieval as R


def _units(n: int, tokens: int = 10) -> list[E.Unit]:
    return [E.Unit(f"wp-{i}", "episode", f"testo {i}", f"h{i}", tokens) for i in range(n)]


class FakeClient:
    def __init__(self):
        self.calls = 0
        self.embeddings = self

    def create(self, *, model, input, dimensions, encoding_format):
        self.calls += 1
        rng = np.random.default_rng(len(input))
        data = [type("D", (), {"index": i, "embedding": rng.normal(size=dimensions).tolist()}) for i in range(len(input))]
        return type("R", (), {"data": data, "usage": type("U", (), {"total_tokens": sum(len(t) for t in input)})(), "_request_id": "r"})()


def test_shards_respect_input_and_token_limits():
    shards = E.make_shards(_units(300))
    assert [len(s) for s in shards] == [128, 128, 44]
    big = E.make_shards(_units(10, tokens=60_000))
    assert all(sum(u.tokens for u in s) <= E.REQUEST_MAX_TOKENS for s in big)
    assert sum(len(s) for s in big) == 10


def test_embed_resumes_without_repeating_requests(tmp_path):
    units = _units(300)
    c = FakeClient()
    r1 = E.run(c, units=units, directory=tmp_path, workers=2)
    assert c.calls == 3 and r1["requested_now"] == 3
    r2 = E.run(c, units=units, directory=tmp_path, workers=2)
    assert c.calls == 3 and r2["requested_now"] == 0 and r2["reused"] == 3
    (tmp_path / "shard_00001.npz").unlink()
    E.run(c, units=units, directory=tmp_path, workers=2)
    assert c.calls == 4
    assert E.load_all(units, tmp_path).shape == (300, E.DIMENSIONS)


def test_changed_text_invalidates_the_plan(tmp_path):
    units = _units(5)
    c = FakeClient()
    E.run(c, units=units, directory=tmp_path)
    changed = [E.Unit(u.unit_id, u.entity_type, u.text, u.text_sha256 + "x", u.tokens) for u in units]
    E.run(c, units=changed, directory=tmp_path)
    assert c.calls == 2


def test_budget_is_enforced(tmp_path):
    with pytest.raises(RuntimeError):
        E.run(FakeClient(), units=_units(2, tokens=60_000_000), directory=tmp_path, max_usd=1.0)


def test_point_ids_are_stable_and_distinct_from_films():
    assert I.point_id("wp-1") == I.point_id("wp-1") != I.point_id("wp-2")
    assert I.COLLECTION not in I.PROTECTED


# ---- retrieval over an in-memory collection
DIM = 8


def _vec(i: int) -> list[float]:
    v = np.zeros(DIM, dtype=np.float32)
    v[i % DIM] = 1.0
    return v.tolist()


def _mk(rid, et, title, i, **kw):
    p = {"record_id": rid, "entity_type": et, "title": title, "title_norm": R.norm(title), "original_title_norm": R.norm(kw.pop("original", "")),
         "default_search_eligible": kw.pop("eligible", True), "plot_text": kw.pop("plot", "trama " + title), "year": kw.pop("year", 2000),
         "wikipedia_url": f"https://it.wikipedia.org/wiki/{title}", **kw}
    return models.PointStruct(id=I.point_id(rid), vector=_vec(i), payload=p)


@pytest.fixture()
def index():
    c = QdrantClient(":memory:")
    c.create_collection("t", vectors_config=models.VectorParams(size=DIM, distance=models.Distance.COSINE))
    c.upsert("t", points=[
        _mk("s1", "series", "Alfa", 0, subtype="tv_series", country=["Italia"], cast="* Mario Rossi: x"),
        _mk("s2", "series", "Beta", 0, subtype="anime", eligible=False, original="Beta Original"),
        _mk("s3", "series", "Gamma", 1, subtype="tv_series", year=2010),
        _mk("e1", "episode", "Pilota", 0, series_id="s1", series_title="Alfa", season_number=1, episode_number=1),
        _mk("e2", "episode", "Secondo", 0, series_id="s1", series_title="Alfa", season_number=1, episode_number=2),
        _mk("e3", "episode", "Ritorno", 0, series_id="s3", series_title="Gamma", season_number=2, episode_number=1),
        _mk("t1", "tv_movie", "Film TV", 0),
        _mk("q1", "season", "Alfa – stagione 1", 0, series_id="s1", season_number=1),
    ])
    return R.SeriesIndex(client=c, collection="t")


def fake_embed(texts):
    return np.stack([np.asarray(_vec(0), dtype=np.float32) for _ in texts])


def test_search_is_bound_to_one_level_and_hides_mixed_media(index):
    out = R.search(index, fake_embed, R.SeriesSignals(positive_it="x", positive_en="x"), k=10)
    assert {i.entity_type for i in out.items} == {"series"}
    assert "s2" not in {i.record_id for i in out.items}          # default_search_eligible = false
    out = R.search(index, fake_embed, R.SeriesSignals(positive_it="x", positive_en="x", about_manga_or_original_work=True), k=10)
    assert "s2" in {i.record_id for i in out.items}
    out = R.search(index, fake_embed, R.SeriesSignals(level="tv_movie", positive_it="x", positive_en="x"), k=10)
    assert [i.record_id for i in out.items] == ["t1"]


def test_named_series_binds_episodes_and_unknown_series_returns_nothing(index):
    sg = R.SeriesSignals(level="episode", positive_it="x", positive_en="x", series_title="alfa")
    out = R.search(index, fake_embed, sg, k=10)
    assert {i.record_id for i in out.items} == {"e1", "e2"}
    sg.season_number, sg.episode_number = 1, 2
    assert [i.record_id for i in R.search(index, fake_embed, sg, k=10).items] == ["e2"]
    out = R.search(index, fake_embed, R.SeriesSignals(level="episode", positive_it="x", positive_en="x", series_title="Inesistente"), k=10)
    assert out.items == [] and out.notes["series_not_in_index"] == "Inesistente"


def test_year_country_and_subtype_filters(index):
    base = dict(positive_it="x", positive_en="x")
    assert [i.record_id for i in R.search(index, fake_embed, R.SeriesSignals(year_from=2005, **base), k=10).items] == ["s3"]
    assert [i.record_id for i in R.search(index, fake_embed, R.SeriesSignals(countries=["Italia"], **base), k=10).items] == ["s1"]
    assert [i.record_id for i in R.search(index, fake_embed, R.SeriesSignals(subtypes=["tv_series"], **base), k=10).items] == ["s1", "s3"]
    assert [i.record_id for i in R.search(index, fake_embed, R.SeriesSignals(cast_names=["Rossi"], **base), k=10).items] == ["s1"]


def test_titles_and_navigation(index):
    assert [i.record_id for i in index.find_titles("Beta Original")] == ["s2"]
    assert [i.episode_number for i in index.episodes_of("s1", 1)] == [1, 2]
    assert [i.record_id for i in index.seasons_of("s1")] == ["q1"]
    assert index.parent_of(index.episodes_of("s1")[0]).record_id == "s1"
    assert index.find_titles("   ") == []


def test_avoided_and_cited_titles_are_removed_and_parser_failure_is_noted(index):
    sg = R.SeriesSignals(positive_it="x", positive_en="x", avoid_titles=["Alfa"])
    assert "s1" not in {i.record_id for i in R.search(index, fake_embed, sg, k=10).items}

    def boom(_):
        raise RuntimeError("x")
    out = R.run("q", index=index, embed=fake_embed, parse=boom, k=3)
    assert out.notes["parser_failed"] == "RuntimeError" and out.items


def test_named_series_is_an_exact_lookup_that_reaches_mixed_media_pages(index):
    out = R.search(index, fake_embed, R.SeriesSignals(positive_it="x", positive_en="x", series_title="Beta"), k=5)
    assert [i.record_id for i in out.items] == ["s2"] and out.notes["mixed_media_pages"] == ["Beta"]
    out = R.search(index, fake_embed, R.SeriesSignals(positive_it="x", positive_en="x", series_title="Nessuna"), k=5)
    assert out.items == [] and out.notes["series_not_in_index"] == "Nessuna"


def test_listing_children_follows_the_numbering_without_vectors(index):
    sg = R.SeriesSignals(level="episode", positive_it="x", positive_en="x", series_title="Alfa", season_number=1, list_children=True)
    out = R.search(index, fake_embed, sg, k=1)
    assert [i.episode_number for i in out.items] == [1, 2] and out.notes["listing"]


def test_base_title_strips_the_disambiguation():
    assert R.base_title_norm("Lost (serie televisiva)") == "lost" and I.base_title_norm("Friends") == "friends"
    assert R.base_title_norm("Cobra (manga)") == "cobra"


def test_cited_title_with_a_disambiguation_is_removed(index):
    c = index.client
    c.upsert("t", points=[_mk("s9", "series", "Alfa (serie televisiva)", 0)])
    out = R.search(index, fake_embed, R.SeriesSignals(positive_it="x", positive_en="x", like_titles=["Alfa"]), k=10)
    assert not ({"s1", "s9"} & {i.record_id for i in out.items})
