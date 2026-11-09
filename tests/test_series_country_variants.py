"""The `country` filter of the series retriever matches every payload spelling of a country (offline; the real-collection check is separate and read-only)."""
from __future__ import annotations

from tool.rag.series.retrieval import SeriesIndex, SeriesSignals
from tool.rag.series.retrieval.countries import SPELLINGS, country_variants


def test_a_country_without_variants_is_unchanged():
    assert country_variants(["Italia"]) == ["Italia"]
    assert country_variants(["Giappone", "Francia"]) == ["Giappone", "Francia"]
    assert country_variants([]) == []


def test_any_spelling_of_the_united_states_reaches_all_of_them():
    full = set(SPELLINGS[0])
    for name in ("Stati Uniti", "Stati Uniti d'America", "USA", "usa", "stati uniti"):
        got = country_variants([name])
        assert full <= set(got)
        assert got[0] == name                      # the requested spelling stays first
        assert len(got) == len(set(got))           # each once


def test_the_united_kingdom_and_thailand_groups_and_mixed_requests():
    assert {"Regno Unito", "Regno unito", "UK"} == set(country_variants(["Regno Unito"]))
    assert "Gran Bretagna" not in country_variants(["Regno Unito"]) and country_variants(["Gran Bretagna"]) == ["Gran Bretagna"]
    assert {"Thailandia", "Tailandia"} == set(country_variants(["Tailandia"]))
    mixed = country_variants(["Italia", "USA"])
    assert mixed[0] == "Italia" and set(SPELLINGS[0]) <= set(mixed)


def test_groups_do_not_overlap_and_keep_distinct_countries_apart():
    seen = [s for g in SPELLINGS for s in g]
    assert len(seen) == len(set(seen))
    assert "Germania Ovest" not in country_variants(["Germania"])
    assert "Giappone" not in country_variants(["Stati Uniti"])


def test_the_positive_filter_uses_the_variants_only_for_series_and_tv_movies():
    index = SeriesIndex.__new__(SeriesIndex)
    def country_values(level):
        flt = index.positive_filter(SeriesSignals(level=level, positive_it="x", positive_en="x", countries=["Stati Uniti"]))
        conds = [c for c in flt.must if getattr(c, "key", None) == "country"]
        return set(conds[0].match.any) if conds else None
    assert set(SPELLINGS[0]) <= country_values("series")
    assert set(SPELLINGS[0]) <= country_values("tv_movie")
    assert country_values("episode") is None       # unchanged: the country filter never applied to seasons and episodes
