"""A0 audit tools: normalisation, dump scan, causes of missing films, duplicates, curve, read-only behaviour. Offline, miniature data."""
from __future__ import annotations

import bz2
import json
import sqlite3
from pathlib import Path

import pytest

from cinema_db.harness.audit import dump_scan, sections, util
from cinema_db.schema import create_database


def test_title_normalisation_and_movielens_parsing():
    assert util.norm_title("Godfather, The") == "the godfather"
    assert util.norm_title("Amélie") == "amelie"
    assert util.strip_qualifier("Fight Club (film)") == "Fight Club"
    assert util.strip_qualifier("Bianca (film 1984)") == "Bianca"
    assert util.strip_qualifier("Solaris (romanzo)") == "Solaris (romanzo)"
    names, year = util.parse_movielens_title("City of Lost Children, The (Cité des enfants perdus, La) (1995)")
    assert year == 1995 and names == ["City of Lost Children, The", "Cité des enfants perdus, La"]
    assert util.parse_movielens_title("Se7en") == (["Se7en"], None)


def test_imdb_identifier_normalisation():
    assert util.imdb_tt("114709") == "tt0114709" and util.imdb_tt(114709) == "tt0114709"
    assert util.imdb_tt("tt0114709") == "tt0114709"
    assert util.imdb_tt("") is None and util.imdb_tt(None) is None and util.imdb_tt("abc") is None


def _page(pid: int, title: str, text: str, ns: int = 0, redirect: str | None = None) -> str:
    red = f'<redirect title="{redirect}" />' if redirect else ""
    return (f"<page><title>{title}</title><ns>{ns}</ns><id>{pid}</id>{red}"
            f'<revision><id>1</id><text bytes="1">{text}</text></revision></page>')


def _dump(tmp: Path) -> Path:
    film = "{{Film\n|titolo originale = Fight Club\n|anno uscita = 1999\n|regista = [[David Fincher]]\n}}\nIntro\n== Trama ==\nTesto lungo."
    no_plot = "{{Film\n|titolo originale = Girlfight\n|anno uscita = 2000\n}}\n== Produzione ==\nx"
    pages = [
        _page(1, "Fight Club (film)", film), _page(2, "Girlfight", no_plot), _page(3, "Fight Club", "", redirect="Fight Club (film)"),
        _page(4, "Altra voce", "niente"), _page(5, "Discussione:Fight Club", film, ns=1),
    ]
    path = tmp / "mini.xml.bz2"
    path.write_bytes(bz2.compress(("<mediawiki>" + "".join(pages) + "</mediawiki>").encode()))
    return path


def test_dump_scan_extracts_film_pages_and_target_hits(tmp_path):
    out = tmp_path / "scan.jsonl"
    stats = dump_scan.run_scan(frozenset({"fight club", "altra voce"}), out, dump=_dump(tmp_path))
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert stats["pages"] == 5 and stats["film_pages"] == 2  # the namespace-1 page is ignored
    films = {r["title"]: r for r in rows if r["kind"] == "film_page"}
    assert films["Fight Club (film)"]["year"] == 1999 and films["Fight Club (film)"]["plot_heading"] == "trama"
    assert films["Fight Club (film)"]["director"] == "David Fincher"
    assert films["Girlfight"]["plot_heading"] is None
    hits = {r["title"]: r for r in rows if r["kind"] == "target_hit"}
    assert hits["Fight Club"]["redirect_to"] == "Fight Club (film)" and hits["Altra voce"]["film_infobox"] is False
    assert "Girlfight" not in hits


def test_dump_cause_classification():
    film = {"page_id": 10, "title": "Fight Club (film)", "year": 1999, "kind": "film_page"}
    film_by_key = {"fight club": [film]}
    m = {"year": 1999}
    rejected = {10: ("Fight Club (film)", "no_plot_section")}
    cause, ev = sections._dump_cause(m, ["fight club"], film_by_key, {}, {}, rejected, set())
    assert cause == "itwiki_film_page_rejected:no_plot_section" and ev["match"] == "year_confirmed"
    cause, _ = sections._dump_cause({"year": 1950}, ["fight club"], film_by_key, {}, {}, rejected, set())
    assert cause == "itwiki_title_only_candidate_year_not_confirmed"  # same title, other year: never counted as the same film
    cause, ev = sections._dump_cause(m, ["fight club"], film_by_key, {}, {}, {}, {10})
    assert cause == "itwiki_film_page_in_extraction_but_not_in_cinema"
    hit = {"key": "xyz", "redirect_to": None, "film_infobox": False, "page_id": 5, "title": "Xyz"}
    cause, _ = sections._dump_cause(m, ["xyz"], {}, {"xyz": [hit]}, {}, {}, set())
    assert cause == "itwiki_page_without_film_infobox"
    cause, _ = sections._dump_cause(m, ["nothing"], {}, {}, {}, {}, set())
    assert cause == "no_itwiki_page_with_that_title"


@pytest.fixture()
def mini(tmp_path):
    """Miniature cinema database (real schema) and MovieLens database, plus a context with the other archives stubbed."""
    db = create_database(tmp_path / "cinema.sqlite3")
    c = sqlite3.connect(db)
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("INSERT INTO source (source_id, name, kind, license, usage_scope, attribution_required) VALUES (1, 's', 'dataset', 'x', 'unverified', 0)")

    def entity(eid, etype):
        c.execute("INSERT INTO entity VALUES (?,?)", (eid, etype))

    def work(wid, title, year, kind="film", ids=()):
        entity(wid, "work")
        c.execute("INSERT INTO work (work_id, kind, release_year, source_id) VALUES (?,?,?,1)", (wid, kind, year))
        c.execute("INSERT INTO entity_name (entity_id, name, name_norm, kind, is_primary, source_id) VALUES (?,?,?,?,1,1)",
                  (wid, title, util.norm_title(title), "primary"))
        seen = set()
        for scheme, value in ids:  # a second value of the same scheme is stored as non-primary (the schema allows one primary)
            c.execute("INSERT INTO external_id (entity_id, scheme, value, is_primary, source_id) VALUES (?,?,?,?,1)",
                      (wid, scheme, value, int(scheme not in seen)))
            seen.add(scheme)

    def person(pid, name, birth=None):
        entity(pid, "person")
        c.execute("INSERT INTO person (person_id, birth_year, source_id) VALUES (?,?,1)", (pid, birth))
        c.execute("INSERT INTO entity_name (entity_id, name, name_norm, kind, is_primary, source_id) VALUES (?,?,?,?,1,1)",
                  (pid, name, util.norm_title(name), "primary"))

    work(1, "Alpha", 2000, ids=[("imdb_title", "tt0000001"), ("imdb_title", "tt0000011"), ("tmdb_movie", "100")])
    work(2, "Beta", 2001, ids=[("imdb_title", "tt0000002")])
    work(3, "Twin", 1990, ids=[("imdb_title", "tt0000003")])
    work(4, "Twin", 1990, ids=[("imdb_title", "tt0000004")])
    person(10, "Ann Lee", 1970); person(11, "Ann Lee", 1970); person(12, "Bob Roy", 1950); person(13, "Bob Roy", 1980)
    for wid, pid, role in ((1, 10, "director"), (1, 11, "director"), (3, 12, "director"), (4, 13, "director"), (2, 10, "cast")):
        c.execute("INSERT INTO credit (work_id, person_id, role, source_id) VALUES (?,?,?,1)", (wid, pid, role))
    c.commit(); c.close()

    ml = sqlite3.connect(tmp_path / "ml.sqlite3")
    ml.executescript("""
        CREATE TABLE movies (movie_id INTEGER PRIMARY KEY, title TEXT, clean_title TEXT, year INTEGER);
        CREATE TABLE links (movie_id INTEGER PRIMARY KEY, imdb_id TEXT, tmdb_id TEXT);
        CREATE TABLE movie_stats (movie_id INTEGER PRIMARY KEY, n_ratings INTEGER, avg_rating REAL, first_rated_at INTEGER, last_rated_at INTEGER);
        CREATE TABLE movie_genres (movie_id INTEGER, genre TEXT);
        INSERT INTO movies VALUES (1,'Alpha (2000)','Alpha',2000),(2,'Gamma (1999)','Gamma',1999),(3,'Delta (1980)','Delta',1980),(4,'Alpha Again (2000)','x',2000);
        INSERT INTO links VALUES (1,'1','100'),(2,'99','555'),(3,'98','556'),(4,'97','100');
        INSERT INTO movie_stats VALUES (1,500,4.0,0,0),(2,80,3.5,0,0),(3,3,2.0,0,0),(4,60,3.0,0,0);
        INSERT INTO movie_genres VALUES (2,'Drama');
    """)
    ml.commit(); ml.close()
    ctx = sections.Context(tmp_path / "out", cinema=db, movielens=tmp_path / "ml.sqlite3")
    return ctx, db


def test_curve_and_missing_causes_without_dump(mini):
    ctx, _ = mini
    curve = sections.ml_relevance_curve(ctx)["by_threshold"]
    by = {r["min_ratings"]: r for r in curve}
    assert by[50]["ml_films"] == 3 and by[50]["missing_from_cinema"] == 2 and by[1]["missing_from_cinema"] == 3
    ctx._memo.update(v3=[], s5={"series": [], "tv_movies": [], "uncertain": []},
                     film_snap={"entities": {}}, series_snap={"entities": {}},
                     pages={"candidates": {}, "rejected": {}, "excluded": []})
    summary, rows = sections.ml_missing_analysis(ctx)
    causes = {r["title"]: r["cause"] for r in rows}
    assert causes["Alpha Again (2000)"] == "present_in_cinema_with_another_imdb_id"  # same TMDb id 100 as Alpha
    assert causes["Gamma (1999)"] == "unclassified_dump_not_scanned"
    assert summary["missing_total"] == 3 and summary["missing_ge50"] == 2 and summary["dump_scanned"] is False


def test_duplicates_candidates_are_classified_not_merged(mini):
    ctx, db = mini
    ctx._memo.update(v3=[], film_snap={"entities": {}}, series_snap={"entities": {}})
    summary, cand = sections.duplicates(ctx)
    assert summary["works_multiple_ids"] == {"imdb_title": 1}
    assert [r["work_id"] for r in cand["work_multiple_ids"]] == [1]
    assert summary["work_homonym_pairs_by_class"] == {"undetermined_director_unknown": 0} or "homonym_different_directors" in summary["work_homonym_pairs_by_class"]
    assert summary["work_homonym_pairs_by_class"]["homonym_different_directors"] == 1
    classes = summary["person_pairs_by_class"]
    assert classes["same_person_candidate_strong_shared_work_and_role"] == 1  # Ann Lee twice as director of Alpha
    assert classes["homonym_different_birth_year"] == 1  # the two Bob Roy
    # read-only: the database was not modified by the audit
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM credit").fetchone()[0] == 5


def test_audit_connections_cannot_write(mini):
    ctx, _ = mini
    with pytest.raises(sqlite3.OperationalError):
        ctx.cinema.execute("INSERT INTO build_info VALUES ('x', 'y')")
    with pytest.raises(sqlite3.OperationalError):
        ctx.ml_db.execute("DELETE FROM movies")


def test_results_are_deterministic(mini):
    ctx, _ = mini
    ctx._memo.update(v3=[], s5={"series": [], "tv_movies": [], "uncertain": []}, film_snap={"entities": {}}, series_snap={"entities": {}},
                     pages={"candidates": {}, "rejected": {}, "excluded": []})
    first = json.dumps(sections.ml_missing_analysis(ctx)[0], sort_keys=True)
    second = json.dumps(sections.ml_missing_analysis(ctx)[0], sort_keys=True)
    assert first == second
