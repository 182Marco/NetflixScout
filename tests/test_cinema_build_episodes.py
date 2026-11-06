"""Phase 6 data fix: an episode known from its own Wikipedia page AND from a row of its season page is one episode, never two.

Found by the cinema_sql tool on the real database (Breaking Bad season 1 had 8 episodes, season 5 had 18). The matching is strict (same series, same title once
the series qualifier is gone, compatible season and number, exactly one row) and nothing is inferred: a row without a number stays without one.
"""
from __future__ import annotations

import json
import sqlite3

import pytest
from cinema_build_support import make_inputs

from cinema_db.harness.build.build import Inputs, episode_page_base_title, run_build

SERIES = "wp-100"  # «Serie di prova», season 2 = wp-100#season2 in the miniature


def row(record_id, title, *, number=None, season=2, source="season_page", **extra):
    return {"record_id": record_id, "series_id": SERIES, "season_id": "wp-100#season2" if source == "season_page" else None, "season_number": season, "episode_number": number,
            "title": title, "title_it": title, "title_original": None, "air_dates": [], "source": source, "ids": {}, "wikipedia_url": None, **extra}


EXTRA = [
    row("wp-100#r-finale", "Finale"),                                                                   # a season row without a number...
    row("wp-701", "Finale (Serie di prova)", number=5, source="episode_page", wikipedia_url="https://it.wikipedia.org/wiki/Finale_(Serie_di_prova)",
        ids={"qid": "Q9990", "imdb_id": "tt9990001"}, air_dates=["1 gennaio 2017"]),                    # ...and the page that states its number and ids: ONE episode
    row("wp-100#r-solo", "Un episodio solo con pagina", number=None, source="episode_page", wikipedia_url="https://it.wikipedia.org/wiki/Solo_(Serie_di_prova)"),   # no row: stays
    row("wp-100#r-doppio-a", "Doppio"), row("wp-100#r-doppio-b", "Doppio"),
    row("wp-702", "Doppio (Serie di prova)", source="episode_page", wikipedia_url="https://it.wikipedia.org/wiki/Doppio_(Serie_di_prova)"),  # two rows fit: ambiguous, stays
    row("wp-100#r-numeri", "Numeri", number=3),
    row("wp-703", "Numeri (episodio)", number=4, source="episode_page", wikipedia_url="https://it.wikipedia.org/wiki/Numeri_(episodio)"),    # the numbers contradict: stays
    row("wp-100#r-parte1", "Atto (prima parte)", number=6), row("wp-100#r-parte2", "Atto (seconda parte)", number=7),
    row("wp-704", "Atto (prima parte)", number=6, source="episode_page", wikipedia_url="https://it.wikipedia.org/wiki/Atto_(prima_parte)"),  # a part, not a qualifier: same full title
]


def build(tmp_path, *, merge: bool):
    base = make_inputs(tmp_path)
    episodes = base.series_dir / "episodes.jsonl"
    episodes.write_text(episodes.read_text(encoding="utf-8") + "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in EXTRA), encoding="utf-8")
    inputs = Inputs(base.film_snapshot, base.series_snapshot, base.film_catalog, base.series_dir, merge_episode_pages=merge)
    out = tmp_path / ("merged" if merge else "kept") / "cinema.sqlite3"
    report = run_build(out, inputs, log=lambda *_: None)
    return sqlite3.connect(out), report


@pytest.fixture(scope="module")
def merged(tmp_path_factory):
    conn, report = build(tmp_path_factory.mktemp("merge"), merge=True)
    yield conn, report
    conn.close()


@pytest.fixture(scope="module")
def kept(tmp_path_factory):
    conn, report = build(tmp_path_factory.mktemp("kept"), merge=False)
    yield conn, report
    conn.close()


def season2(conn, title):
    return conn.execute("SELECT work_id, episode_number, release_date FROM v_work WHERE kind = 'episode' AND title = ? AND season_number = 2", (title,)).fetchall()


def test_a_page_and_its_season_row_become_one_episode_with_the_stated_number_and_identifiers(merged):
    conn, report = merged
    rows = season2(conn, "Finale")
    assert len(rows) == 1 and rows[0][1] == 5  # the number comes from the page that states it
    wid = rows[0][0]
    ids = dict(conn.execute("SELECT scheme, value FROM external_id WHERE entity_id = ? AND scheme IN ('wikipedia_it','wikidata','imdb_title')", (wid,)).fetchall())
    assert ids == {"wikipedia_it": "Finale_(Serie_di_prova)", "wikidata": "Q9990", "imdb_title": "tt9990001"}
    assert ("Finale (Serie di prova)",) in conn.execute("SELECT name FROM entity_name WHERE entity_id = ? AND kind = 'alias'", (wid,)).fetchall()
    assert conn.execute("SELECT count(*) FROM v_work WHERE title = 'Finale (Serie di prova)'").fetchone()[0] == 0  # no second episode
    assert report["counts"]["episode_pages_merged_into_their_season_row"] == 2  # this page and the one of «Atto (prima parte)»


def test_a_match_that_is_not_exactly_one_row_with_compatible_numbers_is_never_merged(merged):
    conn, report = merged
    assert conn.execute("SELECT count(*) FROM v_work WHERE kind = 'episode' AND title = 'Un episodio solo con pagina'").fetchone()[0] == 1
    assert len(season2(conn, "Doppio")) == 2 and conn.execute("SELECT count(*) FROM v_work WHERE title = 'Doppio (Serie di prova)'").fetchone()[0] == 1
    assert len(season2(conn, "Numeri")) == 1 and conn.execute("SELECT count(*) FROM v_work WHERE title = 'Numeri (episodio)'").fetchone()[0] == 1
    assert report["skipped"]["episode_page_not_merged:several_rows"] == 1


def test_a_part_of_an_episode_is_not_a_qualifier_and_a_row_without_a_number_gets_none_by_position(merged):
    conn, _ = merged
    assert len(season2(conn, "Atto (prima parte)")) == 1 and len(season2(conn, "Atto (seconda parte)")) == 1
    assert [r[1] for r in conn.execute("SELECT work_id, episode_number FROM v_work WHERE title = 'Doppio' AND kind = 'episode'")] == [None, None]  # never numbered by position


def test_only_the_duplicates_disappear_and_the_database_stays_consistent(merged, kept):
    merged_conn, kept_conn = merged[0], kept[0]
    count = lambda c: c.execute("SELECT count(*) FROM v_work WHERE kind = 'episode'").fetchone()[0]  # noqa: E731
    assert count(kept_conn) - count(merged_conn) == 2  # the pages of «Finale» and of «Atto (prima parte)»: the only exact one-row matches
    assert merged_conn.execute("PRAGMA foreign_key_check").fetchall() == [] and merged_conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert merged_conn.execute("SELECT count(*) FROM (SELECT 1 FROM external_id GROUP BY scheme, value HAVING count(*) > 1)").fetchone()[0] == 0


def test_the_flag_off_keeps_the_phase_three_and_four_behaviour(kept):
    conn, report = kept
    assert len(season2(conn, "Finale")) == 1 and conn.execute("SELECT count(*) FROM v_work WHERE title = 'Finale (Serie di prova)'").fetchone()[0] == 1
    assert "episode_pages_merged_into_their_season_row" not in report["counts"]


@pytest.mark.parametrize("title,series,expected", [
    ("Felina (Breaking Bad)", "breaking bad", "felina"), ("Pilot (episodio)", "lost", "pilot"), ("Ozymandias (episodio di Breaking Bad)", "breaking bad", "ozymandias"),
    ("Il cavaliere pirata (prima parte)", "dragons", "il cavaliere pirata prima parte"), ("Pilota", "x", "pilota"), ("Titolo (altra cosa)", "serie", "titolo altra cosa"),
])
def test_the_qualifier_is_removed_only_when_it_names_the_series_or_says_episode(title, series, expected):
    assert episode_page_base_title(title, series) == expected
