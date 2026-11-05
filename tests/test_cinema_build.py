"""The offline build on a miniature of the local sources: rows, provenance, gaps, reproducibility, read-only inputs, no network."""
from __future__ import annotations

import hashlib
import json
import socket
import sqlite3
from pathlib import Path

import pytest
from cinema_build_support import input_files, make_inputs

from cinema_db.harness.build import extract as X
from cinema_db.harness.build.build import run_build
from cinema_db.harness.build.common import italian_date, normalize_name, wikipedia_title
from cinema_db.harness.build.genres import map_label
from cinema_db.schema import check_fts
from tool.cinema_db.approved_views import POLICY
from tool.cinema_db.connection import open_database
from tool.cinema_db.executor import execute
from tool.cinema_db.validator import validate


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("build")
    inputs = make_inputs(tmp)
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in input_files(inputs)}
    out = tmp / "out" / "cinema.sqlite3"
    report = run_build(out, inputs, log=lambda *_: None)
    after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in input_files(inputs)}
    conn = sqlite3.connect(out)
    yield {"conn": conn, "out": out, "report": report, "inputs": inputs, "before": before, "after": after, "tmp": tmp}
    conn.close()


def q(built, sql, *p):
    return built["conn"].execute(sql, p).fetchall()


def test_the_build_leaves_the_inputs_untouched_and_is_consistent(built):
    assert built["before"] == built["after"]
    assert q(built, "PRAGMA foreign_key_check") == [] and q(built, "PRAGMA integrity_check") == [("ok",)]
    assert check_fts(built["conn"]) == []
    assert q(built, "SELECT count(*) FROM sqlite_master WHERE type='trigger'") == [(0,)]
    assert not list(built["out"].parent.glob("*.building"))


def test_films_get_kind_year_runtime_and_names(built):
    assert q(built, "SELECT title, kind, year, runtime_min, original_title FROM v_work WHERE wikidata_id = 'Q9001'") == [("Film di prova", "film", 1982, 109, "Test Film")]
    assert q(built, "SELECT kind, runtime_min FROM v_work WHERE wikidata_id = 'Q9003'") == [("short", 20)]
    assert q(built, "SELECT kind FROM v_work WHERE wikidata_id = 'Q9005'") == [("tv_film",)]  # (merged with the series catalogue's record)
    assert q(built, "SELECT kind, wikidata_id FROM v_work WHERE title = 'Senza Wikidata'") == [("film", None)]  # no QID: still imported, found by its page
    # the Italian label is primary; the English label, the original title and the page title are alternative names
    names = q(built, "SELECT name, name_kind, language FROM v_name WHERE entity_id = (SELECT work_id FROM v_work WHERE wikidata_id = 'Q9001') ORDER BY name_kind, name")
    assert ("Film di prova", "primary", "it") in names and ("Sample Film", "translated", "en") in names and ("Test Film", "original", None) in names


def test_the_release_date_is_kept_only_when_it_agrees_with_the_catalogue_year(built):
    assert q(built, "SELECT release_date FROM v_work WHERE wikidata_id = 'Q9001'") == [("1982-06-25",)]
    assert q(built, "SELECT release_date FROM v_work WHERE wikidata_id = 'Q9004'") == [(None,)]  # no date in Wikidata: nothing invented


def test_identifiers_are_normalised_multiple_and_conflicts_are_reported_not_hidden(built):
    ids = dict(q(built, "SELECT scheme, value FROM v_external_id WHERE entity_id = (SELECT work_id FROM v_work WHERE wikidata_id='Q9001') AND is_primary = 1"))
    assert ids["imdb_title"] == "tt9000001" and ids["tmdb_movie"] == "9001" and ids["eidr"] == "10.5240/AAAA" and ids["wikipedia_it"] == "Film_di_prova"
    # Wikidata says tt9000002 for Q9001; the catalogue says tt9000001: both kept, the catalogue's is the preferred one
    assert q(built, "SELECT value, is_primary FROM v_external_id WHERE entity_id = (SELECT work_id FROM v_work WHERE wikidata_id='Q9001') AND scheme='imdb_title' ORDER BY is_primary DESC") == [("tt9000001", 1), ("tt9000002", 0)]
    # Q9004 also claims tt9000002 (already taken): dropped for it and counted
    assert q(built, "SELECT count(*) FROM v_external_id WHERE scheme='imdb_title' AND value='tt9000002'") == [(1,)]
    assert built["report"]["skipped"]["id_conflict:imdb_title"] >= 1


def test_credits_exist_only_for_people_the_local_sources_name(built):
    rows = q(built, "SELECT role, person_name, character_name FROM v_credit WHERE work_title = 'Film di prova' ORDER BY role, person_name")
    assert ("director", "Ann Regista", None) in rows
    assert ("cast", "Bob Attore", "Eroe") in rows  # the character on the Wikidata claim wins over the catalogue's
    assert ("cast", "Cara Attrice", None) in rows  # a name that only the catalogue knows
    assert not [r for r in rows if r[0] == "writer"]  # the unnamed writer is NOT imported (no name is invented)
    assert built["report"]["skipped"]["credit_unnamed_person:writer"] == 1
    assert q(built, "SELECT count(*) FROM person") == [(3,)]


def test_genres_keep_source_labels_and_map_to_the_canonical_vocabulary(built):
    assert sorted(r[0] for r in q(built, "SELECT genre FROM v_work_genre WHERE work_title = 'Film di prova'")) == ["Drama", "Thriller"]
    labels = q(built, "SELECT label_it, label_en, genre, mapping FROM v_work_genre_label WHERE work_title = 'Film di prova' ORDER BY label_it, label_en")
    assert ("film drammatico", "drama film", "Drama", "exact") in labels
    assert ("film strano", None, None, None) in labels  # unmapped but present
    assert (None, "psychological thriller", "Thriller", "specific") in labels
    assert q(built, "SELECT count(*) FROM genre_label WHERE wikidata_id IS NOT NULL") [0][0] >= 4
    # a label only in English is still a label
    assert q(built, "SELECT genre FROM v_work_genre WHERE work_title = 'Solo inglese' ORDER BY genre") == [("Comedy",), ("Drama",), ("Romance",), ("Romantic comedy",)]


def test_countries_languages_releases_money_franchise_companies(built):
    assert q(built, "SELECT country, role FROM v_work_country WHERE work_title = 'Film di prova'") == [("Italy", "origin")]
    assert q(built, "SELECT iso2 FROM v_work_country WHERE work_title = 'Film di prova'") == [(None,)]  # ISO codes are a phase-4 gap, not guessed
    assert q(built, "SELECT language FROM v_work_language WHERE work_title = 'Film di prova'") == [("Italian",)]
    assert q(built, "SELECT country, release_date, release_kind FROM v_work_release WHERE work_title = 'Film di prova'") == [("Italy", "1982-06-25", "unspecified")]
    money = q(built, "SELECT kind, scope, amount, currency FROM v_work_financial WHERE work_title = 'Film di prova' ORDER BY kind")
    assert money == [("box_office", "worldwide", 20000000, "USD"), ("budget", "unspecified", 1500000, "USD")]  # the non-USD budget is not imported
    assert built["report"]["skipped"]["money_unit_not_imported:Q9999"] == 1
    assert q(built, "SELECT franchise, basis FROM v_franchise WHERE work_title = 'Film di prova'") == [("Saga di prova", "wikidata_franchise")]
    assert q(built, "SELECT company, role FROM v_work_company WHERE work_title = 'Film di prova'") == [("Casa di Prova", "production")]
    assert built["report"]["counts"]["award_statements_not_imported"] == 1  # awards need names the local sources lack


def test_relations_link_known_works_and_label_only_targets_become_other_works(built):
    rels = q(built, "SELECT relation, direction, related_title, related_kind FROM v_work_relation WHERE work_title = 'Film di prova' ORDER BY relation, direction")
    assert ("based_on", "forward", "Romanzo di prova", "other") in rels
    assert ("follows", "forward", "Prequel di prova", "short") in rels
    # Q9003 says "followed by Q9001": the same fact from the other side must not duplicate it
    assert q(built, "SELECT count(*) FROM work_relation WHERE relation = 'follows'") == [(1,)]
    assert q(built, "SELECT count(*) FROM v_work WHERE wikidata_id = 'Q9998'") == [(0,)]  # an unnamed target is skipped, not invented
    assert built["report"]["skipped"]["relation_target_without_label:based_on"] == 1


def test_series_are_imported_only_when_eligible_and_use_wikidata_only_when_ids_are_reliable(built):
    assert q(built, "SELECT title, kind, year, end_year FROM v_work WHERE kind IN ('series','miniseries') ORDER BY title") == [
        ("Miniserie di prova", "miniseries", 2020, None), ("Serie di prova", "series", 2016, 2018), ("Serie dubbia", "series", 2010, None)]
    assert q(built, "SELECT count(*) FROM v_work WHERE title = 'Pagina mista'") == [(0,)]  # not eligible by default
    assert q(built, "SELECT count(*) FROM v_credit WHERE work_title = 'Serie dubbia'") == [(0,)]  # unreliable QID: its Wikidata facts are not used
    assert q(built, "SELECT count(*) FROM v_external_id e JOIN v_work w ON w.work_id = e.entity_id WHERE w.title = 'Serie dubbia' AND e.scheme IN ('imdb_title','wikidata')") == [(0,)]
    assert q(built, "SELECT person_name FROM v_credit WHERE work_title = 'Serie di prova'") == [("Bob Attore",)]
    ids = dict(q(built, "SELECT scheme, value FROM v_external_id WHERE entity_id = (SELECT work_id FROM v_work WHERE title='Serie di prova')"))
    assert ids["imdb_title"] == "tt9100001" and ids["tmdb_tv"] == "5555" and ids["wikidata"] == "Q9801"
    # catalogue text genres and countries resolve; unknown text stays visible/unmapped or is counted
    assert sorted(r[0] for r in q(built, "SELECT genre FROM v_work_genre WHERE work_title = 'Serie di prova'")) == ["Action", "Drama"]
    assert q(built, "SELECT company, role FROM v_work_company WHERE work_title = 'Serie di prova'") == [("Rai Uno", "network")]
    assert built["report"]["skipped"]["series_country_text_not_a_known_country"] == 1
    assert built["report"]["skipped"]["genre_text_without_letters"] == 1  # a genre that is only punctuation is not a label


def test_seasons_and_episodes_hang_from_their_parents_with_numbers_and_dates(built):
    assert q(built, "SELECT s.title, s.season_number, p.title FROM v_work s JOIN v_work p ON p.work_id = s.parent_work_id WHERE s.kind = 'season' ORDER BY s.title") == [
        ("Serie di prova – stagione 1", 1, "Serie di prova"), ("Serie di prova – stagione 2", 2, "Serie di prova")]
    assert built["report"]["skipped"]["season_without_imported_series"] == 1
    eps = q(built, "SELECT e.title, e.season_number, e.episode_number, e.release_date, p.title FROM v_work e JOIN v_work p ON p.work_id = e.parent_work_id WHERE e.kind = 'episode' ORDER BY e.title")
    assert ("Pilota", 1, 1, "2016-07-15", "Serie di prova – stagione 1") in eps
    assert ("Ritorno", 2, 1, None, "Serie di prova – stagione 2") in eps  # unparsable date: left empty, counted
    assert ("Speciale", None, None, "2017-12", "Serie di prova") in eps  # no number: hangs from the series
    assert not [e for e in eps if e[0] == "Pilota (riga)"]  # the table row of an episode that has its own page is not repeated
    assert built["report"]["skipped"]["episode_without_imported_series"] == 1
    assert q(built, "SELECT value FROM v_external_id WHERE scheme = 'imdb_title' AND entity_id = (SELECT work_id FROM v_work WHERE title = 'Pilota')") == [("tt9200001",)]
    assert q(built, "SELECT name FROM v_name WHERE name_kind = 'original' AND entity_id = (SELECT work_id FROM v_work WHERE title = 'Pilota')") == [("Pilot",)]


def test_a_work_in_both_catalogues_becomes_one_work_decided_by_the_series_catalogue(built):
    # film catalogue "Only English" (Q9005) and series catalogue "Solo inglese" are the same page and the same Wikidata item
    rows = q(built, "SELECT work_id, title, kind, source FROM v_work WHERE wikidata_id = 'Q9005'")
    assert len(rows) == 1 and rows[0][1:3] == ("Solo inglese", "tv_film")
    names = {r[0] for r in q(built, "SELECT name FROM v_name WHERE entity_id = ?", rows[0][0])}
    assert {"Solo inglese", "Only English"} <= names  # the other catalogue's title survives as an alternative name
    assert built["report"]["counts"]["works_merged_film_into_series_catalog"] == 1
    # the same genre asserted by both snapshots is stored once and the repeat is counted
    assert built["report"]["counts"]["assertion_repeated_from_another_source:work_genre"] >= 1
    assert q(built, "SELECT count(*) FROM work_genre g JOIN genre_label l ON l.label_id = g.label_id WHERE g.work_id = ? AND l.wikidata_id = 'Q9204'", rows[0][0]) == [(1,)]
    assert q(built, "SELECT count(*) FROM v_work WHERE title IN ('Only English', 'Solo inglese')") == [(1,)]
    # facts of the film catalogue are added: the English-only genre of the Wikidata item reaches the merged work
    assert ("Romantic comedy",) in q(built, "SELECT genre FROM v_work_genre WHERE work_id = ?", rows[0][0])


def test_tv_films_are_works_of_their_own_kind(built):
    assert q(built, "SELECT kind, year, imdb_id, tmdb_id FROM v_work WHERE title = 'Film TV di prova'") == [("tv_film", 2003, "tt9300001", "777")]
    assert q(built, "SELECT genre FROM v_work_genre WHERE work_title = 'Film TV di prova' ORDER BY genre") == [("Comedy",), ("Drama",)]


def test_every_work_has_one_primary_name_a_source_and_a_valid_hierarchy(built):
    assert q(built, "SELECT count(*) FROM work w WHERE (SELECT count(*) FROM entity_name n WHERE n.entity_id = w.work_id AND n.is_primary = 1) <> 1") == [(0,)]
    assert q(built, "SELECT count(*) FROM person p WHERE (SELECT count(*) FROM entity_name n WHERE n.entity_id = p.person_id AND n.is_primary = 1) <> 1") == [(0,)]
    assert q(built, "SELECT count(*) FROM work WHERE kind IN ('season','episode') AND parent_work_id IS NULL") == [(0,)]
    assert q(built, "SELECT count(*) FROM (SELECT source_id FROM work UNION ALL SELECT source_id FROM credit UNION ALL SELECT source_id FROM external_id) WHERE source_id IS NULL") == [(0,)]


def test_provenance_names_the_source_licence_and_snapshot_hashes(built):
    rows = q(built, "SELECT name, usage_scope, attribution_required, snapshot_sha256 IS NOT NULL FROM v_source ORDER BY source_id") if False else q(built, "SELECT name, usage_scope, attribution_required FROM source ORDER BY source_id")
    assert rows == [("wikidata-film-snapshot", "open_public_domain", 0), ("wikidata-series-snapshot", "open_public_domain", 0), ("film-catalog-v3", "open_share_alike", 1), ("series-catalog-s5", "open_share_alike", 1), ("cinema-db-genre-vocabulary", "unverified", 0)]
    assert q(built, "SELECT count(*) FROM source WHERE snapshot_sha256 IS NOT NULL AND length(snapshot_sha256) = 64") == [(4,)]
    assert q(built, "SELECT source FROM v_credit WHERE person_name = 'Ann Regista' LIMIT 1") == [("wikidata-film-snapshot",)]


def test_the_database_opens_under_the_real_policy_and_answers_through_the_guard(built):
    g = open_database(built["out"], POLICY)
    try:
        res = execute(g, validate("SELECT entity_id, name FROM v_title_search WHERE search MATCH ? ORDER BY rank LIMIT 5", ["prova*"], POLICY))
        assert res.rows
        res = execute(g, validate("SELECT title FROM v_work WHERE imdb_id = ?", ["tt9000001"], POLICY))
        assert res.rows == (("Film di prova",),)
    finally:
        g.close()


def test_the_build_is_reproducible_refuses_to_overwrite_and_keeps_the_previous_file(built):
    again = built["tmp"] / "again" / "c.sqlite3"
    report = run_build(again, built["inputs"], log=lambda *_: None)
    assert report["content_sha256"] == built["report"]["content_sha256"]
    assert q(built, "SELECT value FROM build_info WHERE key = 'content_sha256'") == [(built["report"]["content_sha256"],)]
    with pytest.raises(FileExistsError):
        run_build(again, built["inputs"], log=lambda *_: None)
    run_build(again, built["inputs"], force=True, log=lambda *_: None)
    assert again.with_name("c.sqlite3.previous").exists()


def test_the_build_never_touches_the_network(tmp_path, monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("the offline build tried to open a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    run_build(tmp_path / "x.sqlite3", make_inputs(tmp_path / "in") if (tmp_path / "in").mkdir() is None else None, log=lambda *_: None)


def test_a_failing_build_leaves_no_database_and_no_temporary_file(tmp_path):
    inputs = make_inputs(tmp_path / "in") if (tmp_path / "in").mkdir() is None else None
    inputs.film_catalog.write_text('{"film_id": "Q1", "wikidata_id": null, "title": "", "year": 1}\n', encoding="utf-8")  # a record the build cannot name
    out = tmp_path / "bad.sqlite3"
    with pytest.raises(Exception):
        run_build(out, inputs, log=lambda *_: None)
    assert not out.exists()


# --- pure helpers -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [({"time": "+1982-06-25T00:00:00Z", "precision": 11}, "1982-06-25"), ({"time": "+1982-06-00T00:00:00Z", "precision": 10}, "1982-06"), ({"time": "+1972-00-00T00:00:00Z", "precision": 9}, "1972"),
     ({"time": "+1982-06-25T00:00:00Z", "precision": 8}, None), ({"time": "-0044-03-15T00:00:00Z", "precision": 11}, None), ({"time": "+1982-00-00T00:00:00Z", "precision": 11}, "1982"), ("x", None)],
)
def test_wikidata_dates_follow_their_precision(value, expected):
    assert X.iso_date(value) == expected


def test_quantities_are_whole_non_negative_amounts_with_a_unit_item():
    ok = {"datavalue": {"value": {"amount": "+1500000", "unit": "http://www.wikidata.org/entity/Q4917"}}}
    assert X.quantity(ok) == (1500000, "Q4917")
    for bad in ("+1.5", "-3"):
        assert X.quantity({"datavalue": {"value": {"amount": bad, "unit": "http://www.wikidata.org/entity/Q4917"}}}) is None
    assert X.quantity({"datavalue": {"value": {"amount": "+3", "unit": "1"}}}) is None


@pytest.mark.parametrize(("text", "expected"), [("23 marzo 2008", "2008-03-23"), ("1º gennaio 2000", "2000-01-01"), ("marzo 2008", "2008-03"), ("2008", "2008"), ("14 ottobre 2024 (Hulu)", "2024-10-14"), ("data sconosciuta", None), ("32 marzo 2008", None), ("14 dicembre 1988 Ci sono dubbi", None), ("", None), (None, None)])
def test_italian_dates(text, expected):
    assert italian_date(text) == expected


def test_names_are_normalised_without_losing_other_scripts():
    assert normalize_name("  Così è la VITA — L'été ") == "cosi e la vita l ete"
    assert normalize_name("北斗の拳") == "北斗の拳"
    assert wikipedia_title("https://it.wikipedia.org/wiki/Il_pianista_(film_2002)") == "Il_pianista_(film_2002)"


@pytest.mark.parametrize(
    ("it", "en", "expected"),
    [("film dell'orrore", "horror film", {("horror", "exact")}), ("film giallo", "crime film", {("crime", "exact"), ("mystery", "synonym")}),
     ("commedia romantica", "romantic comedy", {("comedy", "specific"), ("romantic_comedy", "exact"), ("romance", "specific")}), (None, "psychological thriller", {("thriller", "specific")}),
     ("film muto", "silent film", {("silent", "exact")}), ("buddy film", "buddy film", set()), ("azione", None, {("action", "exact")}), (None, None, set())],
)
def test_genre_mapping_rules(it, en, expected):
    assert {(c, k) for c, k, _ in map_label(it, en)} == expected


def test_the_verification_helpers_run_on_a_built_database(built):
    from cinema_db.harness.build import verify as V

    conn = sqlite3.connect(built["out"])
    try:
        i = V.integrity(conn, built["out"])
        assert i["foreign_key_check_rows"] == 0 and i["integrity_check"] == "ok" and i["content_digest_matches"] and i["policy_accepts_the_file"] and not i["invariant_problems"]
        cov = V.coverage(conn)
        assert cov["film_catalog_works"] == 4 and cov["with_director"]["n"] >= 1 and cov["genre_assertions"]["pct_mapped"] > 0
        assert V.counts(conn)["work"] > 0
    finally:
        conn.close()
    assert [q["label"] for q in V.run_queries(built["out"])]  # every demo query is accepted by the guard (they may return no rows on a miniature)
    assert all("error" not in q for q in V.run_queries(built["out"]))
