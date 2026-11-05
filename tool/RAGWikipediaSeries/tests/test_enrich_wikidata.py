from __future__ import annotations

import json

from tool.RAGWikipediaSeries import enrich_wikidata as wd


def entity(qid, title, claims=None):
    return {"id": qid, "labels": {"it": {"value": title}}, "sitelinks": {"itwiki": {"title": title}}, "claims": claims or {}}


def item(qid):
    return {"mainsnak": {"snaktype": "value", "datavalue": {"value": {"id": qid}}}, "rank": "normal"}


def string(v, rank="normal"):
    return {"mainsnak": {"snaktype": "value", "datavalue": {"value": v}}, "rank": rank}


ORDINAL = {"qualifiers": {"P1545": [{"snaktype": "value", "datavalue": {"value": "2"}}]}}


class FakeClient:
    network_requests = 0
    snapshot_hits = 0

    class cfg:  # noqa: N801
        snapshot_id = "fake"
        mode = "offline"

    def __init__(self):
        self.calls = []

    def get_json(self, params):
        self.calls.append(params)
        if "titles" in params:
            ents = {}
            for i, t in enumerate(params["titles"].split("|")):
                if t == "Mancante":
                    ents[f"-{i + 1}"] = {"site": "itwiki", "title": t, "missing": ""}
                elif t.startswith("Episodi di S"):
                    ents["Q2"] = entity("Q2", t, {"P31": [item("Q3464665")], "P179": [{**item("Q1"), **ORDINAL}]})
                else:
                    ents["Q1"] = entity("Q1", t, {"P31": [item("Q5398426")], "P345": [string("tt1"), string("tt9", "deprecated")]})
            return {"entities": ents}
        return {"entities": {q: {"labels": {"en": {"value": "L" + q}}} for q in params["ids"].split("|")}}


def write(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_summarize_keeps_ordinal_and_skips_deprecated():
    e = entity("Q2", "Episodi di S (seconda stagione)", {"P179": [{**item("Q1"), **ORDINAL}],
                                                         "P345": [string("tt9", "deprecated"), string("tt1")]})
    out = wd.summarize(e, "t")
    assert out["part_of_series"] == [{"qid": "Q1", "ordinal": "2"}]
    assert out["imdb_id"] == "tt1"


def test_run_writes_matched_missing_and_classes(tmp_path):
    s1 = tmp_path / "s1"
    s1.mkdir()
    write(s1 / "series.jsonl", [{"page_id": 10, "title": "Serie"}, {"page_id": 30, "title": "Mancante"}])
    write(s1 / "seasons.jsonl", [{"page_id": 20, "title": "Episodi di S (seconda stagione)"}])
    write(s1 / "episodes.jsonl", [{"page_id": 20, "title": "Sezione", "source": "season_page"}])  # a section: no entity of its own
    out = tmp_path / "s2"
    manifest = wd.run(FakeClient(), s1, out)
    rows = [json.loads(l) for l in open(out / "wikidata_entities.jsonl")]
    assert [r["page_id"] for r in rows] == [10, 20] and rows[1]["part_of_series"][0]["qid"] == "Q1"
    assert [json.loads(l)["title"] for l in open(out / "wikidata_missing.jsonl")] == ["Mancante"]
    assert manifest["entities"] == 2 and manifest["missing"] == 1
    assert json.load(open(out / "wikidata_classes.json"))["Q5398426"]["en"] == "LQ5398426"


def test_titles_with_pipe_are_skipped_not_sent(tmp_path):
    s1 = tmp_path / "s1"
    s1.mkdir()
    write(s1 / "series.jsonl", [{"page_id": 1, "title": "A|B"}])
    client = FakeClient()
    manifest = wd.run(client, s1, tmp_path / "s2")
    assert manifest["skipped_titles_with_pipe"] == 1 and not any("titles" in c for c in client.calls)


def test_rerun_is_byte_identical(tmp_path):
    s1 = tmp_path / "s1"
    s1.mkdir()
    write(s1 / "series.jsonl", [{"page_id": 10, "title": "Serie"}])
    a, b = tmp_path / "a", tmp_path / "b"
    wd.run(FakeClient(), s1, a)
    wd.run(FakeClient(), s1, b)
    assert (a / "wikidata_entities.jsonl").read_bytes() == (b / "wikidata_entities.jsonl").read_bytes()
