"""A1 IMDb tools on miniature data: TSV parsing, staging filters, classification of MovieLens titles, Italian-page tiers,
person matching tiers, loss tracing. Offline."""
from __future__ import annotations

import gzip
import json
import sqlite3
from pathlib import Path

import pytest

from cinema_db.harness.audit import imdb_load as L
from cinema_db.harness.audit import imdb_sections as S
from cinema_db.harness.audit import sections, util
from cinema_db.schema import create_database


def _gz(path: Path, header: str, lines: list[str]) -> Path:
    path.write_bytes(gzip.compress(("\t".join(header.split()) + "\n" + "\n".join(lines) + "\n").encode()))
    return path


def test_parsing_helpers():
    assert L.opt("\\N") is None and L.opt("x") == "x" and L.opt_int("\\N") is None and L.opt_int("1999") == 1999
    assert L.tid("tt0000012") == 12 and L.tid("nm1") is None and L.nid("nm0000002") == 2
    assert L.parse_characters('["Tyler Durden","Narrator"]') == ["Tyler Durden", "Narrator"]
    assert L.parse_characters("\\N") == [] and L.parse_characters("not json") == [] and L.parse_characters('"x"') == []
    assert L.person_norm("Edward Norton") == L.person_norm("norton, Edward".replace(",", ""))


def test_staging_keeps_screen_titles_interest_and_filters_principals(tmp_path):
    basics = _gz(tmp_path / "b.gz", "tconst titleType primaryTitle originalTitle isAdult startYear endYear runtimeMinutes genres", [
        "tt0000001\tmovie\tAlpha\tAlpha\t0\t2000\t\\N\t100\tDrama", "tt0000002\ttvEpisode\tEp\tEp\t0\t2001\t\\N\t45\tComedy",
        "tt0000003\ttvEpisode\tWanted episode\tWanted episode\t0\t2002\t\\N\t\\N\t\\N", "tt0000004\tvideoGame\tGame\tGame\t0\t2003\t\\N\t\\N\t\\N"])
    conn = L.create_staging(tmp_path / "s.sqlite3")
    stats = L.stage_basics(basics, conn, {3})
    assert stats["by_type"]["tvEpisode"] == 2 and stats["kept"] == 2  # the movie and the episode of interest only
    assert {r[0] for r in conn.execute("SELECT tconst FROM title")} == {"tt0000001", "tt0000003"}
    principals = _gz(tmp_path / "p.gz", "tconst ordering nconst category job characters", [
        'tt0000001\t1\tnm0000010\tactor\t\\N\t["Hero"]', "tt0000009\t1\tnm0000011\tactor\t\\N\t\\N", "tt0000001\t2\tnm0000012\tdirector\t\\N\t\\N"])
    p = L.stage_principals(principals, conn, {1})
    assert p["rows"] == 3 and p["kept"] == 2
    crew = _gz(tmp_path / "c.gz", "tconst directors writers", ["tt0000001\tnm0000012\tnm0000013,nm0000014", "tt0000009\t\\N\t\\N"])
    L.stage_crew(crew, conn, {1})
    people = L.needed_people(conn, {1})
    assert people == {10, 12, 13, 14}
    names = _gz(tmp_path / "n.gz", "nconst primaryName birthYear deathYear primaryProfession knownForTitles", [
        "nm0000010\tAnn Lee\t1970\t\\N\tactress\ttt0000001", "nm0000099\tNobody\t\\N\t\\N\t\\N\t\\N"])
    assert L.stage_names(names, conn, people)["kept"] == 1


@pytest.fixture()
def env(tmp_path):
    db = create_database(tmp_path / "cinema.sqlite3")
    c = sqlite3.connect(db)
    c.execute("INSERT INTO source (source_id, name, kind, license, usage_scope, attribution_required) VALUES (1, 's', 'dataset', 'x', 'unverified', 0)")

    def work(wid, title, year, imdb=None, kind="film"):
        c.execute("INSERT INTO entity VALUES (?, 'work')", (wid,))
        c.execute("INSERT INTO work (work_id, kind, release_year, source_id) VALUES (?,?,?,1)", (wid, kind, year))
        c.execute("INSERT INTO entity_name (entity_id, name, name_norm, kind, is_primary, source_id) VALUES (?,?,?,'primary',1,1)", (wid, title, util.norm_title(title)))
        if imdb:
            c.execute("INSERT INTO external_id (entity_id, scheme, value, source_id) VALUES (?,'imdb_title',?,1)", (wid, imdb))

    def person(pid, name, birth):
        c.execute("INSERT INTO entity VALUES (?, 'person')", (pid,))
        c.execute("INSERT INTO person (person_id, birth_year, source_id) VALUES (?,?,1)", (pid, birth))
        c.execute("INSERT INTO entity_name (entity_id, name, name_norm, kind, is_primary, source_id) VALUES (?,?,?,'primary',1,1)", (pid, name, util.norm_name if False else name.lower()))

    work(1, "Alpha", 2000, "tt0000001"); work(2, "Beta", 2001, "tt0000002")
    person(10, "Ann Lee", 1970); person(11, "Bob Roy", 1950); person(12, "Cy Dee", None)
    for w, p, role, ch in ((1, 10, "cast", None), (2, 10, "cast", None), (1, 11, "cast", "Hero"), (1, 12, "director", None)):
        c.execute("INSERT INTO credit (work_id, person_id, role, character_name, source_id) VALUES (?,?,?,?,1)", (w, p, role, ch))
    c.commit(); c.close()
    ml = sqlite3.connect(tmp_path / "ml.sqlite3")
    ml.executescript("""
      CREATE TABLE movies (movie_id INTEGER PRIMARY KEY, title TEXT, clean_title TEXT, year INTEGER);
      CREATE TABLE links (movie_id INTEGER PRIMARY KEY, imdb_id TEXT, tmdb_id TEXT);
      CREATE TABLE movie_stats (movie_id INTEGER PRIMARY KEY, n_ratings INTEGER, avg_rating REAL, first_rated_at INTEGER, last_rated_at INTEGER);
      CREATE TABLE movie_genres (movie_id INTEGER, genre TEXT);
      INSERT INTO movies VALUES (1,'Alpha (2000)','',2000),(2,'Gamma (1999)','',1999),(3,'Tiny (2005)','',2005),(4,'Ep (2001)','',2001),(5,'Lost (1990)','',1990),(6,'Alpha Redux (2000)','',2000);
      INSERT INTO links VALUES (1,'1','1'),(2,'20','2'),(3,'30','3'),(4,'40','4'),(5,'50','5'),(6,'60','6');
      INSERT INTO movie_stats VALUES (1,500,4,0,0),(2,80,3,0,0),(3,70,3,0,0),(4,60,3,0,0),(5,55,3,0,0),(6,51,3,0,0);
      INSERT INTO movie_genres VALUES (2,'Drama');
    """)
    ml.commit(); ml.close()
    ctx = sections.Context(tmp_path / "out", cinema=db, movielens=tmp_path / "ml.sqlite3")
    st = L.create_staging(tmp_path / "st.sqlite3")
    titles = [("tt0000001", 1, "movie", "Alpha", "Alpha", 0, 2000, None, 100, "Drama", "alpha", "alpha"),
              ("tt0000020", 20, "movie", "Gamma", "Gamma", 0, 1999, None, 95, "Drama,Documentary", "gamma", "gamma"),
              ("tt0000030", 30, "short", "Tiny", "Tiny", 0, 2005, None, 8, "Short", "tiny", "tiny"),
              ("tt0000040", 40, "tvEpisode", "Ep", "Ep", 0, 2001, None, 40, None, "ep", "ep"),
              ("tt0000060", 60, "movie", "Alpha Redux", "Alpha", 0, 2000, None, 90, None, "alpha redux", "alpha")]
    st.executemany("INSERT INTO title VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", titles)
    st.commit()
    return ctx, st, tmp_path


def test_movielens_classification(env):
    ctx, st, _ = env
    summary, rows = S.ml_missing_classification(ctx, st)
    by_id = {r["imdb"]: r for r in rows}
    assert by_id["tt0000020"]["class"] == "lungometraggio" and by_id["tt0000030"]["class"] == "cortometraggio"
    assert by_id["tt0000040"]["class"] == "episodio" and by_id["tt0000050"]["class"] == "non_identificabile_via_imdb"
    # 'Alpha Redux' has the original title of Alpha (2000): reported as a candidate already in cinema, not as a new film
    assert by_id["tt0000060"]["cinema_candidates_same_title_year"] == [1]
    assert summary["missing_total"] == 5 and summary["movies"]["movie_without_cinema_candidate"] == 1
    assert summary["not_identifiable"]["count"] == 1 and summary["movies"]["movie_documentary"] == 1
    assert summary["movies_by_threshold"]["50"] == {"movies": 2, "without_cinema_candidate": 1}


def test_italian_page_tiers(env):
    ctx, st, tmp = env
    st.executemany("INSERT INTO title VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
        ("tt0000100", 100, "movie", "Delta", "Delta", 0, 1980, None, 90, None, "delta", "delta"),
        ("tt0000101", 101, "movie", "Epsilon", "Epsilon", 0, 1981, None, 90, None, "epsilon", "epsilon"),
        ("tt0000102", 102, "movie", "Epsilon", "Epsilon", 0, 1981, None, 90, None, "epsilon", "epsilon")])
    st.executemany("INSERT INTO crew VALUES (?,?,?)", [("tt0000100", "nm0000500", None), ("tt0000101", "nm0000500", None), ("tt0000102", "nm0000500", None),
                                                     ("tt0000001", "nm0000500", None)])
    st.execute("INSERT INTO name VALUES ('nm0000500','Jo Smith',1950,NULL,NULL,?)", (L.person_norm("Jo Smith"),))
    st.commit()
    pages = [{"kind": "film_page", "page_id": 1, "title": "Delta (film)", "year": 1980, "original_title": None, "director": "Jo Smith"},
             {"kind": "film_page", "page_id": 2, "title": "Epsilon", "year": 1981, "original_title": None, "director": "Jo Smith"},
             {"kind": "film_page", "page_id": 3, "title": "Zeta", "year": 1970, "original_title": None, "director": "Jo Smith"},
             {"kind": "film_page", "page_id": 4, "title": "Delta", "year": 1980, "original_title": None, "director": "Someone Else"},
             {"kind": "film_page", "page_id": 5, "title": "Alpha", "year": 2000, "original_title": None, "director": "Jo Smith"}]
    (tmp / "out").mkdir()
    (tmp / "out/dump_scan.jsonl").write_text("\n".join(json.dumps(p) for p in pages))
    ctx._memo["pages"] = {"candidates": {}, "excluded": [], "rejected": {i: ("t", "plot_too_short") for i in range(1, 6)}}
    ctx._memo["v3"] = [{"wikipedia_page_id": 50, "imdb_id": "tt0000100"}, {"wikipedia_page_id": 51, "imdb_id": "tt0000999"}]
    pages += [{"kind": "film_page", "page_id": 50, "title": "Delta", "year": 1980, "original_title": None, "director": "Jo Smith"},
              {"kind": "film_page", "page_id": 51, "title": "Delta", "year": 1980, "original_title": None, "director": "Jo Smith"}]
    (tmp / "out/dump_scan.jsonl").write_text("\n".join(json.dumps(p) for p in pages))
    summary, rows = S.italian_pages(ctx, st)
    tier = {r["page_id"]: r["tier"] for r in rows}
    assert tier[1] == "identified_without_plot"       # unique, same year, title and director match
    assert tier[2] == "dubious"                       # two IMDb titles qualify: not decided automatically
    assert tier[3] == "no_candidate"
    assert tier[4] == "dubious"                       # title and year match but the director does not
    assert tier[5] == "already_in_cinema"             # candidate with a director match whose identifier cinema already holds
    assert summary["tiers"]["identified_without_plot"] == 1
    # ground truth: page 50 is identified as the right title, page 51 (known id differs) counts as a wrong identification
    v = summary["validation_on_known_pages"]
    assert v["identified_correct"] == 1 and v["identified_wrong"] == 1 and v["precision_pct"] == 50.0


def test_new_film_estimate_counts_the_overlap_once():
    ml = [{"imdb": "tt1", "imdb_type": "movie"}, {"imdb": "tt2", "imdb_type": "movie", "cinema_candidates_same_title_year": [1]},
          {"imdb": "tt3", "imdb_type": "short"}]
    pages = [{"tier": "identified_without_plot", "tconst": "tt1", "imdb_type": "movie"}, {"tier": "identified_without_plot", "tconst": "tt4", "imdb_type": "movie"},
             {"tier": "identified_without_plot", "tconst": "tt5", "imdb_type": "short"}, {"tier": "dubious", "tconst": None}]
    est = S.new_film_estimate(ml, pages)
    assert est == {"movielens_movies_without_cinema_candidate": 1, "italian_pages_identified_movies": 2, "italian_pages_identified_all_types": 3,
                   "in_both_movies": 1, "union_movies": 2}


def test_person_matching_tiers_and_cast_order(env):
    ctx, st, _ = env
    st.executemany("INSERT INTO principal VALUES (?,?,?,?,?,?)", [
        ("tt0000001", 1, "nm1", "actress", None, '["Heroine"]'), ("tt0000001", 2, "nm2", "actor", None, '["Hero"]'),
        ("tt0000002", 1, "nm1", "actress", None, None)])
    st.executemany("INSERT INTO name VALUES (?,?,?,?,?,?)", [("nm1", "Ann Lee", 1970, None, None, L.person_norm("Ann Lee")),
                                                              ("nm2", "Bob Roy", 1999, None, None, L.person_norm("Bob Roy"))])
    st.executemany("INSERT INTO crew VALUES (?,?,?)", [("tt0000001", "nm3", None)])
    st.execute("INSERT INTO name VALUES ('nm3','Cy Dee',NULL,NULL,NULL,?)", (L.person_norm("Cy Dee"),))
    st.commit()
    summary, cand = S.people_and_cast(ctx, st)
    tiers = {r["person_id"]: r["tier"] for r in cand["person_nconst"]}
    assert tiers[10] == "strong"                       # two titles agree
    assert tiers[11] == "conflict_birth_year"          # same name and title, birth years 1950 vs 1999
    assert tiers[12] == "weak_single_title_no_birth_confirmation"
    cast = summary["cast_order_and_characters"]
    assert cast["with_ordering"] >= 2 and cast["with_characters"] >= 1 and cast["both_have_character"] == 1
    assert cast["character_comparison"] == {"agree": 1}
    assert summary["persons_resolved_total"] == 3


def test_loss_trace_names_the_exclusion_point(env, tmp_path, monkeypatch):
    ctx, _, tmp = env
    s5 = tmp / "s5"
    s5.mkdir()
    def write(name, rows):
        (s5 / f"{name}.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    write("series", [{"record_id": "wp-1", "title": "A", "catalog_class": "franchise_page_mixed_media", "default_search_eligible": False,
                      "ids_reliable": True, "ids": {"imdb_id": "tt0000700", "qid": "Q1"}},
                     {"record_id": "wp-2", "title": "B", "catalog_class": "series_page", "default_search_eligible": True,
                      "ids_reliable": False, "ids": {"imdb_id": "tt0000701", "qid": "Q2"}}])
    write("tv_movies", [])
    write("excluded", [])
    write("uncertain", [{"record_id": "wp-3", "title": "C", "ids": {"imdb_id": "tt0000702", "qid": "Q3"}}])
    monkeypatch.setattr(util, "S5", s5)
    ctx._memo["pages"] = {"candidates": {}, "excluded": [], "rejected": {99: ("Some film", "no_plot_section")}}
    ctx._memo["film_snap"] = {"entities": {"Q9": {"imdb_title": ["tt0000703"], "sitelink": "Some film"}}}
    ctx._memo.update(s5={"series": [{"imdb": "tt0000700"}, {"imdb": "tt0000701"}], "tv_movies": [], "uncertain": [{"imdb": "tt0000702"}]},
                     v3=[], series_snap={"entities": {}})
    summary, rows = S.build_losses(ctx)
    cause = {r["imdb"]: r["cause"] for r in rows}
    assert cause["tt0000700"] == "series_not_imported:franchise_page_mixed_media"
    assert cause["tt0000701"] == "series_imported_without_identifiers"
    assert cause["tt0000702"] == "series_catalogue_uncertain_records_not_imported"
    assert cause["tt0000703"] == "snapshot_entity_page_rejected_by_film_extraction:no_plot_section"
    assert summary["identifiers_in_local_sources_not_in_cinema"] == 4
