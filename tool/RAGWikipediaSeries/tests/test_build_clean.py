from __future__ import annotations

import json

from tool.RAGWikipediaSeries import build_clean as bc
from tool.RAGWikipediaSeries import build_relations as br


def w(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + ("\n" if rows else ""), encoding="utf-8")


def series(pid, title, **kw):
    return {"record_id": f"wp-{pid}", "page_id": pid, "title": title, "subtype": "tv_series", "wikipedia_url": "u", "revision_id": 1, "info": {"year": 2000, "stagioni": "2"},
            "text_kind": "plot", "plot_text": "p" * 500, "lead_text": "", "plot_chars": 500, "lead_chars": 0, "inline_episode_row_count": 0, **kw}


def world(tmp_path):
    s1, s2, s3 = tmp_path / "s1", tmp_path / "s2", tmp_path / "s3"
    for d in (s1, s2, s3):
        d.mkdir()
    movie = {**series(5, "Un film"), "subtype": "tv_movie", "director": "R", "info": {"cast": "A"}, "classification": {"class": "tv_movie"}}
    w(s1 / "series.jsonl", [series(1, "Serie X", info={"year": 2000, "stagioni": "3", "paese": "Italia, Francia", "genere": "giallo"})])
    w(s1 / "tv_movies.jsonl", [movie])
    w(s1 / "uncertain.jsonl", [])
    w(s1 / "excluded.jsonl", [{"record_id": "wp-9", "page_id": 9, "title": "Talk", "reason": "programme_not_episodic", "detail": ["x"]}])
    rows = [{"number_int": 1, "number": "1", "title_it": "Pilota", "dates": ["1 maggio 2000"], "cells": []},
            {"number_int": 2, "number": "2", "title_it": "Secondo", "cells": []}, {"partial": True, "cells": ["3"], "number_int": 3}]
    w(s1 / "seasons.jsonl", [{"record_id": "wp-2", "page_id": 2, "title": "Episodi di Serie X (prima stagione)", "series_name_from_title": "Serie X",
                              "lead_text": "x" * 200, "table_rows": rows, "table_row_count": 3, "episode_section_count": 1, "wikipedia_url": "u2", "revision_id": 2}])
    w(s1 / "episode_lists.jsonl", [])
    w(s1 / "episodes.jsonl", [{"record_id": "wp-2#s0", "page_id": 2, "title": "Pilota", "parent_page_id": 2, "source": "season_page",
                               "plot_text": "t" * 300, "plot_chars": 300, "wikipedia_url": "u2#Pilota", "revision_id": 2}])
    w(s2 / "wikidata_entities.jsonl", [{"page_id": 1, "qid": "Q1", "imdb_id": "tt1", "tmdb_tv_id": "10"}, {"page_id": 5, "qid": "Q5", "imdb_id": "tt5"}])
    w(s3 / "relations.jsonl", [{"child_page_id": 2, "child_record_id": "wp-2", "child_type": "season", "parent_page_id": 1, "status": "verified_wikidata",
                                "season_number": 1, "season_number_sources": {}, "sources": {}, "notes": []}])
    w(s3 / "episode_links.jsonl", [{"episode_record_id": "wp-2#s0", "parent_page_id": 2, "parent_kind": "season", "season_number": 1, "series_page_id": 1,
                                    "series_status": "verified_wikidata", "episode_number": 1, "row_index": 0, "numbering": "table_row_exact_title"}])
    w(s3 / "logical_seasons.jsonl", [{"record_id": "wp-1#season2", "series_page_id": 1, "series_title": "Serie X", "season_number": 2,
                                      "evidence": "infobox_declared_count", "text": None}])
    return s1, s2, s3


def test_hierarchy_ids_and_tv_movie_stays_autonomous(tmp_path):
    out = bc.build(*world(tmp_path), {"relations": {}, "exclude": {}, "reclassify": {}})
    assert out["series"][0]["ids"] == {"qid": "Q1", "imdb_id": "tt1", "tmdb_id": "10", "tmdb_kind": "tv"}
    assert out["series"][0]["country"] == ["Italia", "Francia"]
    season = next(s for s in out["seasons"] if not s["logical"])
    assert season["series_id"] == "wp-1" and season["season_number"] == 1 and season["text_kind"] == "season_intro"
    logical = next(s for s in out["seasons"] if s["logical"])
    assert logical["series_id"] == "wp-1" and logical["text_kind"] == "none" and logical["lead_text"] == ""   # no invented content
    ep = out["episodes"][0]
    assert (ep["series_id"], ep["season_id"], ep["episode_number"], ep["air_dates"]) == ("wp-1", "wp-2", 1, ["1 maggio 2000"])
    movie = out["tv_movies"][0]
    assert movie["series_id"] is None and movie["season_id"] is None and movie["parent_ids"] == [] and movie["ids"].get("imdb_id") == "tt5"
    assert movie["ids"].get("tmdb_id") is None and movie in out["tv_movies"]   # kept although it has no TMDb id


def test_metadata_rows_skip_matched_partial_and_numberless_rows(tmp_path):
    out = bc.build(*world(tmp_path), {"relations": {}, "exclude": {}, "reclassify": {}})
    assert [m["title"] for m in out["episodes_meta"]] == ["Secondo"]
    assert out["episodes_meta"][0]["text_kind"] == "none" and out["episodes_meta"][0]["flags"] == ["metadata_only"]


def test_override_exclude_detaches_children_and_is_reversible(tmp_path):
    inputs = world(tmp_path)
    cut = bc.build(*inputs, {"relations": {}, "exclude": {"1": {"reason": "falso positivo"}}, "reclassify": {}})
    assert cut["series"] == [] and any(e["reason"] == "override_exclude" for e in cut["excluded"])
    assert all(s["series_id"] is None for s in cut["seasons"]) and "parent_excluded" in cut["seasons"][0]["flags"]
    restored = bc.build(*inputs, {"relations": {}, "exclude": {}, "reclassify": {}})
    assert len(restored["series"]) == 1


def test_reclassify_series_to_tv_movie(tmp_path):
    out = bc.build(*world(tmp_path), {"relations": {}, "exclude": {}, "reclassify": {"1": {"to": "tv_movie", "reason": "x"}}})
    assert out["series"] == [] and {m["page_id"] for m in out["tv_movies"]} == {1, 5}
    assert "reclassified:tv_movie" in next(m for m in out["tv_movies"] if m["page_id"] == 1)["flags"]


def test_write_is_deterministic(tmp_path):
    inputs = world(tmp_path)
    o = {"relations": {}, "exclude": {}, "reclassify": {}}
    a = bc.write(bc.build(*inputs, o), tmp_path / "a", tmp_path / "none.json")
    b = bc.write(bc.build(*inputs, o), tmp_path / "b", tmp_path / "none.json")
    assert {k: v["sha256"] for k, v in a["files"].items()} == {k: v["sha256"] for k, v in b["files"].items()}


def test_identical_plot_is_flagged_not_removed(tmp_path):
    s1, s2, s3 = world(tmp_path)
    w(s1 / "series.jsonl", [series(1, "A"), series(7, "B")])           # same 500-char plot
    out = bc.build(s1, s2, s3, {"relations": {}, "exclude": {}, "reclassify": {}})
    assert len(out["series"]) == 2 and all("duplicate_plot_text" in r["flags"] and r["plot_text_shared_by"] >= 2 for r in out["series"])
