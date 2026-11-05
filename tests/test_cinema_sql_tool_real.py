"""The `cinema_sql` tool against the REAL local database (`cinema_db/data/cinema.sqlite3`, git-ignored): skipped, with the reason, when it is missing.

The expected values were checked by hand against independent SQL on the base tables (not through the views the tool reads) and, for the
sample tests below, are recomputed independently every time.
"""
from __future__ import annotations

import dataclasses
import os
import random
import sqlite3
from pathlib import Path

import pytest

from turn import TOOL_PARAM_TURN_ID
from tool.cinema_db.approved_views import POLICY
from tool.cinema_db.config import CinemaDbConfig
from tool.cinema_db.names import normalize_name
from tool.cinema_db.settings import QueryLimits
from tool.cinema_db.tool import CinemaSqlTool

DB = Path(__file__).resolve().parents[1] / "cinema_db/data/cinema.sqlite3"
pytestmark = pytest.mark.skipif(not DB.is_file(), reason="the local cinema database is not built (python -m cinema_db.harness.build.build)")

GODFATHER, NOLAN, BREAKING_BAD, CRASH_1996, CRASH_2004, CRASH_SERIES = 415700, 310973, 21995, 436264, 368053, 22814


def make_tool(max_queries: int = 40, policy=POLICY) -> CinemaSqlTool:
    return CinemaSqlTool(config=CinemaDbConfig(db_path=str(DB), max_queries_per_turn=max_queries, default_limit=25), policy=policy)


@pytest.fixture(scope="module")
def tool() -> CinemaSqlTool:
    return make_tool()


@pytest.fixture(scope="module")
def raw():
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)  # independent of the tool: base tables, no views, no guard
    yield conn
    conn.close()


def call(tool: CinemaSqlTool, **arguments):
    result = tool.run(query="test request", params=arguments)
    return result, result["metadata"]["cinema_db"]


# 1. a film by title, alias and original title --------------------------------------------------------------------------------------
def test_a_film_is_found_by_its_title_its_alias_and_its_year_disambiguates_the_original_title(tool):
    for title in ("Il padrino", "Il padrino (film)", "il PADRINO"):
        _, m = call(tool, operation="find_work", title=title)
        assert m["status"] == "ok" and m["subject"]["work_id"] == GODFATHER
    _, m = call(tool, operation="find_work", title="The Godfather", year=1972)
    assert m["status"] == "ok" and m["subject"] == {
        "work_id": GODFATHER, "kind": "film", "title": "Il padrino", "original_title": "The Godfather", "year": 1972, "runtime_min": 175,
        "directors": ["Francis Ford Coppola"], "imdb_id": "tt0068646", "tmdb_id": "238", "wikidata_id": "Q47703",
    }


# 2. an external identifier is the identity -----------------------------------------------------------------------------------------
def test_external_identifiers_resolve_without_a_title_search(tool):
    for arguments in ({"imdb_id": "tt0068646"}, {"wikidata_id": "Q47703"}, {"tmdb_id": 238, "type": "film"}, {"work_id": GODFATHER}):
        result, m = call(tool, operation="find_work", **arguments)
        assert m["status"] == "ok" and m["subject"]["work_id"] == GODFATHER
        assert not any("v_name" in c["sql"] for c in result["trace"][0]["data"]["queries"])  # no name lookup: the id was the identity
    _, series = call(tool, operation="find_work", tmdb_id=1396, type="series")
    assert series["subject"]["work_id"] == BREAKING_BAD  # the same number is a different work as a movie: the type picks the scheme
    _, m = call(tool, operation="find_work", tmdb_id=1396, type="film")
    assert m["subject"]["work_id"] != BREAKING_BAD if m["status"] == "ok" else m["status"] == "not_found"


def test_ids_that_point_at_different_works_are_never_resolved_to_one(tool):
    result, m = call(tool, operation="find_work", imdb_id="tt0068646", wikidata_id="Q25188")  # The Godfather and Inception
    assert m["status"] == "ambiguous" and m["reason"] == "ids_disagree"
    assert {c["work_id"] for c in m["candidates"]} == {GODFATHER, 382977} and "follow_up" not in result


def test_an_unknown_identifier_is_not_found_and_offers_one_step_elsewhere(tool):
    result, m = call(tool, operation="find_work", imdb_id="tt9999999")
    assert (m["status"], m["reason"]) == ("not_found", "id_unknown") and result["follow_up"]["available"] is True
    assert result["outcome"]["status"] == "empty"


def test_a_tmdb_id_without_a_type_is_refused_because_film_and_series_ids_overlap(tool):
    result = tool.run(query="x", params={"operation": "find_work", "tmdb_id": 238})
    assert result["outcome"]["status"] == "error" and result["metadata"]["cinema_db"]["error"] == "invalid_request"


# 3. a person ---------------------------------------------------------------------------------------------------------------------
def test_a_person_is_found_by_name_and_by_wikidata_id_with_the_credits_per_role(tool):
    for arguments in ({"person": "Christopher Nolan"}, {"wikidata_id": "Q25191"}, {"person_id": NOLAN}):
        _, m = call(tool, operation="find_person", **arguments)
        assert m["status"] == "ok" and m["subject"]["person_id"] == NOLAN and m["subject"]["birth_year"] == 1970
    assert m["subject"]["credits_by_role"]["director"] == 13


def test_namesakes_are_listed_with_what_tells_them_apart_and_a_birth_year_picks_one(tool):
    _, m = call(tool, operation="find_person", person="John Williams")
    assert m["status"] == "ambiguous" and sorted(c["birth_year"] for c in m["candidates"]) == [1903, 1932]
    composer = next(c for c in m["candidates"] if c["birth_year"] == 1932)
    assert composer["credits_by_role"]["composer"] == 107 and "subject" not in m
    _, picked = call(tool, operation="find_person", person="John Williams", birth_year=1932)
    assert picked["status"] == "ok" and picked["subject"]["person_id"] == composer["person_id"]


# 4. the filmography of a director ----------------------------------------------------------------------------------------------------
def test_the_filmography_of_a_director_lists_each_film_once_with_the_total(tool, raw):
    _, m = call(tool, operation="filmography", person="Christopher Nolan", role="director")
    assert m["status"] == "ok" and m["total"] == 13 and m["shown"] == 13 and not m["truncated"]
    titles = [w["title"] for w in m["works"]]
    assert titles[:3] == ["Following", "Memento", "Insomnia"] and "Inception" in titles and all(w["roles"] == ["director"] for w in m["works"])
    assert [w["year"] for w in m["works"]] == sorted(w["year"] for w in m["works"])
    expected = raw.execute("SELECT count(DISTINCT work_id) FROM credit WHERE person_id = ? AND role = 'director'", (NOLAN,)).fetchone()[0]
    assert m["total"] == expected


def test_year_range_and_order_and_limit_apply_and_a_cut_list_says_so(tool):
    _, m = call(tool, operation="filmography", person="Christopher Nolan", role="director", year_from=2010, year_to=2014, order="desc")
    assert [w["title"] for w in m["works"]] == ["Interstellar", "Il cavaliere oscuro - Il ritorno", "Inception"] and m["total"] == 3
    _, cut = call(tool, operation="filmography", person="Christopher Nolan", role="director", limit=4)
    assert cut["shown"] == 4 and cut["total"] == 13 and cut["truncated"] and "limit" in [n["code"] for n in cut["notes"]]


# 5. the cast of a film ------------------------------------------------------------------------------------------------------------
def test_the_cast_has_characters_a_total_and_no_claimed_order(tool, raw):
    _, m = call(tool, operation="cast", title="Il padrino", limit=50)
    assert m["status"] == "ok" and m["total"] == 40 == raw.execute("SELECT count(*) FROM credit WHERE work_id = ? AND role = 'cast'", (GODFATHER,)).fetchone()[0]
    by_name = {p["name"]: p["character"] for p in m["cast"]}
    assert by_name["Al Pacino"] == "Michael" and by_name["James Caan"] == "Sonny" and by_name["Robert Duvall"] == "Tom Hagen"
    assert "cast_order" in [n["code"] for n in m["notes"]]
    _, few = call(tool, operation="cast", title="Il padrino", limit=5)
    assert few["shown"] == 5 and few["total"] == 40 and few["truncated"]


def test_the_crew_of_a_film_is_grouped_by_role(tool):
    _, m = call(tool, operation="crew", title="Il padrino", role="writer")
    assert m["crew"] == [{"role": "writer", "people": ["Francis Ford Coppola", "Mario Puzo"]}]


# 6. collaborations ---------------------------------------------------------------------------------------------------------------
def test_works_shared_by_two_people_and_the_most_frequent_collaborators(tool):
    _, m = call(tool, operation="collaborations", person="Christopher Nolan", person_b="Michael Caine")
    assert m["status"] == "ok" and [w["year"] for w in m["shared_works"]] == [2005, 2006, 2008, 2010, 2012, 2014, 2017, 2020]
    first = m["shared_works"][0]
    assert first["title"] == "Batman Begins" and "director" in first["roles_of_first"] and "cast" in first["roles_of_second"]
    _, top = call(tool, operation="collaborations", person="Christopher Nolan", role="director", role_b="cast", limit=3)
    assert [(c["name"], c["works"]) for c in top["collaborators"]] == [("Michael Caine", 8), ("Cillian Murphy", 6), ("Christian Bale", 4)]


def test_collaboration_edge_cases_are_reported_not_hidden(tool):
    result, same = call(tool, operation="collaborations", person="Christopher Nolan", person_b="Christopher Nolan")
    assert result["outcome"]["status"] == "error" and same["error"] == "same_person"
    _, unknown = call(tool, operation="collaborations", person="Christopher Nolan", person_b="Zzyzx Qwerty")
    assert unknown["status"] == "not_found" and unknown["which"] == "second_person"


# 7. awards and nominations --------------------------------------------------------------------------------------------------------
def test_awards_of_a_work_separate_wins_from_nominations(tool, raw):
    _, m = call(tool, operation="awards", title="Il padrino", limit=50)
    assert m["total"] == 20 == raw.execute("SELECT count(*) FROM award_result WHERE work_id = ?", (GODFATHER,)).fetchone()[0]
    assert sum(r["outcome"] == "won" for r in m["results"]) == 6 and any(r["person_name"] == "Marlon Brando" for r in m["results"])
    _, won = call(tool, operation="awards", title="Il padrino", outcome="won", limit=50)
    assert won["total"] == 6 and {r["outcome"] for r in won["results"]} == {"won"}
    assert "awards" in [n["code"] for n in m["notes"]]


def test_awards_of_a_person_and_by_award_name_and_year(tool):
    _, person = call(tool, operation="awards", person="Christopher Nolan", year_from=2010, year_to=2011)
    assert {r["work_title"] for r in person["results"]} == {"Inception"} and person["subject"]["person_id"] == NOLAN
    _, named = call(tool, operation="awards", award="Oscar al miglior film", year_from=1973, year_to=1973, outcome="won")
    assert any(r["work_title"] == "Il padrino" and r["category"] == "Oscar al miglior film" for r in named["results"])
    assert named["results"][0]["category"] == "Oscar al miglior film"  # the exact category comes before longer names that contain it


# 8. series, seasons and episodes ---------------------------------------------------------------------------------------------------
def test_a_series_lists_its_seasons_with_both_episode_counts(tool, raw):
    _, m = call(tool, operation="series", title="Breaking Bad")
    assert m["status"] == "ok" and m["subject"]["work_id"] == BREAKING_BAD and [s["season_number"] for s in m["seasons"]] == [1, 2, 3, 4, 5]
    season1 = m["seasons"][0]
    assert (season1["episodes"], season1["numbered_episodes"]) == (8, 7)  # the catalogue holds a repeat: the counts are not claimed to be exact
    assert "episode_duplicates" in [n["code"] for n in m["notes"]]
    assert raw.execute("SELECT count(*) FROM work WHERE kind='episode' AND parent_work_id = ?", (66400,)).fetchone()[0] == 8


def test_the_episodes_of_a_season_and_a_film_is_not_a_series(tool):
    _, m = call(tool, operation="series", title="Breaking Bad", season=2)
    assert m["status"] == "ok" and m["total"] == 13 and [e["episode_number"] for e in m["episodes"]] == list(range(1, 14))
    assert all(e["date"] for e in m["episodes"])
    _, film = call(tool, operation="series", work_id=GODFATHER)
    assert (film["status"], film["reason"]) == ("empty", "not_a_series")


# 9. companies and franchise ----------------------------------------------------------------------------------------------------------
def test_companies_of_a_work_and_the_works_of_a_company(tool):
    _, m = call(tool, operation="companies", title="Il padrino")
    roles = {c["role"]: c["companies"] for c in m["companies"]}
    assert "Paramount Pictures" in roles["production"] and "Paramount Pictures" in roles["distribution"]
    _, company = call(tool, operation="companies", company="Paramount Pictures", limit=50)
    assert company["status"] == "ok" and company["subject"]["name"] == "Paramount Pictures" and company["works"]


def test_a_franchise_lists_its_members_and_warns_that_it_may_be_a_list(tool):
    _, m = call(tool, operation="franchise", title="Il padrino")
    members = {x["title"] for x in m["franchises"][0]["members"]}
    assert m["franchises"][0]["franchise"] == "Il padrino" and {"Il padrino", "Il padrino - Parte II"} <= members
    note = next(n["text"] for n in m["notes"] if n["code"] == "franchise")
    assert "list" in note
    _, by_name = call(tool, operation="franchise", franchise="Il padrino")
    assert by_name["status"] == "ok" and {x["title"] for x in by_name["franchises"][0]["members"]} == members


def test_relations_of_a_work_keep_the_direction_and_the_caveat(tool):
    _, m = call(tool, operation="relations", title="Il padrino")
    pairs = {(r["relation"], r["direction"], r["title"]) for r in m["relations"]}
    assert ("is based on", "forward", "Il padrino") in pairs and ("is followed by", "inverse", "Il padrino - Parte II") in pairs
    assert "relations" in [n["code"] for n in m["notes"]]


def test_the_work_card_gathers_facts_in_few_queries(tool):
    result, m = call(tool, operation="work_card", title="Il padrino")
    assert m["writers"] == ["Francis Ford Coppola", "Mario Puzo"] and m["composers"] == ["Nino Rota"] and "Drama" in m["genres"] and m["queries"] <= 8
    assert len(result["trace"][0]["data"]["queries"]) == m["queries"]


# 10. homonyms and ambiguous results ----------------------------------------------------------------------------------------------
def test_same_title_works_are_alternatives_until_the_request_tells_them_apart(tool):
    _, m = call(tool, operation="find_work", title="Crash")
    assert m["status"] == "ambiguous" and {c["work_id"] for c in m["candidates"]} == {CRASH_1996, CRASH_2004, CRASH_SERIES}
    assert {c["work_id"]: c["directors"][0] for c in m["candidates"] if c["kind"] == "film"} == {CRASH_1996: "David Cronenberg", CRASH_2004: "Paul Haggis"}
    assert call(tool, operation="find_work", title="Crash", year=2004)[1]["subject"]["work_id"] == CRASH_2004
    assert call(tool, operation="find_work", title="Crash", director="Cronenberg")[1]["subject"]["work_id"] == CRASH_1996
    assert call(tool, operation="find_work", title="Crash", type="series")[1]["subject"]["work_id"] == CRASH_SERIES


def test_an_ambiguous_work_returns_alternatives_and_no_data_for_any_operation(tool):
    for operation in ("cast", "awards", "relations", "work_card"):
        result, m = call(tool, operation=operation, title="Crash")
        assert m["status"] == "ambiguous" and m["candidates"] and "cast" not in m and "results" not in m and "follow_up" not in result


# 11. missing data and empty results -------------------------------------------------------------------------------------------------
def test_a_title_that_does_not_exist_is_not_found_and_the_gap_is_not_presented_as_proof(tool):
    result, m = call(tool, operation="find_work", title="Zzyzx Qwerty Movie")
    assert m["status"] == "not_found" and result["follow_up"]["available"] is True
    assert "does not prove" in result["follow_up"]["summary"]


def test_similar_names_are_alternatives_never_the_answer_and_a_wrong_year_is_not_dropped(tool):
    result, typo = call(tool, operation="find_work", title="Il padrin")
    assert typo["status"] == "unverified" and typo["reason"] == "similar_names_only" and "subject" not in typo
    assert GODFATHER in {c["work_id"] for c in typo["candidates"]} and "unverified" in [n["code"] for n in typo["notes"]] and result["follow_up"]["available"]
    _, wrong_year = call(tool, operation="find_work", title="Il padrino", year=1999)
    assert wrong_year["status"] == "unverified" and wrong_year["reason"] == "filters_not_matched" and wrong_year["candidates"][0]["year"] == 1972


def test_an_empty_list_is_empty_with_a_reason_and_a_follow_up_not_an_error(tool):
    result, m = call(tool, operation="filmography", person="Christopher Nolan", role="costume_designer")
    assert (m["status"], m["reason"]) == ("empty", "no_credits_in_catalogue") and result["outcome"] == {"status": "empty", "reason": "no_credits_in_catalogue"}
    assert result["follow_up"]["available"] is True and m["total"] == 0
    _, no_franchise = call(tool, operation="relations", title="Following")
    assert no_franchise["status"] in {"empty", "ok"}


# 12. read-only protections and limits ----------------------------------------------------------------------------------------------
def test_free_sql_is_validated_and_the_database_file_never_changes():
    before = os.stat(DB)
    tool = make_tool()
    ok, m = call(tool, operation="sql", sql="SELECT title, year FROM v_work WHERE work_id = ? LIMIT 1", params=[GODFATHER])
    assert m["status"] == "ok" and m["rows"] == [{"title": "Il padrino", "year": 1972}]
    assert ok["trace"][0]["data"]["queries"][0]["sql"].startswith("SELECT") and "LIMIT 1" in ok["trace"][0]["data"]["queries"][0]["sql"]
    forbidden = [
        "INSERT INTO source (name) VALUES ('x')", "DELETE FROM v_work", "UPDATE v_work SET title = 'x'", "DROP VIEW v_work", "PRAGMA table_info(work)",
        "ATTACH DATABASE 'x.db' AS x", "SELECT * FROM work LIMIT 1", "SELECT * FROM sqlite_master LIMIT 1", "SELECT load_extension('x')",
        "SELECT 1; DROP TABLE work", "SELECT title FROM v_work",
    ]
    for sql in forbidden:
        result = tool.run(query="x", params={"operation": "sql", "sql": sql})
        error = result["metadata"]["cinema_db"].get("error", "")
        assert result["outcome"]["status"] == "error" or sql == "SELECT title FROM v_work", sql
        assert "rows" not in result["metadata"]["cinema_db"] or sql == "SELECT title FROM v_work", sql
        assert "x.db" not in str(result["metadata"]) and "no such" not in error, sql
    after = os.stat(DB)
    assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
    assert not [p for p in DB.parent.iterdir() if p.name.endswith(("-wal", "-shm", "-journal"))]


def test_the_row_limit_is_enforced_even_when_the_sql_asks_for_more(tool):
    result = tool.run(query="x", params={"operation": "sql", "sql": "SELECT work_id FROM v_work LIMIT 5000"})
    m = result["metadata"]["cinema_db"]
    assert (result["outcome"]["status"] == "error") or (len(m["rows"]) <= 50 and m["truncated"])


def test_the_turn_budget_stops_further_queries_and_a_new_turn_has_its_own():
    tool = make_tool(max_queries=3)
    first, m = call(tool, operation="find_work", title="Il padrino", **{})
    assert m["status"] == "ok"  # 2 queries
    arguments = {"operation": "sql", "sql": "SELECT work_id FROM v_work WHERE work_id = ? LIMIT 1", "params": [GODFATHER], TOOL_PARAM_TURN_ID: "turn-A"}
    results = [tool.run(query="x", params=arguments) for _ in range(4)]  # the limit of the turn is 3 queries
    assert [r["outcome"]["status"] for r in results[:3]] == ["ok"] * 3
    result = results[3]
    assert result["metadata"]["cinema_db"]["error"] == "turn_limit" and result["outcome"]["status"] == "error"
    assert tool.run(query="x", params={**arguments, TOOL_PARAM_TURN_ID: "turn-B"})["outcome"]["status"] == "ok"


def test_a_query_that_runs_too_long_or_scans_too_much_is_stopped_not_answered():
    tool = make_tool(policy=dataclasses.replace(POLICY, limits=QueryLimits(timeout_ms=5)))
    heavy = "SELECT count(*) AS n FROM v_credit a JOIN v_credit b ON b.work_id = a.work_id WHERE a.role = ? AND b.role = ? LIMIT 1"
    result = tool.run(query="x", params={"operation": "sql", "sql": heavy, "params": ["cast", "cast"]})
    assert result["outcome"]["status"] == "error" and result["metadata"]["cinema_db"]["error"] in {"timeout", "plan_rejected", "execution_failed"}
    assert "rows" not in result["metadata"]["cinema_db"]


def test_a_missing_database_is_an_error_with_a_follow_up_not_a_crash(tmp_path):
    tool = CinemaSqlTool(config=CinemaDbConfig(db_path=str(tmp_path / "nope.sqlite3"), max_queries_per_turn=3, default_limit=10))
    result = tool.run(query="x", params={"operation": "find_work", "title": "Il padrino"})
    assert result["metadata"]["cinema_db"]["error"] == "db_missing" and result["follow_up"]["available"] is True and result["outcome"]["status"] == "error"
    assert not (tmp_path / "nope.sqlite3").exists()  # a read-only open never creates the file


# 13. correctness and completeness against independent SQL ----------------------------------------------------------------------------
def test_the_name_normalisation_equals_the_one_stored_by_the_build(raw):
    rows = raw.execute("SELECT name, name_norm FROM entity_name WHERE entity_id IN (SELECT work_id FROM work WHERE kind = 'film' LIMIT 3000)").fetchall()
    assert len(rows) > 2000 and all(normalize_name(name) == norm for name, norm in rows)


def test_filmographies_match_an_independent_recomputation_on_a_random_sample(tool, raw):
    rng = random.Random(20261106)
    people = [r[0] for r in raw.execute("SELECT DISTINCT person_id FROM credit WHERE role = 'director'").fetchall()]
    for person_id in rng.sample(people, 40):
        _, m = call(tool, operation="filmography", person_id=person_id, role="director", limit=50)
        kinds = "('film','short','tv_film','series','miniseries')"
        expected = {r[0] for r in raw.execute(f"SELECT c.work_id FROM credit c JOIN work w ON w.work_id = c.work_id WHERE c.person_id = ? AND c.role = 'director' AND w.kind IN {kinds}", (person_id,))}
        if not expected:
            assert m["status"] == "empty"
            continue
        assert m["total"] == len(expected), person_id
        assert {w["work_id"] for w in m["works"]} <= expected and (len(expected) > 50 or {w["work_id"] for w in m["works"]} == expected), person_id


def test_cast_and_award_counts_match_an_independent_recomputation_on_a_random_sample(tool, raw):
    rng = random.Random(20261106)
    films = [r[0] for r in raw.execute("SELECT work_id FROM work WHERE kind = 'film' AND release_year BETWEEN 1950 AND 2018").fetchall()]
    for work_id in rng.sample(films, 40):
        _, cast_result = call(tool, operation="cast", work_id=work_id, limit=50)
        expected_cast = raw.execute("SELECT count(*) FROM credit WHERE work_id = ? AND role = 'cast'", (work_id,)).fetchone()[0]
        assert cast_result.get("total", 0) == expected_cast, work_id
        _, award_result = call(tool, operation="awards", work_id=work_id, limit=50)
        expected_awards = raw.execute("SELECT count(*) FROM award_result WHERE work_id = ?", (work_id,)).fetchone()[0]
        assert award_result.get("total", 0) == expected_awards, work_id


def test_an_id_from_an_earlier_step_skips_the_name_lookup_and_cannot_be_ambiguous(tool):
    """Reusing an id does NOT save queries (the card and the directors cost the same as the name lookup); it removes the ambiguity and the fuzzy fallback."""
    by_name, named = call(tool, operation="cast", title="Il padrino")
    by_id, with_id = call(tool, operation="cast", work_id=named["subject"]["work_id"])
    assert with_id["total"] == named["total"] and with_id["queries"] <= named["queries"]
    assert not any("v_name" in c["sql"] for c in by_id["trace"][0]["data"]["queries"])
    assert any("v_name" in c["sql"] for c in by_name["trace"][0]["data"]["queries"])
    _, crash_by_name = call(tool, operation="cast", title="Crash")
    _, crash_by_id = call(tool, operation="cast", work_id=CRASH_2004)
    assert crash_by_name["status"] == "ambiguous" and crash_by_id["status"] == "ok" and crash_by_id["subject"]["year"] == 2004


def test_every_executed_statement_is_recorded_with_the_views_it_read(tool):
    result, m = call(tool, operation="filmography", person="Christopher Nolan", role="director")
    data = result["trace"][0]["data"]
    assert result["trace"][0]["kind"] == "cinema_sql_calls" and data["operation"] == "filmography" and len(data["queries"]) == m["queries"]
    assert all(q["sql"].startswith("SELECT") and "LIMIT" in q["sql"] for q in data["queries"])
    assert set(data["views"]) <= {"v_name", "v_person", "v_credit"} and "CC BY-SA" in data["license"]
