import json

import pytest
from pydantic import ValidationError

from wikidata_fake import FILM_UNO, FakeWikidata
from pipelines.wikipedia_films.config import load_config
from pipelines.wikipedia_films.enrich_metadata import (
    derive_record, duration_from_wikidata, infobox_actors, infobox_duration, infobox_year, run_enrich,
    year_from_wikidata,
)
from pipelines.wikipedia_films.schema import FilmRecord, dumps_record
from pipelines.wikipedia_films.wikidata_client import (
    Snapshot, SnapshotMiss, WikidataClient, WikidataError, request_key,
)

CANDIDATE = {
    "page_id": 1, "title": "Film Uno", "revision_id": "100", "timestamp": "2026-10-01T10:00:00Z",
    "infobox": {"titolo originale": "Original Uno", "anno uscita": "1990", "durata": "{{Lista|100 min|110 min}}",
                "regista": "[[Fallback Regista]]", "genere": "Giallo", "genere 2": "Drammatico",
                "attori": "\n* [[Marlon Rossi]]: Don Vito\n* [[Al Neri]]: Michael"},
    "plot": "Trama pulita.", "plot_heading": "Trama", "flags": [],
}
LABELS = {k: v for k, v in __import__("wikidata_fake").LABELS.items()}


@pytest.fixture
def config(tmp_path):
    cfg = load_config(overrides={"wikidata.contact": "test@example.invalid", "wikidata.mode": "online",
                                 "wikidata.min_interval_seconds": 0, "wikidata.retry_backoff_seconds": 1})
    object.__setattr__(cfg.extract, "processed_dir", str(tmp_path / "processed"))
    object.__setattr__(cfg.wikidata, "snapshot_root", str(tmp_path / "snap"))
    return cfg


def _client(config, fake, snapshot=None):
    sleeps = []
    client = WikidataClient(config.wikidata, snapshot or Snapshot(config.snapshot_dir), transport=fake,
                            sleep=sleeps.append, clock=lambda: 0.0)
    client.sleeps = sleeps
    return client


def test_wikidata_values_win_and_missing_values_are_null_or_empty(config):
    record = derive_record(CANDIDATE, FILM_UNO, LABELS, config=config)
    FilmRecord.model_validate(record)
    assert record["film_id"] == record["wikidata_id"] == "Q1001"
    assert record["year"] == 1998  # earliest publication date
    assert record["duration_minutes"] == 110  # 6600 s
    assert record["director"] == [{"name": "Anna Bianchi", "wikidata_id": "Q2001"}]
    assert record["actors"] == [
        {"name": "Luca Verdi", "wikidata_id": "Q2002", "character": "Il Professore"},
        {"name": "Maria Neri", "wikidata_id": "Q2003", "character": None},  # label fallback to en
    ]
    assert record["genres"] == ["drammatico"]  # the deprecated statement is ignored
    assert record["country"] == ["Italia"] and record["language"] == ["lingua italiana"]
    assert record["imdb_id"] == "tt0123456" and record["original_title"] == "The First Film"
    assert record["retrieved_at"] == "2026-11-01T00:00:00Z" and record["source_revision_id"] == "100"
    assert record["wikipedia_url"] == "https://it.wikipedia.org/wiki/Film_Uno"


def test_infobox_fallback_when_wikidata_is_missing(config):
    record = derive_record(CANDIDATE, None, {}, config=config)
    FilmRecord.model_validate(record)
    assert record["film_id"] == "wp-1" and record["wikidata_id"] is None and record["imdb_id"] is None
    assert record["year"] == 1990 and record["duration_minutes"] == 100
    assert record["director"] == [{"name": "Fallback Regista", "wikidata_id": None}]
    assert record["genres"] == ["Giallo", "Drammatico"]
    assert record["actors"][0] == {"name": "Marlon Rossi", "wikidata_id": None, "character": "Don Vito"}
    assert record["original_title"] == "Original Uno"


def test_nothing_is_invented():
    bare = {"page_id": 5, "title": "Nudo", "revision_id": "1", "timestamp": "", "infobox": {}, "plot": "x"}
    cfg = load_config()
    record = derive_record(bare, None, {}, config=cfg)
    assert record["year"] is None and record["duration_minutes"] is None and record["original_title"] is None
    assert record["director"] == record["actors"] == record["genres"] == record["country"] == record["language"] == []


def test_pure_helpers():
    assert year_from_wikidata({"claims": {"P577": [{"rank": "normal", "mainsnak": {"snaktype": "value", "datavalue": {
        "value": {"time": "+1950-00-00T00:00:00Z", "precision": 7}}}}]}}) is None  # century precision ignored
    assert duration_from_wikidata({"claims": {}}) is None
    assert infobox_year({"anno": "[[1975]]"}) == 1975 and infobox_duration({"durata": "n.d."}) is None
    assert infobox_actors({"attori": "senza elenco"}, 5) == []


def test_schema_rejects_bad_values(config):
    good = derive_record(CANDIDATE, FILM_UNO, LABELS, config=config)
    for field, value in [("imdb_id", "12345"), ("wikidata_id", "X1"), ("retrieved_at", "ieri"),
                         ("film_id", "abc"), ("year", 3000), ("synopsis", " ")]:
        with pytest.raises(ValidationError):
            FilmRecord.model_validate({**good, field: value})
    with pytest.raises(ValidationError):
        FilmRecord.model_validate({**good, "extra": 1})


def test_snapshot_keeps_original_bytes_and_makes_offline_replay_exact(config):
    fake = FakeWikidata()
    client = _client(config, fake)
    first = client.get_json({"action": "wbgetentities", "ids": "Q2001"})
    original = client.snapshot.read(request_key({"action": "wbgetentities", "ids": "Q2001", "format": "json"}))
    assert json.loads(original) == first
    assert fake.calls[0]["headers"]["User-Agent"].startswith("RAGWikipediaPipeline/1.0 (test@")
    # a new object over the same directory, offline: zero network, same data
    object.__setattr__(config.wikidata, "mode", "offline")
    offline = _client(config, FakeWikidata())
    assert offline.get_json({"action": "wbgetentities", "ids": "Q2001"}) == first
    assert offline.network_requests == 0 and offline.snapshot_hits == 1
    with pytest.raises(SnapshotMiss):
        offline.get_json({"action": "wbgetentities", "ids": "Q9"})


def test_retry_with_backoff_and_retry_after(config):
    fake = FakeWikidata(fail_first=2, status=429)
    client = _client(config, fake)
    client.get_json({"action": "wbgetentities", "ids": "Q2001"})
    assert len(fake.calls) == 3 and client.sleeps == [2.0, 2.0]
    assert fake.calls[0]["params"]["maxlag"] == "5"
    failing = _client(config, FakeWikidata(fail_first=99, status=503))
    object.__setattr__(failing.cfg, "max_retries", 2)
    with pytest.raises(WikidataError):
        failing.get_json({"action": "wbgetentities", "ids": "Q1"})


def test_incomplete_read_is_retried(config):
    import http.client

    fake = FakeWikidata()
    calls = []

    def transport(url, headers, timeout, data=None):
        calls.append(url)
        if len(calls) == 1:
            raise http.client.IncompleteRead(b"")
        return fake(url, headers, timeout, data)

    client = _client(config, fake)
    client._transport = transport
    client.get_json({"action": "wbgetentities", "ids": "Q2001"})
    assert len(calls) == 2


def test_rate_limit_waits_between_requests(config):
    object.__setattr__(config.wikidata, "min_interval_seconds", 1.0)
    now = [0.0]
    sleeps = []
    client = WikidataClient(config.wikidata, Snapshot(config.snapshot_dir), transport=FakeWikidata(),
                            sleep=lambda s: (sleeps.append(s), now.__setitem__(0, now[0] + s)),
                            clock=lambda: now[0])
    client.get_json({"action": "wbgetentities", "ids": "Q2001"})
    client.get_json({"action": "wbgetentities", "ids": "Q2002"})
    assert sleeps == [1.0]


def test_empty_contact_is_refused_online(config):
    object.__setattr__(config.wikidata, "contact", " ")
    with pytest.raises(WikidataError, match="contact"):
        _client(config, FakeWikidata()).get_json({"action": "wbgetentities", "ids": "Q1"})


def test_run_enrich_is_byte_identical_online_then_offline(config, tmp_path):
    out = tmp_path / "processed"
    out.mkdir()
    second = {**CANDIDATE, "page_id": 2, "title": "Film Due", "revision_id": "200"}
    (out / "candidates.jsonl").write_text(
        "\n".join(json.dumps(c) for c in (second, CANDIDATE)) + "\n", encoding="utf-8")  # unsorted on purpose
    summary = run_enrich(config, _client(config, FakeWikidata()))
    assert summary["films"] == 2 and summary["network_requests"] == 2
    films = (out / "films.jsonl").read_bytes()
    lines = films.decode().splitlines()
    assert [json.loads(x)["wikipedia_page_id"] for x in lines] == [1, 2]  # sorted by page id
    assert json.loads(lines[1])["film_id"] == "wp-2"  # no Wikidata item: stable fallback id
    (out / "films.jsonl").unlink()
    object.__setattr__(config.wikidata, "mode", "offline")
    again = run_enrich(config, _client(config, FakeWikidata()))
    assert again["network_requests"] == 0
    assert (out / "films.jsonl").read_bytes() == films
    assert dumps_record(json.loads(lines[0])) == lines[0]


def test_enrich_resume_continues_only_with_the_same_input(config, tmp_path):
    out = tmp_path / "processed"
    out.mkdir()
    object.__setattr__(config.wikidata, "batch_size", 1)
    rows = [{**CANDIDATE, "page_id": i, "title": f"T{i}", "revision_id": str(i)} for i in (1, 2, 3)]
    (out / "candidates.jsonl").write_text("\n".join(json.dumps(c) for c in rows) + "\n", encoding="utf-8")

    class Boom(FakeWikidata):  # fails on the third batch: the run is interrupted after 2 batches
        def __call__(self, url, headers, timeout, data=None):
            if "T3" in url:
                raise KeyboardInterrupt
            return super().__call__(url, headers, timeout, data)

    with pytest.raises(KeyboardInterrupt):
        run_enrich(config, _client(config, Boom()))
    assert (out / "enrich_checkpoint.json").exists() and not (out / "films.jsonl").exists()
    done = json.loads((out / "enrich_checkpoint.json").read_text())["batches_done"]
    assert done == 2
    run_enrich(config, _client(config, FakeWikidata()))  # same input: resumes, finishes
    resumed = (out / "films.jsonl").read_bytes()
    (out / "films.jsonl").unlink()
    run_enrich(config, _client(config, FakeWikidata()))  # from scratch
    assert (out / "films.jsonl").read_bytes() == resumed and len(resumed.splitlines()) == 3


def test_enrich_checkpoint_of_a_different_input_is_ignored(config, tmp_path):
    out = tmp_path / "processed"
    out.mkdir()
    object.__setattr__(config.wikidata, "batch_size", 1)
    make = lambda n: "\n".join(
        json.dumps({**CANDIDATE, "page_id": i, "title": f"T{i}", "revision_id": str(i)}) for i in range(1, n + 1)
    ) + "\n"
    (out / "candidates.jsonl").write_text(make(2), encoding="utf-8")
    (out / "films.jsonl.part").write_text("STALE\n")
    (out / "enrich_checkpoint.json").write_text(json.dumps({
        "snapshot_id": config.wikidata.snapshot_id, "batch_size": 1, "input": "different",
        "batches_done": 1, "written": 1, "rejected": 0, "films_bytes": 6, "rejected_bytes": 0}))
    (out / "rejected_records.jsonl").write_text("")
    run_enrich(config, _client(config, FakeWikidata()))
    assert b"STALE" not in (out / "films.jsonl").read_bytes()


def test_invalid_records_go_to_rejected_records_and_do_not_stop_the_run(config, tmp_path):
    out = tmp_path / "processed"
    out.mkdir()
    bad = {**CANDIDATE, "page_id": 7, "title": "Durata Assurda", "infobox": {"durata": "9000 min"}}
    good = {**CANDIDATE, "page_id": 8, "title": "Film Uno"}
    (out / "candidates.jsonl").write_text(json.dumps(bad) + "\n" + json.dumps(good) + "\n", encoding="utf-8")
    summary = run_enrich(config, _client(config, FakeWikidata()))
    assert summary["films"] == 1 and summary["rejected"] == 1
    problem = json.loads((out / "rejected_records.jsonl").read_text().splitlines()[0])
    assert problem["page_id"] == 7 and problem["reason"] == "schema_validation"
    assert "duration_minutes" in problem["errors"][0]


def test_labels_come_from_one_sparql_post_per_thousand_ids_and_replay_offline(config, tmp_path):
    from pipelines.wikipedia_films.enrich_metadata import label_query, labels_for_ids

    fake = FakeWikidata()
    client = _client(config, fake)
    labels = labels_for_ids(client, ["Q2001", "Q2003", "Q4001", "Q9999"])
    assert fake.sparql_batches == [4] and client.network_requests == 1
    assert labels["Q2001"]["labels"]["it"]["value"] == "Anna Bianchi"
    assert labels["Q2003"]["labels"] == {"en": {"language": "en", "value": "Maria Neri"}}
    assert "Q9999" not in labels  # no label: absent, never invented
    assert fake.calls[0]["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    object.__setattr__(config.wikidata, "mode", "offline")
    offline = _client(config, FakeWikidata())
    assert labels_for_ids(offline, ["Q2001", "Q2003", "Q4001", "Q9999"]) == labels
    assert offline.network_requests == 0 and offline.snapshot_hits == 1
    with pytest.raises(ValueError):
        label_query(["Q1} UNION {?s ?p ?o"], ["it"])  # no free text can reach the query
    with pytest.raises(ValueError):
        label_query(["Q1"], ['it") ) } #'])


def test_a_failing_big_label_batch_is_retried_in_halves(config):
    from pipelines.wikipedia_films.enrich_metadata import labels_for_ids

    class TooBig(FakeWikidata):
        def _sparql(self, url, headers, data):
            import re

            if len(re.findall(r"wd:Q\d+", urllib.parse.parse_qs(data.decode())["query"][0])) > 60:
                return 504, {}, b""
            return super()._sparql(url, headers, data)

    import urllib.parse

    object.__setattr__(config.wikidata, "max_retries", 1)
    fake = TooBig()
    ids = [f"Q{n}" for n in range(1, 101)]
    ids[0] = "Q2001"
    labels = labels_for_ids(_client(config, fake), ids)
    assert fake.sparql_batches == [50, 50] and "Q2001" in labels


def test_wikidata_placeholder_dates_and_durations_are_ignored_not_fatal(config):
    def date(time, precision=9):
        return {"rank": "normal", "mainsnak": {"snaktype": "value", "datavalue": {
            "value": {"time": time, "precision": precision}}}}

    entity = {"id": "Q1", "claims": {"P577": [date("+2002-05-16T00:00:00Z", 11), date("+0001-00-00T00:00:00Z")]}}
    assert year_from_wikidata(entity) == 2002  # the 0001 placeholder is not "the earliest release"
    assert year_from_wikidata({"claims": {"P577": [date("+0001-00-00T00:00:00Z")]}}) is None
    huge = {"claims": {"P2047": [{"rank": "normal", "mainsnak": {"snaktype": "value", "datavalue": {
        "value": {"amount": "+999999", "unit": "http://www.wikidata.org/entity/Q7727"}}}}]}}
    assert duration_from_wikidata(huge) is None
    record = derive_record({**CANDIDATE, "infobox": {"anno uscita": "1990"}}, {**entity, "claims": {
        "P577": [date("+0001-00-00T00:00:00Z")]}}, {}, config=config)
    FilmRecord.model_validate(record)
    assert record["year"] == 1990  # falls back to the infobox instead of rejecting the film


def test_a_checkpoint_of_an_older_derivation_is_not_resumed(config, tmp_path, monkeypatch):
    import pipelines.wikipedia_films.enrich_metadata as em

    out = tmp_path / "processed"
    out.mkdir()
    object.__setattr__(config.wikidata, "batch_size", 1)
    rows = [{**CANDIDATE, "page_id": i, "title": f"T{i}", "revision_id": str(i)} for i in (1, 2)]
    (out / "candidates.jsonl").write_text("\n".join(json.dumps(c) for c in rows) + "\n", encoding="utf-8")

    class Boom(FakeWikidata):
        def __call__(self, url, headers, timeout, data=None):
            if "T2" in url:
                raise KeyboardInterrupt
            return super().__call__(url, headers, timeout, data)

    with pytest.raises(KeyboardInterrupt):
        run_enrich(config, _client(config, Boom()))
    assert json.loads((out / "enrich_checkpoint.json").read_text())["batches_done"] == 1
    monkeypatch.setattr(em, "DERIVATION_VERSION", em.DERIVATION_VERSION + 1)
    fake = FakeWikidata()
    client = _client(config, fake)
    summary = run_enrich(config, client)
    # batch 1 was re-derived from the snapshot (hits, no network), batch 2 was fetched
    assert summary["films"] == 2 and client.snapshot_hits == 1
    assert [c["params"]["titles"] for c in fake.calls if "titles" in c["params"]] == ["T2"]
