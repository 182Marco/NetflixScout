"""FASE 21: identifiers with a wrong shape (the `nm…` person id stored as the IMDb title id of *Tumbling*), their correction by a verified override, and the check on the real
candidate. The mini world is the one of the layer tests."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from cinema_db.harness.audit import util
from cinema_db.harness.build import id_rules as R
from cinema_db.harness.build import imdb_layer as layer
from test_cinema_imdb_layer import _t, world  # noqa: F401  (fixture and staging helper of the layer tests)

ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------------------------------------------------- the rules themselves
def test_the_shape_of_every_checked_scheme() -> None:
    ok = {"imdb_title": "tt0000001", "imdb_name": "nm0000001", "wikidata": "Q42", "tmdb_movie": "603", "tmdb_tv": "1396", "tmdb_person": "6193", "tvdb_series": "169861"}
    assert all(R.has_valid_shape(s, v) for s, v in ok.items())
    bad = {"imdb_title": ["nm1627110", "tt123", "TT0000001", "tt0000001 ", ""], "imdb_name": ["tt0000001", "nm12"], "wikidata": ["42", "q42", "Q0", "P345"], "tmdb_movie": ["0", "12a", ""]}
    assert not any(R.has_valid_shape(s, v) for s, vs in bad.items() for v in vs)
    assert R.has_valid_shape("wikipedia_it", "anything at all") and R.has_valid_shape("eidr", "10.5240/0000-40B8-6A21-DB8F-14F7-A")   # schemes without a pattern are not checked


def test_the_packaged_override_is_complete_and_audited() -> None:
    overrides = R.load_overrides()
    entry = overrides[("imdb_title", "nm1627110", "wp-4059646")]
    assert entry["action"] == "replace" and entry["value"] == "tt1627110" and len(entry["evidence"]) >= 4
    assert R.has_valid_shape("imdb_title", entry["value"]) and not R.has_valid_shape("imdb_title", entry["rejected"])


@pytest.mark.parametrize("entry, message", [
    ({"id": "x", "scheme": "imdb_title", "rejected": "nm1", "source_ref": "r", "action": "replace", "value": "nm2", "evidence": ["e"]}, "valid imdb_title"),
    ({"id": "x", "scheme": "imdb_title", "rejected": "nm1", "source_ref": "r", "action": "replace", "evidence": ["e"]}, "valid imdb_title"),
    ({"id": "x", "scheme": "imdb_title", "rejected": "nm1", "source_ref": "r", "action": "invent", "evidence": ["e"]}, "action must be"),
    ({"id": "x", "scheme": "imdb_title", "rejected": "nm1", "source_ref": "r", "action": "drop"}, "evidence"),
    ({"scheme": "imdb_title", "rejected": "nm1", "source_ref": "r", "action": "drop", "evidence": ["e"]}, "'id'"),
])
def test_a_correction_nobody_can_audit_is_refused(tmp_path, entry, message) -> None:
    path = tmp_path / "o.json"
    path.write_text(json.dumps({"overrides": [entry]}))
    with pytest.raises(ValueError, match=message):
        R.load_overrides(path)


def test_two_overrides_for_the_same_record_are_refused(tmp_path) -> None:
    e = {"id": "a", "scheme": "imdb_title", "rejected": "nm1", "source_ref": "r", "action": "drop", "evidence": ["e"]}
    path = tmp_path / "o.json"
    path.write_text(json.dumps({"overrides": [e, {**e, "id": "b"}]}))
    with pytest.raises(ValueError, match="duplicate"):
        R.load_overrides(path)


# --------------------------------------------------------------------------------------------------------------- the layer builder
def _add(inputs, tmp_path, overrides):
    c = sqlite3.connect(inputs.base)
    st = sqlite3.connect(tmp_path / "st.sqlite3")

    def series(wid, title, year, bad, ref):
        c.execute("INSERT INTO entity VALUES (?, 'work')", (wid,))
        c.execute("INSERT INTO work (work_id, kind, release_year, source_id, source_ref) VALUES (?, 'series', ?, 1, ?)", (wid, year, ref))
        c.execute("INSERT INTO entity_name (entity_id, name, name_norm, kind, is_primary, source_id) VALUES (?,?,?,'primary',1,1)", (wid, title, util.norm_title(title)))
        c.execute("INSERT INTO external_id (entity_id, scheme, value, is_primary, source_id, source_ref) VALUES (?,'imdb_title',?,1,1,?)", (wid, bad, ref))

    series(90, "Tumbling", 2010, "nm1627110", "wp-4059646")             # the real case: a verified correction exists
    series(91, "No evidence", 2011, "nm5550001", "wp-9100001")           # no correction: the identifier stays absent
    series(92, "Wrong type", 2012, "nm5550002", "wp-9200001")            # the proposed replacement is a film
    series(93, "Taken", 2010, "nm5550003", "wp-9300001")                 # the proposed replacement (a series of 2010) already identifies "Show"
    series(94, "Far year", 2014, "nm5550004", "wp-9400001")              # the proposed replacement is from another year
    series(95, "Not in IMDb", 2015, "nm5550005", "wp-9500001")           # the proposed replacement is unknown to IMDb
    c.commit(); c.close()
    _t(st, "tt1627110", "tvSeries", "Tanburingu", 2010, 58)
    _t(st, "tt0000191", "movie", "Wrong type", 2012, 90)
    _t(st, "tt0000194", "tvSeries", "Far year", 1999)
    st.commit(); st.close()
    entries = [
        {"id": "tumbling", "scheme": "imdb_title", "rejected": "nm1627110", "source_ref": "wp-4059646", "action": "replace", "value": "tt1627110", "evidence": ["test"]},
        {"id": "wrong-type", "scheme": "imdb_title", "rejected": "nm5550002", "source_ref": "wp-9200001", "action": "replace", "value": "tt0000191", "evidence": ["test"]},
        {"id": "taken", "scheme": "imdb_title", "rejected": "nm5550003", "source_ref": "wp-9300001", "action": "replace", "value": "tt0000020", "evidence": ["test"]},
        {"id": "far-year", "scheme": "imdb_title", "rejected": "nm5550004", "source_ref": "wp-9400001", "action": "replace", "value": "tt0000194", "evidence": ["test"]},
        {"id": "unknown", "scheme": "imdb_title", "rejected": "nm5550005", "source_ref": "wp-9500001", "action": "replace", "value": "tt0000099", "evidence": ["test"]},
        {"id": "other-record", "scheme": "imdb_title", "rejected": "nm5550001", "source_ref": "a-different-record", "action": "replace", "value": "tt0000001", "evidence": ["test"]},   # same value, other record: must not apply
    ]
    path = tmp_path / "overrides.json"
    path.write_text(json.dumps({"overrides": entries}))
    return path


def test_wrong_shape_identifiers_are_removed_and_only_a_verified_correction_replaces_them(world) -> None:  # noqa: F811
    inputs, tmp = world
    inputs.id_overrides = _add(inputs, tmp, None)
    layer.run_layer(inputs, tmp / "v3.sqlite3", log=lambda *_: None)
    c = sqlite3.connect(tmp / "v3.sqlite3")
    ids = lambda w: c.execute("SELECT value, is_primary, source_ref FROM external_id WHERE entity_id = ? AND scheme = 'imdb_title'", (w,)).fetchall()
    # no title identifier of the file has a wrong shape any more (the mini archive invents person ids like 'nm1': only the base identifiers are the subject here)
    assert [v for v in R.violations(c) if v[1] == "imdb_title"] == []
    # the verified correction: the right id, still the preferred one, with its provenance
    assert [(v, p, r) for v, p, r in ids(90)] == [("tt1627110", 1, "override:tumbling")]
    assert c.execute("SELECT value FROM entity_claim WHERE entity_id = 90 AND field = 'imdb_title_rejected'").fetchall() == [("nm1627110",)]
    assert c.execute("SELECT value FROM entity_claim WHERE entity_id = 90 AND field = 'imdb_title_override'").fetchall() == [("nm1627110 -> tt1627110",)]
    # no correction, or one that fails its checks: the identifier is absent, the rejected value is kept as a claim
    for wid, rejected in ((91, "nm5550001"), (92, "nm5550002"), (93, "nm5550003"), (94, "nm5550004"), (95, "nm5550005")):
        assert ids(wid) == [], wid
        assert c.execute("SELECT value FROM entity_claim WHERE entity_id = ? AND field = 'imdb_title_rejected'", (wid,)).fetchall() == [(rejected,)]
    assert c.execute("SELECT value FROM external_id WHERE entity_id = 1 AND scheme = 'imdb_title'").fetchall() == [("tt0000001",)]   # Alpha keeps its own id
    # the report: every case, with the reason of a refusal
    archive = {r["entity_id"]: r for r in map(json.loads, (tmp / "v3.separate" / "invalid_ids.jsonl").read_text().splitlines())}
    assert archive[90]["result"] == "replaced" and archive[90]["value"] == "tt1627110"
    assert "not compatible" in archive[92]["refused"] and "another entity" in archive[93]["refused"] and "differs" in archive[94]["refused"] and "not in the IMDb archive" in archive[95]["refused"]
    assert archive[91]["result"] == "dropped" and "override" not in archive[91]
    report = json.loads((tmp / "v3.layer_report.json").read_text())["counts"]
    assert report["id_wrong_shape:imdb_title"] == 6 and report["id_override_replaced:imdb_title"] == 1 and report["id_override_refused:imdb_title"] == 4 and report["id_dropped:imdb_title"] == 1


def test_a_clean_base_is_untouched_by_the_check(world) -> None:  # noqa: F811
    inputs, tmp = world
    base = sqlite3.connect(inputs.base)
    before = base.execute("SELECT entity_id, scheme, value, is_primary FROM external_id ORDER BY 1,2,3").fetchall()
    assert R.violations(base) == []
    layer.run_layer(inputs, tmp / "v3.sqlite3", log=lambda *_: None)
    c = sqlite3.connect(tmp / "v3.sqlite3")
    assert c.execute("SELECT count(*) FROM entity_claim WHERE field LIKE '%_rejected' OR field LIKE '%_override'").fetchone()[0] == 0
    assert not (tmp / "v3.separate" / "invalid_ids.jsonl").exists() or (tmp / "v3.separate" / "invalid_ids.jsonl").read_text() == ""
    kept = {(e, s, v) for e, s, v, _ in before}
    assert kept <= set(c.execute("SELECT entity_id, scheme, value FROM external_id").fetchall())


# --------------------------------------------------------------------------------------------------------------- the real candidate
CANDIDATE = ROOT / "cinema_db/data/cinema.v4.candidate6.sqlite3"


@pytest.mark.skipif(not CANDIDATE.is_file(), reason="needs the schema-4 candidate")
def test_the_expected_candidate_has_no_identifier_with_the_wrong_shape_and_tumbling_is_corrected() -> None:
    conn = sqlite3.connect(f"file:{CANDIDATE}?mode=ro&immutable=1", uri=True)
    assert R.violations(conn) == []
    assert conn.execute("SELECT value FROM external_id WHERE entity_id = 35942 AND scheme = 'imdb_title'").fetchall() == [("tt1627110",)]
    assert conn.execute("SELECT field FROM entity_claim WHERE entity_id = 35942 AND field LIKE 'imdb_title_%' ORDER BY field").fetchall() == [("imdb_title_override",), ("imdb_title_rejected",)]
