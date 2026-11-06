"""Phase 7: field-level reliability (verified / partial / uncertain / absent) and the further step offered only for a gap the request asks about."""
from __future__ import annotations

import pytest
from cinema_build_support import make_inputs, make_phase4

from cinema_db.harness.build.build import Inputs, run_build
from tool.cinema_db.config import CinemaDbConfig
from tool.cinema_db.reliability import ABSENT, PARTIAL, UNCERTAIN, VERIFIED, assess, follow_up_summary, offer
from tool.cinema_db.tool import FINAL_INSTRUCTIONS, CinemaSqlTool
from turn import RESULT_FOLLOW_UP


def check(operation, *, status="ok", reason=None, data=None, subject=None, truncated=False):
    return assess(operation, status=status, reason=reason, data=data or {}, total=None, shown=0, truncated=truncated, subject=subject)


def test_identity_states_follow_the_status_and_never_say_the_thing_does_not_exist():
    assert check("find_work", status="ambiguous")[0]["identity"]["state"] == UNCERTAIN
    assert check("find_work", status="unverified")[0]["identity"]["state"] == UNCERTAIN
    assert check("find_work", status="not_found")[0]["identity"]["state"] == ABSENT
    assert "not exist" not in str(check("find_work", status="not_found")[0]).replace("does not say", "")
    assert check("cast", status="empty", reason="no_cast_in_catalogue")[0]["result"]["state"] == ABSENT


def test_the_cast_has_members_but_no_billing_order_and_a_gap_for_the_lead_actors_only():
    fields, gaps = check("cast", data={"cast": [{"name": "A", "character": "x"}, {"name": "B", "character": None}]}, subject={"kind": "work"})
    assert fields["billing_order"]["state"] == ABSENT and fields["members"]["state"] == PARTIAL and fields["characters"]["state"] == PARTIAL
    assert fields["identity"]["state"] == VERIFIED
    assert [g["tool"] for g in offer(gaps, "Chi sono gli attori protagonisti di Inception?")] == ["tmdb_search"]
    assert offer(gaps, "Chi ha recitato in Inception?") == []  # the whole cast is what the local list gives: nothing to complete
    assert [g["tool"] for g in offer(gaps, "Who are the main cast of Heat?")] == ["tmdb_search"]


def test_person_awards_are_partial_and_work_awards_are_offered_a_step_only_when_the_awards_in_general_are_asked():
    fields, gaps = check("awards", data={"results": [1]}, subject={"kind": "person"})
    assert fields["results"]["state"] == PARTIAL and len(offer(gaps, "Quali candidature all'Oscar ha avuto Nolan?")) == 1
    work_fields, work_gaps = check("awards", data={"results": [1]}, subject={"kind": "work"})
    assert work_fields["results"]["state"] == PARTIAL
    assert len(offer(work_gaps, "Quali premi ha vinto Inception?")) == 1 and offer(work_gaps, "Quanti Oscar ha vinto Parasite?") == []  # a named award is answered locally


def test_episode_counts_are_uncertain_unless_every_row_is_numbered_and_the_step_is_offered_for_episode_questions_only():
    seasons = [{"season_number": 1, "episodes": 25, "numbered_episodes": 23}]
    fields, gaps = check("series", data={"seasons": seasons})
    assert fields["episode_counts"]["state"] == UNCERTAIN and fields["numbering"]["state"] == PARTIAL
    assert offer(gaps, "Quante stagioni ha Friends?") == []  # the number of seasons is what the local list gives
    assert len(offer(gaps, "Quanti episodi ha la prima stagione di Friends?")) == 1
    exact = check("series", data={"seasons": [{"season_number": 1, "episodes": 7, "numbered_episodes": 7}]})[0]
    assert exact["episode_counts"]["state"] == PARTIAL and exact["numbering"]["state"] == VERIFIED


def test_relations_franchise_and_crew_say_what_the_data_does_not_settle():
    assert check("relations", data={"relations": [{"nature": "based_on_screen_work"}]}, subject={"kind": "work"})[0]["relation_type"]["state"] == UNCERTAIN
    fields, gaps = check("relations", data={"relations": [{"nature": "adaptation_of_non_screen_work"}]}, subject={"kind": "work"})
    assert fields["relation_type"]["state"] == VERIFIED  # a film based on a novel IS an adaptation: the type is not in doubt
    assert fields["source_work"]["state"] == PARTIAL  # but the novel is recorded with a title only (B04, B16 of the phase 7 evaluation)
    assert offer(gaps, "Da quale libro è tratto Blade Runner?") and offer(gaps, "Who wrote the novel Oppenheimer is based on?")
    assert not offer(gaps, "È un remake di Solaris?") and not offer(gaps, "Chi ha diretto Oppenheimer?") and offer(gaps, "Da cosa è tratto Oppenheimer?")  # even a plain «based on what» gets the author: the source title alone was judged incomplete (B16)
    _, remake_gaps = check("relations", data={"relations": [{"nature": "based_on_screen_work"}, {"nature": "order_in_series"}]}, subject={"kind": "work"})
    assert offer(remake_gaps, "È un remake di Solaris?") and not offer(remake_gaps, "Da cosa è tratto Solaris?")
    assert check("franchise", data={}, subject={"kind": "work"})[0]["membership"]["state"] == UNCERTAIN
    assert check("crew", data={"crew": [{"role": "writer"}]}, subject={"kind": "work"})[0]["writer"]["state"] == UNCERTAIN
    assert "writer" not in check("crew", data={"crew": [{"role": "director"}]}, subject={"kind": "work"})[0]


def test_the_summary_for_the_planner_names_the_tool_and_says_when_not_to_use_it():
    _, gaps = check("cast", data={"cast": [{"name": "A", "character": "x"}]}, subject={"kind": "work"})
    text = follow_up_summary("cast", offer(gaps, "gli attori protagonisti"))
    assert "tmdb_search" in text and "only if the user's request needs that information" in text and "reuse the ids" in text


@pytest.fixture(scope="module")
def tool(tmp_path_factory) -> CinemaSqlTool:
    tmp = tmp_path_factory.mktemp("cinema_reliability")
    base = make_inputs(tmp, awards_demo=True)
    inputs = Inputs(base.film_snapshot, base.series_snapshot, base.film_catalog, base.series_dir, phase4=make_phase4(tmp / "phase4"))
    out = tmp / "out" / "cinema.sqlite3"
    run_build(out, inputs, log=lambda *_: None)
    return CinemaSqlTool(config=CinemaDbConfig(enabled=True, db_path=str(out), max_queries_per_turn=40, default_limit=25))


def test_the_tool_reports_reliability_and_offers_a_step_only_for_the_gap_the_request_asks_about(tool):
    lead = tool.run(query="Chi sono gli attori protagonisti di Film di prova?", params={"operation": "cast", "title": "Film di prova"})
    assert lead["metadata"]["cinema_db"]["reliability"]["billing_order"]["state"] == ABSENT
    assert lead[RESULT_FOLLOW_UP]["reasons"] == ["data_gap:billing_order"] and "tmdb_search" in lead[RESULT_FOLLOW_UP]["summary"]
    assert lead["trace"][0]["data"]["reliability"]["billing_order"] == ABSENT  # the trace carries the states only, never the reasons
    whole = tool.run(query="Chi ha recitato in Film di prova?", params={"operation": "cast", "title": "Film di prova"})
    assert RESULT_FOLLOW_UP not in whole  # nothing to complete: no further planning call


def test_a_person_award_result_offers_one_step_and_a_work_award_result_none(tool):
    person = tool.run(query="Quali premi ha vinto Bob Attore?", params={"operation": "awards", "person": "Bob Attore"})
    assert person["metadata"]["cinema_db"]["reliability"]["results"]["state"] == PARTIAL and RESOLVED_OFFER in person[RESULT_FOLLOW_UP]["reasons"]
    work = tool.run(query="Quanti Oscar ha vinto Film di prova?", params={"operation": "awards", "title": "Film di prova"})
    assert RESULT_FOLLOW_UP not in work
    general = tool.run(query="Quali premi ha vinto Film di prova?", params={"operation": "awards", "title": "Film di prova"})
    assert general[RESULT_FOLLOW_UP]["reasons"] == ["data_gap:results"]


RESOLVED_OFFER = "data_gap:results"


def test_the_final_rules_explain_the_four_states():
    for word in ("verified", "partial", "uncertain", "absent", "billing_order"):
        assert word in FINAL_INSTRUCTIONS


@pytest.mark.parametrize("relation,direction,kind,related,expected", [
    ("based_on", "forward", "film", "other", "adaptation_of_non_screen_work"),   # a film based on a novel
    ("based_on", "forward", "film", "film", "based_on_screen_work"),             # remake, reboot or derived: not told apart
    ("based_on", "forward", "series", "series", "based_on_screen_work"),
    ("based_on", "inverse", "other", "film", "adapted_into_screen_work"),                    # the novel's side
    ("based_on", "inverse", "film", "film", "source_of_screen_work"),
    ("follows", "forward", "film", "film", "order_in_series"),
])
def test_what_a_stored_relation_proves_comes_from_the_kinds_of_the_two_works(relation, direction, kind, related, expected):
    from tool.cinema_db.operations import relation_nature

    assert relation_nature(relation, direction, kind, related) == expected
