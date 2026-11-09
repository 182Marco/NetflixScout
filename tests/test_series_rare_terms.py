"""FASE 19H: the parser's `rare_terms` of the series retriever become a hard full-text filter, so a term that is not a word of the user's request (a translation,
an invention) must never reach it. Offline. The inputs of the S11 case are the signals recorded in FASE 19G (`rare_terms=['ferro']` for an English request);
no parser output that was never observed is used."""
from __future__ import annotations

import numpy as np
import pytest
from qdrant_client import QdrantClient, models

from tool.rag.series import retrieval as R
from tool.rag.series.retrieval.text import verified_rare_terms
from test_series_rag import DIM, _mk, _vec, make_tool

S11 = "A fantasy series about noble families fighting for an iron throne"
S05 = "Un film per la televisione sugli ultimi giorni del magistrato Paolo Borsellino prima della strage di via D'Amelio"


def kept(terms, request):
    return verified_rare_terms(terms, request)[0]


def dropped(terms, request):
    return verified_rare_terms(terms, request)[1]


def test_the_recorded_s11_translation_is_dropped_and_the_recorded_s05_name_is_kept() -> None:
    assert verified_rare_terms(["ferro"], S11) == ([], ["ferro"])
    assert verified_rare_terms(["Paolo Borsellino"], S05) == (["Paolo Borsellino"], [])


def test_a_word_of_the_request_is_kept_whatever_its_case_or_accents() -> None:
    assert kept(["botola"], "L'episodio con la botola nella giungla") == ["botola"]
    assert kept(["BOTOLA"], "una botola") == ["BOTOLA"]
    assert kept(["perche"], "Perché?") == ["perche"] and kept(["Caffè"], "il caffe di Hawkins") == ["Caffè"]


def test_a_term_that_is_not_in_the_request_is_dropped_in_italian_and_in_english() -> None:
    assert dropped(["isola"], "a survivors story on an island") == ["isola"]       # translation of "island"
    assert dropped(["trono"], "a fantasy about an iron throne") == ["trono"]
    assert dropped(["Hawkins"], "una serie sugli anni ottanta") == ["Hawkins"]
    assert kept(["Hawkins"], "a series set in Hawkins") == ["Hawkins"]


def test_inflected_forms_of_the_same_word_are_kept_but_other_words_are_not() -> None:
    assert kept(["sopravvissuto"], "i sopravvissuti di un incidente") == ["sopravvissuto"]
    assert kept(["botole"], "una botola") == ["botole"] and kept(["isola"], "le isole") == ["isola"]
    assert dropped(["ferro"], "una Ferrari rossa") == ["ferro"]                   # a different word that only starts alike
    assert dropped(["uomo"], "gli uomini del re") == ["uomo"]                     # irregular plural: dropped, which only widens
    assert dropped(["re"], "i regni del nord") == ["re"]                          # short words must be equal


def test_compound_terms_need_every_word_next_to_each_other_in_order() -> None:
    assert kept(["Paolo Borsellino"], "film su Paolo Borsellino") == ["Paolo Borsellino"]
    assert dropped(["Paolo Rossi"], "film su Paolo Borsellino") == ["Paolo Rossi"]
    assert dropped(["Borsellino Paolo"], "film su Paolo Borsellino") == ["Borsellino Paolo"]
    assert dropped(["Paolo Borsellino"], "Paolo e il giudice Borsellino") == ["Paolo Borsellino"]
    assert dropped(["Paolo Borsellino"], "Paolo") == ["Paolo Borsellino"]         # request shorter than the term


def test_no_terms_no_request_and_empty_terms() -> None:
    assert verified_rare_terms([], S11) == ([], [])
    assert verified_rare_terms(["ferro"], "") == (["ferro"], [])                    # nothing to check against: untouched, as before
    assert verified_rare_terms(["ferro"], "   ") == (["ferro"], [])
    assert verified_rare_terms(["", "!!"], "una serie") == ([], ["", "!!"])         # nothing searchable is not a filter


class _Spy(R.SeriesIndex):
    """The real filter builder; `query` only records the filter it would send to Qdrant."""
    def __init__(self):
        self.seen = None

    def query(self, vector, *, limit, flt):
        self.seen = flt
        return []


def _search(signals, request):
    spy = _Spy()
    out = R.search(spy, lambda texts: np.stack([np.asarray(_vec(0), dtype=np.float32) for _ in texts]), signals, k=5, request=request)
    return spy.seen, out


def _terms_in(flt):
    return [c.match.text for c in flt.must if getattr(c, "key", None) == "plot_text"]


def test_a_dropped_term_is_not_in_the_filter_and_is_reported() -> None:
    sg = R.SeriesSignals(positive_it="x", positive_en="x", rare_terms=["ferro"])
    flt, out = _search(sg, S11)
    assert _terms_in(flt) == [] and out.notes["dropped_rare_terms"] == ["ferro"]
    assert sg.rare_terms == ["ferro"]                                                # the caller's signals stay as the parser wrote them (the trace shows them)


def test_a_kept_term_is_still_a_hard_filter_and_the_notes_stay_clean() -> None:
    flt, out = _search(R.SeriesSignals(positive_it="x", positive_en="x", level="tv_movie", rare_terms=["Paolo Borsellino"]), S05)
    assert _terms_in(flt) == ["Paolo Borsellino"] and "dropped_rare_terms" not in out.notes


def test_a_mix_keeps_the_valid_term_only_and_other_filters_are_untouched() -> None:
    sg = R.SeriesSignals(positive_it="x", positive_en="x", rare_terms=["ferro", "Hawkins"], year_from=1990, countries=["Stati Uniti"])
    flt, out = _search(sg, "a series set in Hawkins with an iron throne")
    assert _terms_in(flt) == ["Hawkins"] and out.notes["dropped_rare_terms"] == ["ferro"]
    keys = [getattr(c, "key", None) for c in flt.must]
    assert "year" in keys and "country" in keys and "entity_type" in keys


def test_searching_without_a_request_text_keeps_every_term() -> None:
    flt, out = _search(R.SeriesSignals(positive_it="x", positive_en="x", rare_terms=["ferro"]), "")
    assert _terms_in(flt) == ["ferro"] and "dropped_rare_terms" not in out.notes


@pytest.fixture()
def catalogue():
    c = QdrantClient(":memory:")
    c.create_collection("t", vectors_config=models.VectorParams(size=DIM, distance=models.Distance.COSINE))
    c.upsert("t", points=[_mk("s1", "series", "Alfa", 0, plot="il trono di ferro"), _mk("s2", "series", "Beta", 0, plot="un viaggio nel tempo"),
                          _mk("s3", "series", "Gamma", 1, plot="draghi e re")])
    return R.SeriesIndex(client=c, collection="t")


def test_through_the_tool_a_translated_term_no_longer_empties_the_catalogue(catalogue) -> None:
    sg = R.SeriesSignals(positive_it="x", positive_en="x", rare_terms=["ferro"])
    result = make_tool(catalogue, sg).run(query=S11, params={"query": S11, "turn_id": "t1"})
    titles = {i["title"] for i in result["metadata"]["series_rag"]["items"]}
    assert titles == {"Alfa", "Beta", "Gamma"}                                       # before the fix only "Alfa" (the plot with "ferro") could be returned
    assert "dropped_rare_terms" not in result["metadata"]["series_rag"]["notes"]     # nothing about it reaches the answer prompt
    step = result["trace"][0]["data"]
    assert step["notes"]["dropped_rare_terms"] == ["ferro"] and step["signals"]["rare_terms"] == ["ferro"]   # the trace keeps original and dropped terms


def test_through_the_tool_a_real_term_still_filters(catalogue) -> None:
    sg = R.SeriesSignals(positive_it="x", positive_en="x", rare_terms=["ferro"])
    query = "una serie con il trono di ferro"
    result = make_tool(catalogue, sg).run(query=query, params={"query": query, "turn_id": "t2"})
    assert [i["title"] for i in result["metadata"]["series_rag"]["items"]] == ["Alfa"]
