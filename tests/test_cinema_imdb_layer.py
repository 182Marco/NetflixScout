"""The phase-9 layer on a miniature world: what is recovered, what is held back, what is never overwritten, and reproducibility."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from cinema_db.harness.audit import imdb_load as L
from cinema_db.harness.audit import util
from cinema_db.harness.build import imdb_layer as layer
from cinema_db.schema import create_database


def _t(conn, tconst, ttype, title, start, runtime=None, adult=0, genres=None, otitle=None):
    conn.execute("INSERT INTO title VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (tconst, L.tid(tconst), ttype, title, otitle or title, adult, start, None, runtime, genres,
                                                                        util.norm_title(title), util.norm_title(otitle or title)))


@pytest.fixture()
def world(tmp_path):
    base = create_database(tmp_path / "cinema.sqlite3")
    c = sqlite3.connect(base)
    c.execute("INSERT INTO source (source_id, name, kind, license, usage_scope, attribution_required) VALUES (1, 'film-catalog-v3', 'derived', 'x', 'unverified', 0)")
    c.execute("INSERT INTO build_info VALUES ('content_sha256', 'base-digest')")

    def work(wid, title, kind, year, imdb=None, runtime=None, rdate=None, ref=None, parent=None, season=None, number=None):
        c.execute("INSERT INTO entity VALUES (?, 'work')", (wid,))
        c.execute("INSERT INTO work (work_id, kind, parent_work_id, season_number, episode_number, release_date, release_year, runtime_min, source_id, source_ref) VALUES (?,?,?,?,?,?,?,?,1,?)",
                  (wid, kind, parent, season, number, rdate, year, runtime, ref or f"Q{wid}"))
        c.execute("INSERT INTO entity_name (entity_id, name, name_norm, kind, is_primary, source_id) VALUES (?,?,?,'primary',1,1)", (wid, title, util.norm_title(title)))
        if imdb:
            c.execute("INSERT INTO external_id (entity_id, scheme, value, source_id) VALUES (?,'imdb_title',?,1)", (wid, imdb))

    work(1, "Alpha", "film", 2000, "tt0000001", runtime=100)
    work(2, "Beta", "film", 2001, "tt0000002", runtime=90, rdate="2001-05-01")
    c.execute("INSERT INTO external_id (entity_id, scheme, value, source_id) VALUES (2, 'tmdb_movie', '77', 1)")
    work(8, "Notte di carnevale", "film", 1935, None)
    work(3, "Gamma", "series", 2005, None, ref="wp-3;rev=1")
    work(4, "Delta", "series", 2006, None, ref="wp-4;rev=1")
    work(5, "Show", "series", 2010, "tt0000020")
    work(6, "Show ep1", "episode", 2010, None, parent=5, season=1, number=1)
    work(7, "Show ep2", "episode", 2010, None, parent=5, season=1, number=2)
    # works with two IMDb ids (flag = what the v2 file says is primary)
    work(30, "Dup", "film", 2010, "tt0000041")                                    # flagged primary tt41 does not match the title; tt40 does
    c.execute("INSERT INTO external_id (entity_id, scheme, value, is_primary, source_id) VALUES (30, 'imdb_title', 'tt0000040', 0, 1)")
    work(31, "Zed", "film", 2011, "tt0000060")                                    # the title-matching id (tt61) sorts AFTER the flagged one
    c.execute("INSERT INTO external_id (entity_id, scheme, value, is_primary, source_id) VALUES (31, 'imdb_title', 'tt0000061', 0, 1)")
    work(32, "Qux", "film", 2012, "tt0000070")                                    # flagged primary is unknown to IMDb
    c.execute("INSERT INTO external_id (entity_id, scheme, value, is_primary, source_id) VALUES (32, 'imdb_title', 'tt0000071', 0, 1)")
    work(33, "Pair", "film", 2013, "tt0000080")                                   # two equal titles: the one with more votes (tt81) wins
    c.execute("INSERT INTO external_id (entity_id, scheme, value, is_primary, source_id) VALUES (33, 'imdb_title', 'tt0000081', 0, 1)")
    work(34, "Echo", "film", 2003, "tt0000095", runtime=100)                      # held title with another known IMDb id and a far runtime: released
    work(41, "Seasonal", "series", 2014, "tt0000035")
    work(42, "Seasonal S1", "season", 2014, None, parent=41, season=1)
    work(43, "Seasonal e1", "episode", 2014, None, parent=42, season=1, number=1)
    work(44, "Seasonal e3", "episode", 2014, "tt0000039", parent=42, season=1, number=3)  # already has an IMDb id; IMDb lists another episode in its slot

    def person(pid, name, birth):
        c.execute("INSERT INTO entity VALUES (?, 'person')", (pid,))
        c.execute("INSERT INTO person (person_id, birth_year, source_id) VALUES (?,?,1)", (pid, birth))
        c.execute("INSERT INTO entity_name (entity_id, name, name_norm, kind, is_primary, source_id) VALUES (?,?,?,'primary',1,1)", (pid, name, util.norm_title(name)))

    person(10, "Ann Lee", 1970)
    person(11, "Bob Roy", None)
    person(20, "Cy Dup", 1960)
    person(21, "Cy Dup", None)       # same IMDb person, same work and role, no date that contradicts: the safe merge
    person(22, "Dee Hom", 1950)
    person(23, "Dee Hom", 1990)      # same IMDb id claimed, but another birth year: a homonym, never merged
    for w, p in ((1, 10), (2, 10), (1, 11), (1, 20), (1, 21), (2, 22), (2, 23)):
        c.execute("INSERT INTO credit (work_id, person_id, role, source_id) VALUES (?,?,'cast',1)", (w, p))
    c.commit(); c.close()

    ml = sqlite3.connect(tmp_path / "ml.sqlite3")
    ml.executescript("""
      CREATE TABLE movies (movie_id INTEGER PRIMARY KEY, title TEXT, clean_title TEXT, year INTEGER);
      CREATE TABLE links (movie_id INTEGER PRIMARY KEY, imdb_id TEXT, tmdb_id TEXT);
      CREATE TABLE movie_stats (movie_id INTEGER PRIMARY KEY, n_ratings INTEGER, avg_rating REAL, first_rated_at INTEGER, last_rated_at INTEGER);
      INSERT INTO movies VALUES (1,'Alpha (2000)','',2000),(2,'Newfilm (1999)','',1999),(3,'Vid (2001)','',2001),(4,'Adult (2002)','',2002),(5,'Alpha (2000)','',2000),(6,'Beta again (2002)','',2002),
        (7,'Dup (2010)','',2010),(8,'Pair (2013)','',2013),(9,'Pair (2013)','',2013),(10,'Echo (2003)','',2003),(11,'Delta (2006)','',2006),(12,'$ (1971)','',1971),
        (13,'First (2010)','First',2010),(14,'Wrong Name (2012)','Wrong Name',2012);
      INSERT INTO links VALUES (1,'1','1'),(2,'10','10'),(3,'11','11'),(4,'12','12'),(5,'13','13'),(6,'30','77'),(7,'41','141'),(8,'80','180'),(9,'81','181'),(10,'90','190'),(11,'91','191'),(12,'92','192'),(13,'21','21'),(14,'23','23');
      CREATE TABLE movie_genres (movie_id INTEGER NOT NULL, genre TEXT NOT NULL, PRIMARY KEY (movie_id, genre));
      CREATE TABLE tags (user_id INTEGER NOT NULL, movie_id INTEGER NOT NULL, tag TEXT NOT NULL, tag_norm TEXT NOT NULL, tagged_at INTEGER NOT NULL);
      INSERT INTO movie_genres VALUES (1,'Drama'),(1,'Comedy'),(2,'Drama'),(3,'Horror'),(13,'Comedy');
      INSERT INTO tags VALUES (1,1,'Time Travel','time travel',0),(2,1,'time  travel','time travel',0),(2,1,'funny','funny',0),(3,2,'funny','funny',0),(1,3,'x','x',0),(1,13,'funny','funny',0);
      INSERT INTO movie_stats VALUES (1,500,4.0,0,1600000000),(2,40,3.5,0,1600000000),(3,5,3.0,0,0),(4,5,3.0,0,0),(5,9,3.0,0,0),(6,3,3.0,0,0),
        (7,20,3.2,0,0),(8,10,2.0,0,0),(9,30,3.9,0,0),(10,8,3.0,0,0),(11,8,3.0,0,0),(12,8,3.0,0,0),(13,6,4.5,0,0),(14,7,2.0,0,0);
    """)
    ml.commit(); ml.close()

    st = L.create_staging(tmp_path / "st.sqlite3")
    _t(st, "tt0000001", "movie", "Alpha", 2000, 100)
    _t(st, "tt0000002", "short", "Beta", 2002, 80)
    _t(st, "tt0000003", "tvSeries", "Gamma", 2005)
    _t(st, "tt0000004", "movie", "Delta", 2006)
    _t(st, "tt0000010", "movie", "Newfilm", 1999, 95, genres="Drama,Short")
    _t(st, "tt0000011", "video", "Vid", 2001)
    _t(st, "tt0000012", "movie", "Adult", 2002, adult=1)
    _t(st, "tt0000013", "movie", "Alpha", 2000, 90)
    _t(st, "tt0000014", "movie", "Pagefilm", 1980, 88)
    _t(st, "tt0000015", "movie", "Mixfilm", 1990, 70)
    _t(st, "tt0000016", "tvSeries", "Mixseries", 1990)
    _t(st, "tt0000017", "movie", "Carnival Night", 1935, 80)
    st.execute("INSERT INTO crew VALUES ('tt0000017','nm5',NULL)")
    _t(st, "tt0000020", "tvSeries", "Show", 2010)
    _t(st, "tt0000040", "movie", "Dup", 2010, 100); _t(st, "tt0000041", "short", "Other thing", 1999, 10)
    _t(st, "tt0000060", "movie", "Another", 2011, 70); _t(st, "tt0000061", "movie", "Zed", 2011, 95)
    _t(st, "tt0000071", "movie", "Qux", 2012, 80)
    _t(st, "tt0000080", "movie", "Pair", 2013, 90); _t(st, "tt0000081", "movie", "Pair", 2013, 91)
    _t(st, "tt0000095", "movie", "Echo", 2003, 100); _t(st, "tt0000090", "short", "Echo", 2003, 20)
    _t(st, "tt0000091", "movie", "Delta", 2006, 90)
    _t(st, "tt0000092", "movie", "$", 1971, 90)
    _t(st, "tt0000035", "tvSeries", "Seasonal", 2014)
    _t(st, "tt0000023", "tvEpisode", "Third", 2012, 30); _t(st, "tt0000024", "tvEpisode", "No number", 2012); _t(st, "tt0000025", "tvEpisode", "Slot taken", 2010)
    _t(st, "tt0000027", "tvEpisode", "???", 2012)
    _t(st, "tt0000038", "tvEpisode", "Other id same slot", 2014); _t(st, "tt0000039", "tvEpisode", "Own id", 2014)
    _t(st, "tt0000026", "tvEpisode", "Of a series without episodes", 2006); _t(st, "tt0000032", "tvEpisode", "Seasonal two", 2014, 25)
    _t(st, "tt0000021", "tvEpisode", "First", 2010)
    _t(st, "tt0000022", "tvEpisode", "Second", 2015)
    st.executemany("INSERT INTO episode VALUES (?,?,?,?)", [("tt0000021", "tt0000020", 1, 1), ("tt0000022", "tt0000020", 1, 2), ("tt0000023", "tt0000020", 1, 3),
                                                         ("tt0000024", "tt0000020", None, None), ("tt0000027", "tt0000020", 1, 4), ("tt0000025", "tt0000035", 1, 1), ("tt0000026", "tt0000003", 1, 1),
                                                         ("tt0000032", "tt0000035", 1, 2),
                                                         ("tt0000038", "tt0000035", 1, 3)])
    st.executemany("INSERT INTO rating VALUES (?,?,?)", [("tt0000001", 7.5, 1000), ("tt0000010", 6.0, 50), ("tt0000021", 8.0, 10),
                                                       ("tt0000040", 7.0, 5000), ("tt0000041", 3.0, 10), ("tt0000060", 4.0, 3), ("tt0000061", 8.0, 900),
                                                       ("tt0000071", 6.0, 100), ("tt0000080", 5.0, 50), ("tt0000081", 6.5, 500), ("tt0000023", 7.0, 5)])
    st.executemany("INSERT INTO principal VALUES (?,?,?,?,?,?)", [
        ("tt0000001", 1, "nm1", "actress", None, '["Heroine"]'), ("tt0000001", 2, "nm9", "actor", None, None),
        ("tt0000002", 1, "nm1", "actress", None, None),
        ("tt0000010", 1, "nm1", "actress", None, '["Hero"]'), ("tt0000010", 2, "nm2", "director", None, None), ("tt0000010", 3, "nm9", "actor", None, None),
        ("tt0000014", 1, "nm5", "director", None, None), ("tt0000014", 2, "nm6", "casting_director", None, None),
        ("tt0000001", 3, "nm20", "actor", None, None), ("tt0000002", 2, "nm22", "actress", None, None)])
    st.executemany("INSERT INTO crew VALUES (?,?,?)", [("tt0000014", "nm5", None), ("tt0000010", "nm2", "nm7")])
    st.executemany("INSERT INTO name VALUES (?,?,?,?,?,?)", [
        ("nm1", "Ann Lee", 1970, None, None, L.person_norm("Ann Lee")), ("nm2", "Dir One", 1950, None, None, L.person_norm("Dir One")),
        ("nm5", "Page Dir", None, None, None, L.person_norm("Page Dir")), ("nm7", "Wri Ter", 1960, None, None, L.person_norm("Wri Ter")),
        ("nm9", "Bob Roy", 1955, None, None, L.person_norm("Bob Roy")),
        ("nm20", "Cy Dup", 1960, None, None, L.person_norm("Cy Dup")), ("nm22", "Dee Hom", 1950, None, None, L.person_norm("Dee Hom"))])
    st.commit(); st.close()

    s5 = tmp_path / "s5"
    s5.mkdir()
    def rec(record_id, title, imdb, year, reliable=False, eligible=True, klass="series_page"):
        return {"record_id": record_id, "title": title, "year": year, "ids": {"imdb_id": imdb, "qid": f"Q{record_id[-1]}00"}, "ids_reliable": reliable,
                "default_search_eligible": eligible, "catalog_class": klass}
    (s5 / "series.jsonl").write_text("\n".join(json.dumps(r) for r in [
        rec("wp-3", "Gamma", "tt0000003", 2005), rec("wp-4", "Delta", "tt0000004", 2006),
        rec("wp-8", "Mixfilm", "tt0000015", 1990, eligible=False, klass="franchise_page_mixed_media"),
        rec("wp-9", "Mixseries", "tt0000016", 1990, eligible=False, klass="franchise_page_mixed_media")]))
    (s5 / "tv_movies.jsonl").write_text("")
    audit = tmp_path / "audit"
    audit.mkdir()
    (audit / "candidates_person_pairs.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"persons": [20, 21], "name": "cy dup", "class": "same_person_candidate_strong_shared_work_and_role"},
        {"persons": [22, 23], "name": "dee hom", "class": "same_person_candidate_strong_shared_work_and_role"}]))
    (audit / "dump_scan.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"kind": "film_page", "page_id": 100, "title": "Pagefilm", "year": 1980, "original_title": None, "director": "Page Dir"},
        {"kind": "film_page", "page_id": 101, "title": "Notte di carnevale", "year": 1935, "original_title": None, "director": "Page Dir"}]))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"datasets": {"title.basics": {"sha256": "ab" * 32, "retrieved_at": "2026-11-08T12:00:00Z"}}}))
    inputs = layer.LayerInputs(base=base, staging=tmp_path / "st.sqlite3", movielens=tmp_path / "ml.sqlite3", s5_dir=s5, audit_dir=audit, imdb_manifest=manifest,
                               memo={"pages": {"candidates": {}, "excluded": [], "rejected": {100: ("Pagefilm", "plot_too_short"), 101: ("Notte di carnevale", "plot_too_short")}}, "v3": []})
    return inputs, tmp_path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_layer_builds_v3_without_touching_the_base(world):
    inputs, tmp = world
    before = _sha(inputs.base)
    report = layer.run_layer(inputs, tmp / "v3.sqlite3", log=lambda *_: None)
    assert _sha(inputs.base) == before  # the runtime database is only read
    c = sqlite3.connect(tmp / "v3.sqlite3")
    c.row_factory = sqlite3.Row
    one = lambda sql, *a: c.execute(sql, a).fetchone()[0]

    # source priority: IMDb wins for kind, year and runtime, the loser is kept with its source
    assert one("SELECT kind FROM work WHERE work_id = 2") == "short" and one("SELECT release_year FROM work WHERE work_id = 2") == 2002 and one("SELECT runtime_min FROM work WHERE work_id = 2") == 80
    claims = {(r["field"], r["value"]) for r in c.execute("SELECT * FROM entity_claim WHERE entity_id = 2")}
    assert {("kind", "film"), ("release_year", "2001"), ("runtime_min", "90"), ("release_date", "2001-05-01")} <= claims
    assert one("SELECT release_date FROM work WHERE work_id = 2") is None  # moved to a claim, never left inconsistent with the year
    assert one("SELECT release_year FROM work WHERE work_id = 1") == 2000 and one("SELECT COUNT(*) FROM entity_claim WHERE entity_id = 1") == 0  # agreement: nothing changes

    # ids_reliable = false: recovered only where IMDb confirms title, year AND television type
    assert one("SELECT value FROM external_id WHERE entity_id = 3 AND scheme = 'imdb_title'") == "tt0000003"
    assert one("SELECT COUNT(*) FROM external_id WHERE entity_id = 4 AND scheme = 'imdb_title'") == 0
    assert one("SELECT tier FROM external_id_candidate WHERE entity_id = 4") == "ids_reliable_false_unconfirmed"

    # ratings: two sources side by side for the same film, nothing overwritten
    rows = c.execute("SELECT s.name, r.value, r.scale_max, r.vote_count FROM work_rating r JOIN source s USING(source_id) WHERE work_id = 1 ORDER BY s.name").fetchall()
    assert [(r[0], r[1], r[2], r[3]) for r in rows] == [("imdb-datasets", 7.5, 10.0, 1000), ("movielens-32m-aggregates", 4.0, 5.0, 500)]

    # people: strong match attaches the id; weak match stays a candidate; nobody is created from a name alone
    assert one("SELECT value FROM external_id WHERE entity_id = 10 AND scheme = 'imdb_name'") == "nm1"
    assert one("SELECT COUNT(*) FROM external_id WHERE entity_id = 11 AND scheme = 'imdb_name'") == 0
    assert one("SELECT tier FROM external_id_candidate WHERE entity_id = 11 AND value = 'nm9'") in ("weak_single_title", "conflict_birth_year")
    assert one("SELECT billing_order FROM credit WHERE work_id = 1 AND person_id = 10") == 1
    assert one("SELECT character_name FROM credit WHERE work_id = 1 AND person_id = 10") == "Heroine"

    # new works: entry rule, holds and separate archives
    imdb = {r[0]: r[1] for r in c.execute("SELECT value, entity_id FROM external_id WHERE scheme = 'imdb_title'")}
    assert "tt0000010" in imdb and "tt0000014" in imdb and "tt0000015" in imdb  # MovieLens film, Italian page, mixed-media film
    assert not ({"tt0000011", "tt0000012", "tt0000013", "tt0000016", "tt0000017"} & set(imdb))  # tt17: its ITALIAN page title equals an existing film of the same year  # video, adult, same title+year as Alpha, a series from a mixed page
    sep = {r["reason"] for r in map(json.loads, (tmp / "v3.separate" / "not_entered.jsonl").read_text().splitlines())}
    assert {"outside_entry_rule:video", "flagged_adult", "reconciliation_hold_same_title_and_year_in_cinema"} <= sep
    new = imdb["tt0000014"]
    assert one("SELECT entry_route FROM work_status WHERE work_id = ?", new) == "imdb_itwiki_page" and one("SELECT plot_status FROM work_status WHERE work_id = ?", new) == "without_plot"
    assert one("SELECT value FROM external_id WHERE entity_id = ? AND scheme = 'wikipedia_it'", new) == "Pagefilm"
    assert one("SELECT entry_route FROM work_status WHERE work_id = ?", imdb["tt0000010"]) == "imdb_movielens"
    assert one("SELECT kind FROM work WHERE work_id = ?", imdb["tt0000010"]) == "film"
    # credits of the new film: nm1 is the EXISTING Ann Lee (no duplicate person); nm2 is new; nm9 is only a CANDIDATE of Bob Roy: the credit is
    # kept through a NEW person that carries the candidate, and Bob Roy is neither merged nor given the id
    people = {r["scheme"] + ":" + r["value"]: r["entity_id"] for r in c.execute("SELECT * FROM external_id WHERE scheme = 'imdb_name'")}
    assert people["imdb_name:nm1"] == 10 and "imdb_name:nm2" in people and people["imdb_name:nm9"] not in (10, 11)
    assert one("SELECT COUNT(*) FROM credit WHERE work_id = ? AND person_id = 10", imdb["tt0000010"]) == 1
    assert one("SELECT COUNT(*) FROM credit WHERE work_id = ? AND person_id = ?", imdb["tt0000010"], people["imdb_name:nm9"]) == 1
    claim = c.execute("SELECT value, source_ref FROM entity_claim WHERE entity_id = ? AND field = 'imdb_person_possibly_existing_person'", (people["imdb_name:nm9"],)).fetchone()
    assert claim["value"] == "11" and claim["source_ref"].startswith("nm9:")
    assert one("SELECT COUNT(*) FROM entity_canonical WHERE entity_id = 11") == 0 and one("SELECT COUNT(*) FROM external_id WHERE entity_id = 11 AND scheme = 'imdb_name'") == 0
    assert report["counts"]["credits_recovered_through_new_person"] >= 1
    assert one("SELECT COUNT(*) FROM credit WHERE source_ref = 'nm6'") == 0  # casting_director has no role in the vocabulary: skipped, counted
    assert one("SELECT COUNT(*) FROM work_genre WHERE work_id = ?", imdb["tt0000010"]) == 1  # 'Drama'; the format label 'Short' is not a genre

    # a MovieLens title unknown to IMDb whose TMDb id is the catalogue's: the same film, its id becomes a NON-primary alias, no second work
    assert one("SELECT is_primary FROM external_id WHERE entity_id = 2 AND value = 'tt0000030'") == 0
    assert one("SELECT COUNT(*) FROM work w JOIN external_id x ON x.entity_id = w.work_id WHERE x.value = 'tt0000030'") == 1

    # episodes: number + year confirm; number alone is only a candidate
    assert one("SELECT value FROM external_id WHERE entity_id = 6 AND scheme = 'imdb_title'") == "tt0000021"
    assert one("SELECT tier FROM external_id_candidate WHERE entity_id = 7") == "episode_number_only"
    assert one("SELECT COUNT(*) FROM work_rating WHERE work_id = 6") == 1

    # every work has a status; the file passed its own integrity, foreign-key and FTS checks (run_layer raises otherwise)
    assert one("SELECT COUNT(*) FROM work") == one("SELECT COUNT(*) FROM work_status")
    assert one("SELECT value FROM build_info WHERE key = 'layer_base_content_sha256'") == "base-digest"


def test_layer_is_reproducible(world):
    inputs, tmp = world
    a = layer.run_layer(inputs, tmp / "a.sqlite3", log=lambda *_: None)
    b = layer.run_layer(inputs, tmp / "b.sqlite3", log=lambda *_: None)
    assert a["content_sha256"] == b["content_sha256"] and a["counts"] == b["counts"]
    with pytest.raises(FileExistsError):
        layer.run_layer(inputs, tmp / "a.sqlite3", log=lambda *_: None)  # never overwrites without force


def _built(world, name="v3.sqlite3"):
    inputs, tmp = world
    report = layer.run_layer(inputs, tmp / name, log=lambda *_: None)
    c = sqlite3.connect(tmp / name)
    c.row_factory = sqlite3.Row
    return report, c, tmp


def test_double_imdb_ids_feed_the_work_only_through_the_primary(world):
    report, c, _ = _built(world)
    one = lambda sql, *a: c.execute(sql, a).fetchone()[0]
    prim = lambda w: one("SELECT value FROM external_id WHERE entity_id = ? AND scheme = 'imdb_title' AND is_primary = 1", w)
    # the rule (known to IMDb, title, votes) decides, not the v2 flag and not the alphabet
    assert [prim(w) for w in (30, 31, 32, 33)] == ["tt0000040", "tt0000061", "tt0000071", "tt0000081"]
    assert report["counts"]["double_imdb_works"] == 4 and report["counts"]["double_imdb_primary_changed"] == 4
    # type, year and runtime come from the primary only (the secondary says short, 1999, 10 minutes)
    assert tuple(c.execute("SELECT kind, release_year, runtime_min FROM work WHERE work_id = 30").fetchone()) == ("film", 2010, 100)
    # what IMDb says about the secondary ids is kept with its source_ref, nothing is lost
    claims = {(r["field"], r["value"], r["source_ref"]) for r in c.execute("SELECT * FROM entity_claim WHERE entity_id = 30")}
    assert {("imdb_alt_title_type", "short", "tt0000041"), ("imdb_alt_release_year", "1999", "tt0000041"), ("imdb_alt_runtime_min", "10", "tt0000041"),
            ("imdb_alt_rating", "3.0/10 (10 votes)", "tt0000041"), ("imdb_title_previous_primary", "tt0000041", "tt0000041")} <= claims
    assert ("imdb_alt_id_unknown_to_imdb", "tt0000070", "tt0000070") in {(r["field"], r["value"], r["source_ref"]) for r in c.execute("SELECT * FROM entity_claim WHERE entity_id = 32")}
    # ratings: the IMDb rating is the primary's (tt61 sorts after tt60), MovieLens once per work, through a secondary id when it is the only one
    imdb = lambda w: tuple(c.execute("SELECT value, vote_count, source_ref FROM work_rating r JOIN source s USING(source_id) WHERE work_id = ? AND s.name = 'imdb-datasets'", (w,)).fetchone())
    assert imdb(30) == (7.0, 5000, "tt0000040") and imdb(31) == (8.0, 900, "tt0000061") and imdb(33) == (6.5, 500, "tt0000081")
    ml = lambda w: [r["source_ref"] for r in c.execute("SELECT source_ref FROM work_rating r JOIN source s USING(source_id) WHERE work_id = ? AND s.name LIKE 'movielens%'", (w,))]
    assert ml(30) == ["movielens:7"] and ml(33) == ["movielens:9"]
    assert report["counts"]["ratings_movielens_through_an_alias"] == 2  # work 30 (movie 7) and work 2 (movie 6, tt30 is its alias)


def test_person_reconciliation_is_reversible_and_never_merges_homonyms(world):
    report, c, _ = _built(world)
    one = lambda sql, *a: c.execute(sql, a).fetchone()[0]
    assert [tuple(r) for r in c.execute("SELECT entity_id, canonical_entity_id FROM entity_canonical")] == [(21, 20)]
    assert report["counts"]["person_merges"] == 1 and report["counts"]["person_merge_refused:birth_contradicts_imdb"] == 1
    # nothing is deleted: the merged person, its credit and its names are still there
    assert one("SELECT COUNT(*) FROM person WHERE person_id = 21") == 1 and one("SELECT COUNT(*) FROM credit WHERE person_id = 21") == 1
    # the views resolve to the canonical person: once in v_person, the duplicate credit hidden, the id and the other person's id visible
    assert one("SELECT COUNT(*) FROM v_person WHERE person_id = 21") == 0 and one("SELECT imdb_id FROM v_person WHERE person_id = 20") == "nm20"
    assert one("SELECT COUNT(*) FROM v_credit WHERE work_id = 1 AND person_id = 20") == 1 and one("SELECT COUNT(*) FROM v_credit WHERE person_id = 21") == 0
    # homonym: same IMDb id claimed, other birth year -> not merged, and the id goes only to the person whose birth year matches
    assert one("SELECT COUNT(*) FROM v_person WHERE person_id = 23") == 1
    assert one("SELECT entity_id FROM external_id WHERE scheme = 'imdb_name' AND value = 'nm22'") == 22
    assert one("SELECT tier FROM external_id_candidate WHERE entity_id = 23 AND value = 'nm22'") in ("shared_by_several_entities", "conflict_birth_year")
    assert report["counts"]["person_ids_attached_birth_year_decides"] == 1
    # reversible: dropping the map row brings the second person back everywhere
    c.execute("DELETE FROM entity_canonical")
    assert one("SELECT COUNT(*) FROM v_person WHERE person_id = 21") == 1 and one("SELECT COUNT(*) FROM v_credit WHERE person_id = 21") == 1


def test_held_titles_are_released_only_when_proven_distinct(world):
    report, c, tmp = _built(world)
    imdb = {r[0]: r[1] for r in c.execute("SELECT value, entity_id FROM external_id WHERE scheme = 'imdb_title'")}
    assert "tt0000090" in imdb and "tt0000091" in imdb and "tt0000013" not in imdb  # far runtime, existing work is a series, but Alpha (same runtime range, no proof) stays held
    claim = lambda t: c.execute("SELECT value FROM entity_claim WHERE entity_id = ? AND field = 'reconciliation_released_hold'", (imdb[t],)).fetchone()[0]
    assert claim("tt0000090").startswith("B2") and claim("tt0000091").startswith("A")
    sep = tmp / "v3.sqlite3".replace(".sqlite3", ".separate")
    assert len((sep / "released_from_hold.jsonl").read_text().splitlines()) == 2
    held = [json.loads(x) for x in (sep / "not_entered.jsonl").read_text().splitlines()]
    assert any(h["imdb"] == "tt0000013" and h["reason"].startswith("reconciliation_hold") for h in held)
    assert any(h["imdb"] == "tt0000092" and h["reason"] == "title_without_searchable_characters" for h in held) and "tt0000092" not in imdb  # "$" cannot be a searchable name


def test_imdb_episodes_are_imported_only_with_a_valid_free_position(world):
    report, c, _ = _built(world)
    one = lambda sql, *a: c.execute(sql, a).fetchone()[0]
    imdb = {r[0]: r[1] for r in c.execute("SELECT value, entity_id FROM external_id WHERE scheme = 'imdb_title'")}
    new = imdb["tt0000023"]  # series without season works: the parent is the series; season 1, episode 3
    assert tuple(c.execute("SELECT kind, parent_work_id, season_number, episode_number, release_year, runtime_min FROM work WHERE work_id = ?", (new,)).fetchone()) == ("episode", 5, 1, 3, 2012, 30)
    assert tuple(c.execute("SELECT entry_route, identification FROM work_status WHERE work_id = ?", (new,)).fetchone()) == ("imdb_episode", "imdb_episode_parent_id")
    assert one("SELECT value FROM work_rating WHERE work_id = ?", new) == 7.0
    assert one("SELECT parent_work_id FROM work WHERE work_id = ?", imdb["tt0000032"]) == 42  # the existing season work is the parent
    assert not ({"tt0000024", "tt0000025", "tt0000026", "tt0000027"} & set(imdb))  # no season/number, position taken, series without episodes here
    assert report["counts"]["episodes_not_imported:no_title"] == 1  # a title with no letters cannot be a primary name
    assert report["counts"]["episodes_imported"] == 2 and report["counts"]["episodes_not_imported:no_season_or_number"] == 1
    assert report["counts"]["episodes_not_imported:position_taken"] == 3  # tt22 (1x2, candidate only), tt25 and tt38 (Seasonal 1x1 and 1x3, candidates only)
    # an episode that already has an IMDb id never receives a second one: the match is only a candidate
    assert one("SELECT COUNT(*) FROM external_id WHERE entity_id = 44 AND scheme = 'imdb_title'") == 1 and "tt0000038" not in imdb
    assert one("SELECT tier FROM external_id_candidate WHERE entity_id = 44 AND value = 'tt0000038'") == "episode_number_only"
    assert report["counts"]["episode_match_refused:episode_already_has_another_imdb_id"] == 1


def test_unique_rule_strata_and_schema_labels():
    from cinema_db import schema_v3 as V3
    from cinema_db.harness.build import reconcile_rules as RR
    assert RR.identification_for_rule("director_on_page_matches_no_candidate") == "imdb_title_year_unique_director_mismatch"
    assert RR.identification_for_rule("no_director_on_page") == "imdb_title_year_unique"
    ddl = next(t for t in V3.TABLES_V3 if "CREATE TABLE work_status" in t)
    assert "imdb_title_year_unique_director_mismatch" in ddl and "imdb_episode_parent_id" in ddl


def test_reconcile_rules_are_conservative():
    from cinema_db.harness.build import reconcile_rules as RR
    ok = {"birth": 1960, "death": None}
    # a shared id is no proof; what matters is the dates
    assert RR.merge_check(1960, None, ok, {"birth": None, "death": None}, True)[0]
    assert not RR.merge_check(1960, None, ok, {"birth": 1961, "death": None}, True)[0]                  # birth years differ
    assert not RR.merge_check(1960, None, ok, {"birth": None, "death": 1991}, True)[0]                  # a death IMDb does not confirm (father and son)
    assert not RR.merge_check(1960, None, ok, {"birth": None, "death": None}, False)[0]                 # no credit on the same work and role
    assert not RR.merge_check(None, None, ok, {"birth": None, "death": None}, True)[0]                  # IMDb gives no birth year
    assert RR.primary_imdb_id([{"tconst": "tt2", "known": True, "title_match": True, "votes": 5}, {"tconst": "tt1", "known": True, "title_match": True, "votes": 5}]) == "tt1"
    assert RR.release_class(["film"], False, [{"other_id_known": True, "directors_disjoint": False, "runtime_far": False}]) is None
    assert RR.release_class(["film"], True, [{"other_id_known": True, "directors_disjoint": True, "runtime_far": True}]) is None  # same director: stays held


def test_title_keys_keep_every_script_and_never_match_empty():
    from cinema_db.harness.build import title_keys as TK
    assert TK.norm_title_unicode("상도") == "상도" and TK.norm_title_unicode("Москва слезам не верит") == "москва слезам не верит"
    assert TK.norm_title_unicode("遊☆戯☆王デュエルモンスターズ") == "遊 戯 王デュエルモンスターズ"        # a Japanese voiced mark is part of the letter: kept
    assert TK.norm_title_unicode("Amélie") == "amelie" and TK.norm_title_unicode("Matrix, The") == "the matrix" and TK.norm_title_unicode("Ёлки") == "елки"
    assert TK.title_keys("$") == set() and TK.title_keys("()") == set() and TK.title_keys("") == set() and TK.title_keys(None) == set()
    assert TK.title_keys("상도") != TK.title_keys("해신")                                                    # two different non-Latin titles are no longer both ""


def test_non_latin_page_titles_no_longer_hold_unrelated_works(world):
    # an Italian page whose ORIGINAL title is in another script used to match every non-Latin-named work of the year; now only a real match counts
    inputs, tmp = world
    c = sqlite3.connect(inputs.base)
    for wid, name in ((60, "Haesin"), (61, "상도")):
        c.execute("INSERT INTO entity VALUES (?, 'work')", (wid,))
        c.execute("INSERT INTO work (work_id, kind, release_year, source_id) VALUES (?, 'film', 1977, 1)", (wid,))
        c.execute("INSERT INTO entity_name (entity_id, name, name_norm, kind, is_primary, source_id) VALUES (?,?,?,'primary',1,1)", (wid, name, util.norm_title(name) or name))
    c.commit(); c.close()
    st = sqlite3.connect(inputs.staging)
    _t(st, "tt0000096", "movie", "Other film", 1977, 90); _t(st, "tt0000097", "movie", "Real match", 1977, 90, otitle="상도")
    st.commit(); st.close()
    layer_ = layer.Layer(inputs, tmp / "x.building", tmp / "x.sep")
    layer_.setup()
    index = layer_.cinema_title_index()
    page_title = ("해신",)  # a title in Korean that NO existing work carries
    assert layer_.cinema_candidates(index, layer_.title_row("tt0000096"), page_title) == []
    assert layer_.historical_candidates(layer_.title_row("tt0000096"), page_title) == [61]  # the old check: the empty ASCII key matched the unrelated Korean-named work
    assert layer_.cinema_candidates(index, layer_.title_row("tt0000097")) == [61]                # the original title "상도" is a real match


def test_work_status_view_separates_verified_from_uncertain(world):
    report, c, _ = _built(world)
    levels = {r[0]: r[1] for r in c.execute("SELECT identification, identity_level FROM v_work_status GROUP BY 1, 2")}
    assert levels["catalogue"] == "verified" and levels["imdb_id_given_by_movielens"] == "verified" and levels["imdb_episode_parent_id"] == "verified"
    assert levels.get("imdb_title_year_unique", "rule_based") == "rule_based" and levels.get("imdb_title_year_unique_director_mismatch", "uncertain") == "uncertain"
    assert c.execute("SELECT COUNT(*) FROM v_work_status").fetchone()[0] == c.execute("SELECT COUNT(*) FROM work").fetchone()[0]


def test_weak_page_never_lowers_a_movielens_identification(world, monkeypatch):
    from cinema_db.harness.build import reconcile_rules as RR
    inputs, tmp = world
    # pure rule: MovieLens title+year consistent with the IMDb record -> a weak page does not replace it; an English translation that matches nothing does not confirm
    assert RR.movielens_confirms_identity([(1, "Newfilm (1999)", 1999)], ["Newfilm", None], 1999)
    assert RR.movielens_confirms_identity([(1, "Cidade de Deus (City of God) (2002)", 2002)], ["City of God", "Cidade de Deus"], 2002)
    assert not RR.movielens_confirms_identity([(1, "Silent Witnesses (1914)", 1914)], ["Mute Witnesses", "Nemye svideteli"], 1914)
    assert not RR.movielens_confirms_identity([(1, "Newfilm (1999)", 1999)], ["Newfilm"], 2005)
    assert RR.weak_page_replaces_movielens("imdb_title_year_unique_director_mismatch", False) and not RR.weak_page_replaces_movielens("imdb_title_year_unique_director_mismatch", True)
    assert RR.weak_page_replaces_movielens("imdb_title_year_director_confirmed", True)  # a strong page still wins, as before
    # in the build: a weak page for tt0000010 (MovieLens film "Newfilm (1999)") is kept as claims and the work stays 'given by MovieLens'
    (inputs.audit_dir / "dump_scan.jsonl").write_text((inputs.audit_dir / "dump_scan.jsonl").read_text() + "\n" + json.dumps(
        {"kind": "film_page", "page_id": 103, "title": "Nuovo film", "year": 1999, "original_title": None, "director": "Zed Q"}))
    inputs.memo["pages"]["rejected"][103] = ("Nuovo film", "plot_too_short")
    monkeypatch.setattr(layer.AS, "classify_page", lambda rec, st, pnames, crew: ("dubious", None, {}) if rec["page_id"] == 103 else orig_classify(rec, st, pnames, crew))
    monkeypatch.setattr(layer.AS, "dubious_pages", lambda ctx, st: ({}, [], [{"page_id": 103, "tconst": "tt0000010", "reason": "director_on_page_matches_no_candidate"}]))
    report, c, _ = _built(world, "weak.sqlite3")
    w = c.execute("SELECT entity_id FROM external_id WHERE scheme='imdb_title' AND value='tt0000010'").fetchone()[0]
    assert tuple(c.execute("SELECT entry_route, identification FROM work_status WHERE work_id=?", (w,)).fetchone()) == ("imdb_movielens", "imdb_id_given_by_movielens")
    assert c.execute("SELECT COUNT(*) FROM external_id WHERE entity_id=? AND scheme='wikipedia_it'", (w,)).fetchone()[0] == 0   # the weak link is not attached
    claims = {(r["field"], r["value"]) for r in c.execute("SELECT field, value FROM entity_claim WHERE entity_id=?", (w,))}
    assert {("wikipedia_it_page_not_attached", "Nuovo film"), ("wikipedia_it_page_director_conflict", "Zed Q"),
            ("identity_confirmed_by", "movielens_link_title_and_year_consistent_with_imdb")} <= claims
    assert report["counts"]["weak_page_kept_as_claim_over_movielens"] == 1


orig_classify = layer.AS.classify_page


def test_movielens_layer_maps_films_genres_and_tags_and_documents_every_exclusion(world):
    import dataclasses

    inputs, tmp = world
    report = layer.run_layer(dataclasses.replace(inputs, movielens_layer=True), tmp / "v4.sqlite3", log=lambda *_: None)
    c = sqlite3.connect(tmp / "v4.sqlite3")
    one = lambda sql, *a: c.execute(sql, a).fetchone()[0]
    assert one("SELECT value FROM build_info WHERE key = 'schema_version'") == "4" and one("SELECT COUNT(*) FROM ml_movie") == 14
    ml = {r[0]: r[1:] for r in c.execute("SELECT movie_id, work_id, reason, n_ratings FROM ml_movie")}
    assert ml[1][0] == 1 and ml[1][1] is None and ml[1][2] == 500                       # a catalogue film
    assert ml[3][0] is None and ml[3][1] == "outside_entry_rule:video"                    # a video: documented, not invented
    assert ml[4][0] is None and ml[4][1] == "flagged_adult"
    assert ml[13][0] is not None                                                          # an IMDb episode whose title and year MovieLens confirms
    assert ml[14][0] is None and ml[14][1] == "id_belongs_to_an_episode_not_confirmed_by_title_and_year"  # same kind of id, title does not agree: no rating given to an episode
    assert one("SELECT COUNT(*) FROM ml_movie WHERE work_id IS NULL AND reason IS NULL") == 0
    # one MovieLens film per work, and every rating row is the ml_movie row
    assert one("SELECT COUNT(*) FROM (SELECT work_id FROM ml_movie WHERE work_id IS NOT NULL GROUP BY work_id HAVING COUNT(*) > 1)") == 0
    assert one("SELECT COUNT(*) FROM work_rating r JOIN source s USING(source_id) WHERE s.name LIKE 'movielens%'") == one("SELECT COUNT(*) FROM ml_movie WHERE work_id IS NOT NULL AND n_ratings > 0")
    # genres are MovieLens' own, only of mapped films; tags count DISTINCT users and are normalised
    assert sorted(g for (g,) in c.execute("SELECT g.name FROM work_ml_genre x JOIN ml_genre g USING(ml_genre_id) WHERE x.work_id = 1")) == ["Comedy", "Drama"]
    assert one("SELECT COUNT(*) FROM work_ml_genre x JOIN ml_movie m USING(work_id) WHERE m.movie_id = 3") == 0
    assert one("SELECT n_users FROM work_tag WHERE tag_norm = 'time travel' AND work_id = 1") == 2
    assert one("SELECT n_users FROM work_tag WHERE tag_norm = 'funny' AND work_id = 1") == 1
    assert one("SELECT COUNT(*) FROM work_tag WHERE tag_norm = 'x'") == 0 and report["counts"]["ml_tag_pairs_of_excluded_films"] >= 1
    assert one("SELECT COUNT(*) FROM v_ml_movie WHERE status = 'excluded'") == one("SELECT COUNT(*) FROM ml_movie WHERE work_id IS NULL")


def test_episode_confirmation_accepts_a_series_prefix_but_not_a_different_title():
    from cinema_db.harness.build.movielens_layer import episode_confirmed

    row = ("tvEpisode", "Blue Harvest", "Blue Harvest", None, 2007)
    assert episode_confirmed(1, "Family Guy Presents: Blue Harvest (2007)", 2007, row)
    assert episode_confirmed(1, "Blue Harvest (2007)", 2007, row)
    assert not episode_confirmed(1, "Family Guy Presents: Blue Harvest (2007)", 2012, row)          # year too far
    assert not episode_confirmed(1, "Twin Peaks (1989)", 1989, ("tvEpisode", "Episode #1.1", "Episode #1.1", None, 1989))
    assert not episode_confirmed(1, "CSI: Immortality (2015)", 2015, ("tvMovie", "CSI: Immortality", "CSI: Immortality", None, 2015))  # not an episode in IMDb
