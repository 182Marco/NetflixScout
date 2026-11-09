"""`cinema_sql` against the REAL reconciled v3 candidate file (read-only, offline, ~1 s). Skipped when the file is not there (it is not versioned).

Not a benchmark: it proves that the generated v3 policy matches the real file, and that the new operations return real, sensible data."""
from __future__ import annotations

from pathlib import Path

import pytest

from tool.cinema_db.config import CinemaDbConfig
from tool.cinema_db.tool import CinemaSqlTool

DB = Path(__file__).resolve().parents[1] / "cinema_db/data/cinema.v3.candidate2.sqlite3"
pytestmark = pytest.mark.skipif(not DB.is_file(), reason="the v3 candidate database is not built on this machine")


@pytest.fixture(scope="module")
def tool() -> CinemaSqlTool:
    return CinemaSqlTool(config=CinemaDbConfig(enabled=True, db_path=str(DB), max_queries_per_turn=40, default_limit=25))


def run(tool, **arguments):
    return tool.run(query="q", params=arguments)["metadata"]["cinema_db"]


def test_the_policy_matches_the_real_file_and_a_known_film_is_verified(tool):
    assert tool.schema == 3
    body = run(tool, operation="find_work", imdb_id="tt0137523")
    assert body["status"] == "ok" and body["subject"]["title"] == "Fight Club" and body["subject"]["identity_level"] == "verified"


def test_ratings_cast_order_and_ranking_come_from_the_database(tool):
    ratings = run(tool, operation="ratings", imdb_id="tt0137523")["ratings"]
    imdb = next(r for r in ratings if r["source"] == "imdb-datasets")
    assert imdb["scale_max"] == 10 and imdb["votes"] > 1_000_000 and 8 < imdb["rating"] < 9.5 and any(r["scale_max"] == 5 for r in ratings)
    cast = run(tool, operation="cast", imdb_id="tt0137523", limit=3)
    assert [p["billing_order"] for p in cast["cast"]] == [1, 2, 3] and cast["reliability"]["billing_order"]["state"] == "partial"
    ranking = run(tool, operation="ratings", year_from=1999, year_to=1999, type="film", min_votes=500_000, limit=3)["ranking"]
    assert ranking[0]["title"] == "Fight Club" and all(r["votes"] >= 500_000 for r in ranking)


def test_a_work_with_two_imdb_ids_shows_both_and_the_levels_are_queryable(tool):
    body = run(tool, operation="provenance", work_id=221)
    primaries = [i["value"] for i in body["identifiers"] if i["scheme"] == "imdb_title" and i["primary"]]
    others = [i["value"] for i in body["identifiers"] if i["scheme"] == "imdb_title" and not i["primary"]]
    assert len(primaries) == 1 and len(others) == 1 and body["identification"]["identity_level"] == "verified"
    levels = {r["identity_level"] for r in run(tool, operation="sql", sql="SELECT DISTINCT identity_level FROM v_work_status LIMIT 5")["rows"]}
    assert levels == {"verified", "rule_based", "uncertain"}


def test_a_merged_person_is_one_person_and_an_unknown_title_is_not_found(tool):
    merged = run(tool, operation="sql", sql="SELECT merged_entity_id, canonical_entity_id FROM v_entity_canonical LIMIT 20")["rows"]
    assert len(merged) == 12
    gone = merged[0]["merged_entity_id"]
    assert run(tool, operation="sql", sql=f"SELECT count(*) AS n FROM v_person WHERE person_id = {gone}")["rows"][0]["n"] == 0
    assert run(tool, operation="find_work", title="Zzyzx Qwerty Film Inexistent")["status"] == "not_found"


def test_operations_for_a_well_known_person_stay_far_below_the_two_second_limit(tool):
    """Regression of the first candidate: v_credit computed person_id with COALESCE, the filter could not use the credit_person index and `filmography` timed out."""
    import time

    for arguments in ({"operation": "filmography", "person": "Christopher Nolan"}, {"operation": "filmography", "person": "Brad Pitt", "type": "film"},
                      {"operation": "collaborations", "person": "Christopher Nolan"}, {"operation": "collaborations", "person": "Christopher Nolan", "person_b": "Christian Bale"},
                      {"operation": "find_person", "person": "Christopher Nolan"}):
        started = time.perf_counter()
        body = run(tool, **arguments)
        assert body["status"] == "ok", arguments
        assert time.perf_counter() - started < 0.6, arguments  # measured 25-50 ms; the failure was 2 s or more
