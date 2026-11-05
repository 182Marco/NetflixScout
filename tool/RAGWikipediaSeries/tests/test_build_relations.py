from __future__ import annotations

import json

from tool.RAGWikipediaSeries import build_relations as br


def S(pid, title, **kw):
    return {"page_id": pid, "record_id": f"wp-{pid}", "title": title, "info": {}, "inline_sections": [], **kw}


def season(pid, name, qualifier, torna=None, rows=None, number=None):
    return {"page_id": pid, "record_id": f"wp-{pid}", "title": f"Episodi di {name} ({qualifier})", "series_name_from_title": name,
            "season_number": number, "torna_a": torna, "table_rows": rows or []}


def write(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + ("\n" if rows else ""), encoding="utf-8")


def setup(tmp_path, series, seasons=(), lists=(), episodes=(), entities=()):
    s1, s2 = tmp_path / "s1", tmp_path / "s2"
    s1.mkdir(), s2.mkdir()
    write(s1 / "series.jsonl", series)
    write(s1 / "seasons.jsonl", list(seasons))
    write(s1 / "episode_lists.jsonl", list(lists))
    write(s1 / "episodes.jsonl", list(episodes))
    write(s2 / "wikidata_entities.jsonl", list(entities))
    return s1, s2


def test_decide_statuses():
    a, b = {"page_id": 1}, {"page_id": 2}
    assert br.decide({"torna_a": a, "title": a, "wikidata": a})[0] == "verified_wikidata"
    assert br.decide({"torna_a": a, "title": a, "wikidata": None})[0] == "verified_wikipedia"
    assert br.decide({"torna_a": a, "title": None, "wikidata": None})[0] == "inferred"
    assert br.decide({"torna_a": a, "title": b, "wikidata": None}) [0] == "conflict"
    status, parent, notes = br.decide({"torna_a": a, "title": b, "wikidata": b})
    assert (status, parent["page_id"], notes) == ("verified_wikidata", 2, ["wikidata_breaks_tie"])
    assert br.decide({"torna_a": None, "title": None, "wikidata": None})[0] == "orphan"
    status, parent, notes = br.decide({"torna_a": a, "title": a, "wikidata": b})   # two Wikipedia statements outweigh one Wikidata
    assert (status, parent["page_id"]) == ("verified_wikipedia", 1) and notes == ["wikidata_disagrees:2"]


def test_season_resolved_by_wikidata_and_number_cross_check(tmp_path):
    ents = [{"page_id": 1, "qid": "Q1"}, {"page_id": 2, "qid": "Q2", "part_of_series": [{"qid": "Q1", "ordinal": "3"}]}]
    s1, s2 = setup(tmp_path, [S(1, "Serie X")], [season(2, "Serie X", "seconda stagione", torna="Serie X", number=2)], entities=ents)
    edge = br.build(s1, s2, tmp_path / "none", {})["relations"][0]
    assert edge["status"] == "verified_wikidata" and edge["parent_page_id"] == 1
    assert "season_number_disagrees" in edge["notes"] and edge["season_number"] == 2


def test_conflict_is_reviewed_not_guessed_and_override_is_reversible(tmp_path):
    series = [S(1, "Alfa"), S(2, "Beta")]
    seasons = [season(3, "Beta", "prima stagione", torna="Alfa", number=1)]
    s1, s2 = setup(tmp_path, series, seasons)
    out = br.build(s1, s2, tmp_path / "none", {})
    assert out["relations"][0]["status"] == "conflict" and out["relations"][0]["parent_page_id"] is None
    assert len(out["relation_review"]) == 1
    fixed = br.build(s1, s2, tmp_path / "none", {"relations": {"3": {"series_page_id": 2, "reason": "checked"}}})
    assert fixed["relations"][0]["status"] == "reviewed" and fixed["relations"][0]["parent_page_id"] == 2
    again = br.build(s1, s2, tmp_path / "none", {})  # the S1 inputs are untouched: dropping the override restores the automatic result
    assert again["relations"][0]["status"] == "conflict"


def test_episode_numbered_only_by_exact_title_match(tmp_path):
    rows = [{"number_int": 1, "title_it": "Il pilota", "cells": []}, {"number_int": 2, "title_it": "Secondo", "cells": []}]
    eps = [{"record_id": "wp-3#s0", "title": "Il pilota", "parent_page_id": 3, "source": "season_page"},
           {"record_id": "wp-3#s1", "title": "Titolo diverso", "parent_page_id": 3, "source": "season_page"}]
    s1, s2 = setup(tmp_path, [S(1, "Serie X")], [season(3, "Serie X", "prima stagione", torna="Serie X", rows=rows, number=1)], episodes=eps)
    links = {l["episode_record_id"]: l for l in br.build(s1, s2, tmp_path / "none", {})["episode_links"]}
    assert links["wp-3#s0"]["episode_number"] == 1 and links["wp-3#s0"]["numbering"] == "table_row_exact_title"
    assert links["wp-3#s1"]["episode_number"] is None and links["wp-3#s1"]["numbering"] == "unknown"
    assert links["wp-3#s1"]["series_page_id"] == 1


def test_episode_list_without_season_keeps_series_but_no_season_number(tmp_path):
    lst = {"page_id": 4, "record_id": "wp-4", "title": "Episodi di Serie X", "torna_a": "Serie X", "table_rows": []}
    eps = [{"record_id": "wp-4#l0", "title": "Pilota", "parent_page_id": 4, "source": "episode_list_page"}]
    s1, s2 = setup(tmp_path, [S(1, "Serie X")], lists=[lst], episodes=eps)
    link = br.build(s1, s2, tmp_path / "none", {})["episode_links"][0]
    assert link["series_page_id"] == 1 and link["season_number"] is None and link["parent_kind"] == "episode_list"


def test_logical_seasons_only_from_page_evidence_without_text_invented(tmp_path):
    series = [S(1, "Serie X", info={"stagioni": "3"})]
    s1, s2 = setup(tmp_path, series, [season(2, "Serie X", "seconda stagione", torna="Serie X", number=2)])
    logical = br.build(s1, s2, tmp_path / "none", {})["logical_seasons"]
    assert [l["season_number"] for l in logical] == [1, 3]
    assert all(l["text"] is None and l["has_own_page"] is False and l["evidence"] == "infobox_declared_count" for l in logical)


def test_ordinal_of_headings():
    assert br.ordinal_of("Prima stagione") == 1 and br.ordinal_of("Stagione 4") == 4 and br.ordinal_of("Cast") is None


def test_title_without_qualifier_is_not_evidence_against_a_qualified_torna_a(tmp_path):
    series = [S(1, "Suits"), S(2, "Suits (serie televisiva 2018)")]
    lst = {"page_id": 3, "record_id": "wp-3", "title": "Episodi di Suits (serie televisiva 2018)", "torna_a": "Suits (serie televisiva 2018)", "table_rows": []}
    s1, s2 = setup(tmp_path, series, lists=[lst])
    edge = br.build(s1, s2, tmp_path / "none", {})["relations"][0]
    assert edge["parent_page_id"] == 2 and edge["status"] == "inferred" and "title_not_discriminating" in edge["notes"]


def test_season_pointing_to_a_list_page_inherits_that_pages_series(tmp_path):
    lst = {"page_id": 4, "record_id": "wp-4", "title": "Episodi di Naruto", "torna_a": "Naruto (serie televisiva)", "table_rows": []}
    sea = season(5, "Naruto: Shippuden", "settima stagione", torna="Episodi di Naruto", number=7)
    s1, s2 = setup(tmp_path, [S(1, "Naruto (serie televisiva)")], [sea], lists=[lst])
    edges = {e["child_page_id"]: e for e in br.build(s1, s2, tmp_path / "none", {})["relations"]}
    assert edges[4]["parent_page_id"] == 1 and edges[5]["parent_page_id"] == 1
    assert edges[5]["status"] == "inferred" and edges[5]["notes"] == ["via_list_page:Episodi di Naruto"]
