"""Phase 4 audit: the classification rules on synthetic records, the manual review table and the claim reader. No data files."""
from __future__ import annotations

import pytest

from tool.RAGWikipediaFilm.audit import classify as C
from tool.RAGWikipediaFilm.audit import features as F
from tool.RAGWikipediaFilm.audit import manual_review as M


def rec(title="Un film", *, p31=(), flags=(), imdb=None, director=(), genres=(), year=1990, has_wd=True):
    film = {"film_id": "Q1", "title": title, "year": year, "imdb_id": imdb, "director": [{"name": d} for d in director],
            "genres": list(genres)}
    return {"film": film, "flags": list(flags), "p31": list(p31), "has_wd": has_wd}


def test_infobox_feature_film_is_a_confident_film():
    c = C.classify(rec(p31=["Q11424"]))
    assert (c["verdict"], c["subtype"], c["confidence"]) == ("film", "feature", "high")


def test_genre_and_technique_articles_are_topics_even_with_a_plot_section():
    for q in ("Q201658", "Q110900120"):
        c = C.classify(rec("Cinema muto", p31=[q], flags=["no_infobox"], year=None))
        assert c["verdict"] == "topic" and c["confidence"] == "high"


def test_series_of_films_page_is_a_topic_not_a_film():
    assert C.classify(rec("Saw (serie di film)", flags=["no_infobox"], year=None))["verdict"] == "topic"


def test_category_only_series_and_manga_are_not_films():
    for q, sub in (("Q1259759", "miniseries"), ("Q21198342", "manga"), ("Q5398426", "tv_series")):
        c = C.classify(rec("Qualcosa", p31=[q], flags=["no_infobox"], year=None))
        assert (c["verdict"], c["subtype"]) == ("series", sub)


def test_a_series_class_on_a_page_with_a_film_infobox_is_doubtful_not_excluded():
    c = C.classify(rec("Digimon Adventure 02", p31=["Q63952888"]))
    assert c["verdict"] == "doubtful" and c["confidence"] == "low"


def test_title_suffix_marks_a_series_when_wikidata_has_no_film_class():
    c = C.classify(rec("Cuore (miniserie televisiva 2001)", flags=["no_infobox"], year=None, imdb="tt1"))
    assert c["verdict"] == "series"


def test_tv_film_found_through_a_category_needs_imdb_or_director_to_stay_a_film():
    assert C.classify(rec(p31=["Q506240"], flags=["no_infobox"], imdb="tt1"))["verdict"] == "film"
    assert C.classify(rec("Un titolo", p31=["Q506240"], flags=["no_infobox"]))["verdict"] == "doubtful"


def test_video_games_and_literary_works_are_other_works():
    assert C.classify(rec(p31=["Q7889"], flags=["no_infobox"], year=None))["verdict"] == "other_work"


def test_infobox_page_without_wikidata_item_is_kept_as_a_film_with_medium_confidence():
    c = C.classify(rec("Nuovo film", p31=[], has_wd=False))
    assert (c["verdict"], c["confidence"]) == ("film", "medium")


def test_every_decision_carries_its_reasons():
    assert C.classify(rec(p31=["Q201658"], flags=["no_infobox"]))["reasons"]


def test_claim_ids_ignores_deprecated_and_novalue():
    entity = {"claims": {"P31": [
        {"rank": "normal", "mainsnak": {"datavalue": {"value": {"id": "Q11424"}}}},
        {"rank": "deprecated", "mainsnak": {"datavalue": {"value": {"id": "Q1"}}}},
        {"rank": "normal", "mainsnak": {"snaktype": "novalue"}}]}}
    assert F.claim_ids(entity, "P31") == ["Q11424"]


def test_manual_review_matches_exactly_one_record_or_fails():
    rows = [{"film": {"film_id": "Q1", "title": "Alpha"}}, {"film": {"film_id": "Q2", "title": "Alphabet"}}]
    original = M.REVIEW
    try:
        M.REVIEW = [("Alpha", "topic", "x", "n")]
        assert list(M.apply(rows)) == ["Q1"]            # exact title wins over the prefix match
        M.REVIEW = [("Alp", "topic", "x", "n")]
        with pytest.raises(ValueError):
            M.apply(rows)                                  # two prefix matches
        M.REVIEW = [("Missing", "topic", "x", "n")]
        with pytest.raises(ValueError):
            M.apply(rows)
    finally:
        M.REVIEW = original


def test_no_manual_entry_decides_a_nonsense_verdict():
    assert {v for _, v, _, _ in M.REVIEW} <= {"film", "series", "topic", "other_work", "doubtful"}
