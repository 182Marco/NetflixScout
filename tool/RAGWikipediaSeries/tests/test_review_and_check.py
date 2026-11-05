from __future__ import annotations

from tool.RAGWikipediaSeries import audit_series as au
from tool.RAGWikipediaSeries import build_clean as bc
from tool.RAGWikipediaSeries import check_catalog as cc
from tool.RAGWikipediaSeries import review_rules as rr
from tool.RAGWikipediaSeries.tests.test_build_clean import world

NONE = {"relations": {}, "exclude": {}, "reclassify": {}, "flag": {}}


def test_self_described_serial_blocks_the_film_flag():
    assert rr.SELF_DESCRIBED_SERIAL.search("La miniserie racconta") and rr.SELF_DESCRIBED_SERIAL.search("La prima puntata inizia")
    assert not rr.SELF_DESCRIBED_SERIAL.search("Il film narra le vicende di Socrate")
    assert rr.SERIAL_TEXT.search("in tre puntate") and not rr.SERIAL_TEXT.search("una puntata")


def test_regex_infobox_check_is_independent_of_the_parser():
    text = "{{Fumetto e animazione\n|tipo = manga\n}}\n{{Fumetto e animazione\n|tipo = anime\n|sottotipo = serie TV\n}}\nx"
    boxes = au.regex_infoboxes(text)
    assert boxes == [("manga", ""), ("anime", "serie tv")] and [au.tv_box(*b) for b in boxes] == [False, True]


def test_flag_and_reclassify_keep_original_and_mixed_override(tmp_path):
    inputs = world(tmp_path)
    ov = {**NONE, "reclassify": {"1": {"to": "tv_movie", "reason": "r", "original": {"bucket": "series"}}},
          "flag": {"5": {"flag": "possible_tv_movie", "reason": "why"}}}
    out = bc.build(*inputs, ov)
    moved = next(m for m in out["tv_movies"] if m["page_id"] == 1)
    assert moved["original_classification"] == {"bucket": "series"} and "reclassified:tv_movie" in moved["flags"]
    flagged = next(m for m in out["tv_movies"] if m["page_id"] == 5)
    assert "possible_tv_movie" in flagged["flags"] and flagged["review_note"] == "why"
    mixed = bc.build(*inputs, {**NONE, "flag": {"1": {"flag": "mixed_media", "reason": "r"}}})
    s = mixed["series"][0]
    assert s["catalog_class"] == "franchise_page_mixed_media" and s["default_search_eligible"] is False
    assert s["text_provenance"]["revision_id"] == 1 and s["text_provenance"]["kind"] == "plot"


def test_coherence_checks_pass_on_a_valid_catalogue_and_fail_on_a_broken_one(tmp_path):
    s1, s2, s3 = world(tmp_path)
    out = bc.build(s1, s2, s3, NONE)
    bc.write(out, tmp_path / "s5", tmp_path / "none.json")
    assert cc.check(tmp_path / "s5", s1)["failed"] == []
    out["episodes"][0]["series_id"] = "wp-999"
    bc.write(out, tmp_path / "bad", tmp_path / "none.json")
    assert "series_id_resolves" in cc.check(tmp_path / "bad", s1)["failed"]
