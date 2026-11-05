from __future__ import annotations

import json

from tool.RAGWikipediaSeries import audit_series as au


def test_family_of_wikidata_class_labels():
    assert au.family("television series") == "series"
    assert au.family("anime television series") == "series"
    assert au.family("television film") == "film"
    assert au.family("film") == "film"
    assert au.family("manga series") == "other"
    assert au.family("film series") == "other"      # a collection of films is not a film
    assert au.family("television series episode") == "series"
    assert au.family("television episode") == "other"
    assert au.family(None) == "unknown"


def w(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + ("\n" if rows else ""), encoding="utf-8")


def test_audit_flags_disagreement_duplicates_and_is_deterministic(tmp_path):
    s1, s2, s3 = tmp_path / "s1", tmp_path / "s2", tmp_path / "s3"
    for d in (s1, s2, s3):
        d.mkdir()
    rec = lambda pid, title, **kw: {"record_id": f"wp-{pid}", "page_id": pid, "title": title, "subtype": "tv_series", "text_kind": "plot",
                                    "plot_text": kw.pop("plot_text", f"testo {pid}"), "wikipedia_url": "u", **kw}
    w(s1 / "series.jsonl", [rec(1, "A"), rec(2, "B (serie)", plot_text="uguale"), rec(3, "B (altra)", plot_text="uguale")])
    w(s1 / "tv_movies.jsonl", [rec(4, "Un film", subtype="tv_movie")])
    for name in ("uncertain", "seasons", "episode_lists", "episodes"):
        w(s1 / f"{name}.jsonl", [])
    w(s2 / "wikidata_entities.jsonl", [{"page_id": 1, "qid": "Q1", "instance_of": ["C1"]}, {"page_id": 2, "qid": "Q9", "instance_of": ["C2"]},
                                       {"page_id": 3, "qid": "Q9", "instance_of": ["C2"]}, {"page_id": 4, "qid": "Q4", "instance_of": ["C1"]}])
    (s2 / "wikidata_classes.json").write_text(json.dumps({"C1": {"en": "television series"}, "C2": {"en": "manga series"}}))
    w(s3 / "relations.jsonl", [])
    numbers, review, sample = au.audit(s1, s2, s3)
    assert numbers["class_agreement"]["series/agrees"] == 1
    assert numbers["class_agreement"]["series/disagrees:other"] == 2
    assert numbers["class_agreement"]["tv_movies/disagrees:series"] == 1       # TV movie whose entity is a series: to review
    assert numbers["duplicates"] == {"same_qid": 1, "same_base_title_series": 1, "identical_plot_text": 1}
    assert {r["kind"] for r in review} >= {"class_disagreement", "duplicate_qid", "identical_plot_text"}
    again = au.audit(s1, s2, s3)
    assert again[2] == sample and again[0] == numbers   # same seeded sample on every run
