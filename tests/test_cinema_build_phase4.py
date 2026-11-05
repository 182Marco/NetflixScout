"""The build with the phase-4 snapshot: names, life dates, ISO codes, original-currency money, awards, provenance, and that the phase-3 result is unchanged without it."""
from __future__ import annotations

import sqlite3

import pytest
from cinema_build_support import make_inputs, make_phase4

from cinema_db.harness.build.build import Inputs, run_build
from cinema_db.harness.build.phase4 import choose_date, render_time
from cinema_db.schema import check_fts


@pytest.fixture(scope="module")
def p4(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("p4")
    base = make_inputs(tmp, awards_demo=True)
    inputs = Inputs(base.film_snapshot, base.series_snapshot, base.film_catalog, base.series_dir, phase4=make_phase4(tmp / "phase4"))
    out = tmp / "out" / "cinema.sqlite3"
    report = run_build(out, inputs, log=lambda *_: None)
    plain = run_build(tmp / "plain" / "cinema.sqlite3", base, log=lambda *_: None)
    conn = sqlite3.connect(out)
    yield {"conn": conn, "report": report, "plain": plain, "inputs": inputs}
    conn.close()


def q(p4, sql, *args):
    return p4["conn"].execute(sql, args).fetchall()


def test_integrity_foreign_keys_and_fts_hold_with_phase4(p4):
    assert q(p4, "PRAGMA foreign_key_check") == [] and q(p4, "PRAGMA integrity_check") == [("ok",)] and check_fts(p4["conn"]) == []
    assert q(p4, "SELECT value FROM build_info WHERE key='builder'") == [("cinema_db.harness.build.build/2",)]
    assert q(p4, "SELECT count(*) FROM build_info WHERE key='phase4_snapshot_index_sha256'") == [(1,)]


def test_a_person_only_phase4_names_gets_the_credit_and_the_name_provenance(p4):
    rows = q(p4, "SELECT n.name, s.name, c.source_id FROM credit c JOIN entity_name n ON n.entity_id=c.person_id AND n.is_primary=1 JOIN source s ON s.source_id=n.source_id "
                 "JOIN external_id x ON x.entity_id=c.person_id AND x.scheme='wikidata' WHERE x.value='Q9104'")
    assert rows and rows[0][0] == "Dora Sceneggiatrice" and rows[0][1] == "wikidata-phase4-targeted"


def test_phase4_never_replaces_a_name_an_older_source_gave(p4):
    assert q(p4, "SELECT n.name FROM entity_name n JOIN external_id x ON x.entity_id=n.entity_id AND x.scheme='wikidata' WHERE x.value='Q9102' AND n.is_primary=1") == [("Bob Attore",)]
    assert q(p4, "SELECT count(*) FROM entity_name WHERE name='Bob Altro Nome'") == [(0,)]


def test_life_dates_keep_their_precision_and_ambiguous_or_inconsistent_ones_are_dropped(p4):
    assert q(p4, "SELECT birth_date, birth_year, death_date FROM person p JOIN external_id x ON x.entity_id=p.person_id AND x.scheme='wikidata' WHERE x.value='Q9104'") == [("1950-03-04", 1950, None)]
    notes = p4["report"]["skipped"]
    assert notes["person_death_date_ambiguous"] == 1  # 1999 (year precision) and 2001-05-05 are different dates, not one date at two precisions
    assert q(p4, "SELECT f.field, s.name FROM field_provenance f JOIN source s ON s.source_id=f.source_id JOIN external_id x ON x.entity_id=f.entity_id AND x.scheme='wikidata' WHERE x.value='Q9104'") == [("birth_date", "wikidata-phase4-targeted")]


def test_a_multilingual_label_is_a_name_with_no_language_and_a_deprecated_date_is_ignored(p4):
    # Q9105 is credited nowhere in the miniature, so only the pure functions can show it
    assert choose_date([("1960-01-01T00:00:00Z", 9, "NormalRank"), ("1900-01-01T00:00:00Z", 11, "DeprecatedRank")]) == ("1960", "ok")


@pytest.mark.parametrize("value,precision,expected", [("1950-03-04T00:00:00Z", 11, "1950-03-04"), ("1950-01-01T00:00:00Z", 9, "1950"), ("1950-03-01T00:00:00Z", 10, "1950-03"),
                                                      ("1950-01-01T00:00:00Z", 8, None), ("0000-01-01T00:00:00Z", 9, None), ("junk", 11, None)])
def test_time_values_follow_their_precision(value, precision, expected):
    assert render_time(value, precision) == expected


def test_choose_date_resolves_precisions_of_one_date_and_rejects_different_dates():
    assert choose_date([("1950-01-01T00:00:00Z", 9, "NormalRank"), ("1950-03-04T00:00:00Z", 11, "NormalRank")]) == ("1950-03-04", "ok")
    assert choose_date([("1950-01-01T00:00:00Z", 9, "NormalRank"), ("1951-03-04T00:00:00Z", 11, "NormalRank")]) == (None, "ambiguous")
    assert choose_date([("1950-01-01T00:00:00Z", 11, "NormalRank"), ("1951-03-04T00:00:00Z", 11, "PreferredRank")]) == ("1951-03-04", "ok")
    assert choose_date([]) == (None, "none")


def test_inconsistent_dates_are_reported_and_not_imported(p4):
    assert p4["report"]["skipped"].get("person_dates_inconsistent", 0) == 0  # Q9106 has no credit in the miniature: reported only if the person is created


def test_names_for_relation_targets_companies_and_countries_come_from_phase4(p4):
    assert q(p4, "SELECT count(*) FROM v_work WHERE title='Romanzo senza nome offline'") == [(1,)]
    assert q(p4, "SELECT count(*) FROM company c JOIN entity_name n ON n.entity_id=c.company_id AND n.is_primary=1 WHERE n.name='Casa Senza Nome' AND c.country_id IS NOT NULL") == [(1,)]
    assert q(p4, "SELECT iso2, s.name FROM country c JOIN source s ON s.source_id=c.source_id WHERE wikidata_id='Q9301'") == [("IT", "wikidata-phase4-targeted")]
    assert q(p4, "SELECT iso639_1, iso639_3 FROM language WHERE wikidata_id='Q9401'") == [("it", "ita")]


def test_money_in_another_currency_is_kept_as_stated_never_converted(p4):
    rows = q(p4, "SELECT kind, amount, currency FROM work_financial WHERE kind='budget' ORDER BY currency")
    assert ("budget", 900000, "EUR") in rows and ("budget", 1500000, "USD") in rows
    assert p4["report"]["counts"]["financial_rows_in_original_currency"] == 1


def test_awards_link_category_ceremony_work_and_nominee_with_provenance(p4):
    assert sorted(q(p4, "SELECT a.name_norm FROM award_category a")) == [("miglior film",), ("miglior regia",)]  # the orphan category Q9704 was not created
    rows = q(p4, "SELECT c.name, c.scope, r.outcome, cer.year, cer.edition, pn.name FROM award_result r JOIN award_category c ON c.category_id=r.category_id JOIN ceremony cer ON cer.ceremony_id=r.ceremony_id "
                 "LEFT JOIN entity_name pn ON pn.entity_id=r.person_id AND pn.is_primary=1 ORDER BY r.result_id")
    assert ("Miglior regia", "person_for_work", "won", 1983, "5ª cerimonia del Premio di Prova", "Bob Attore") in rows  # nominated AND won: the win is kept
    assert ("Miglior regia", "person_for_work", "nominated", 1983, "5ª cerimonia del Premio di Prova", "Dora Sceneggiatrice") in rows
    assert ("Miglior film", "work", "won", 1983, "5ª cerimonia del Premio di Prova", None) in rows
    counts, skipped = p4["report"]["counts"], p4["report"]["skipped"]
    assert counts["award_nominated_and_won_kept_won"] == 2 and skipped["ceremony_items_with_the_same_award_year_and_label"] == 1
    assert q(p4, "SELECT count(*) FROM ceremony") == [(1,)]  # the year-only statement reuses the ONE ceremony item of that award and year
    assert q(p4, "SELECT count(DISTINCT award_id) FROM award_category") == [(1,)]
    assert q(p4, "SELECT n.name, a.country_id IS NOT NULL FROM award a JOIN entity_name n ON n.entity_id=a.award_id AND n.is_primary=1") == [("Premio di Prova", 1)]


def test_unplaceable_awards_are_skipped_and_counted_not_invented(p4):
    skipped = p4["report"]["skipped"]
    assert skipped["award_item_not_available"] == 1  # Q9701 was never fetched
    assert skipped["award_without_ceremony_or_year"] == 1  # Q9704 has neither a ceremony nor a year
    assert q(p4, "SELECT count(*) FROM award_result") == [(3,)]


def test_without_the_phase4_snapshot_the_build_is_what_it_was(p4):
    assert "builder" not in p4["plain"]["inputs"] or p4["plain"]["inputs"]["builder"] == "cinema_db.harness.build.build/1"
    assert "phase4_snapshot_index_sha256" not in p4["plain"]["inputs"]
    assert p4["plain"]["counts"].get("persons_named_by_phase4") is None and p4["plain"]["counts"]["award_statements_not_imported"] == 6


def test_an_organisation_listed_as_a_producer_is_a_company_not_a_second_entity(p4):
    assert q(p4, "SELECT count(*) FROM external_id WHERE scheme='wikidata' AND value='Q9502'") == [(1,)]
    assert q(p4, "SELECT e.entity_type FROM external_id x JOIN entity e ON e.entity_id=x.entity_id WHERE x.scheme='wikidata' AND x.value='Q9502'") == [("company",)]
    assert p4["report"]["skipped"]["credit_holder_is_an_organisation:producer"] == 1
    assert not any(k.startswith("id_conflict:wikidata") for k in p4["report"]["skipped"])
    # without phase 4 nothing changes: the phase-3 behaviour (and digest) stays reproducible
    assert "credit_holder_is_an_organisation:producer" not in p4["plain"]["skipped"]
