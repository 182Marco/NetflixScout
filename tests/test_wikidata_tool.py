"""The Wikidata tool end to end with a fake transport: contract, identification, relations, filters, budget, failures."""
from __future__ import annotations

import json
import re

from wikidata_support import (
    FRANCHISE,
    SUBJECT,
    TODAY,
    detail_row,
    make_tool,
    related_row,
    routes_for,
    search_payload,
    sparql,
)

from orchestrator import Tool
from tool.wikidata.config import WikidataConfig, load_wikidata_config
from tool.wikidata.settings import SPARQL_ROW_LIMIT
from tool.wikidata.tool import WIKIDATA_TOOL_NAME, planner_schema
from turn import STEP_WIKIDATA_CALLS, TOOL_PARAM_TURN_ID, TOOL_PARAM_TURN_LANGUAGE

import pytest


def _resolve(tool, **params):
    return tool.run(query="q", params={"operation": "resolve", **params})


def _relations(tool, **params):
    return tool.run(query="q", params={"operation": "relations", **params})


# --- contract ------------------------------------------------------------------------------------------------


def test_the_tool_follows_the_tool_protocol_and_its_schema_is_small_and_has_no_class_docstring() -> None:
    tool, _ = make_tool(routes_for())

    assert isinstance(tool, Tool) and tool.name == WIKIDATA_TOOL_NAME
    assert "description" not in planner_schema() and len(json.dumps(planner_schema(), separators=(",", ":"))) < 3500
    assert tool.input_schema["additionalProperties"] is False


def test_the_config_has_only_the_call_limit_and_no_default() -> None:
    assert load_wikidata_config({"max_calls_per_turn": 3}).max_calls_per_turn == 3
    for bad in ({}, {"max_calls_per_turn": 0}, {"max_calls_per_turn": 2, "timeout": 5}):
        with pytest.raises(Exception):
            WikidataConfig.model_validate(bad)


def test_invalid_arguments_are_refused_before_any_request_and_values_are_not_echoed() -> None:
    tool, transport = make_tool(routes_for())

    result = tool.run(query="q", params={"operation": "resolve", "title": "SECRET TITLE", "imdb_id": "bad", "extra": 1})

    assert transport.calls == [] and result["outcome"]["status"] == "error" and result["outcome"]["reason"] == "invalid_request"
    assert "SECRET" not in json.dumps(result) and result["trace"] == []


# --- resolve --------------------------------------------------------------------------------------------------


def test_a_title_costs_one_request_by_exact_label_and_the_work_is_identified_with_its_ids() -> None:
    tool, transport = make_tool(routes_for())

    result = _resolve(tool, title="Sample Film", year=1982)

    assert transport.kinds == ["label"] and result["outcome"]["status"] == "ok"
    work = result["metadata"]["wikidata"]["work"]
    assert (work["title"], work["year"], work["imdb_id"], work["tmdb_id"], work["directors"]) == ("Sample Film", 1982, "tt9000001", 9001, ["Ann Director"])
    [step] = result["trace"]
    assert step["kind"] == STEP_WIKIDATA_CALLS and len(step["data"]["calls"]) == 1
    assert step["data"]["work"]["url"] == f"https://www.wikidata.org/wiki/{SUBJECT}"


def test_homonyms_without_a_year_are_ambiguous_with_alternatives_and_no_follow_up() -> None:
    tool, _ = make_tool(routes_for())

    result = _resolve(tool, title="Sample Film")

    data = result["metadata"]["wikidata"]
    assert data["status"] == "ambiguous" and result["outcome"]["status"] == "empty" and "follow_up" not in result
    assert [(c["year"], c["imdb_id"]) for c in data["candidates"]] == [(1982, "tt9000001"), (2004, "tt9000002")]


def test_an_imdb_id_costs_one_request_and_never_searches() -> None:
    tool, transport = make_tool(routes_for())

    result = _resolve(tool, imdb_id="tt9000001")

    assert transport.kinds == ["details"] and 'wdt:P345 "tt9000001"' in transport.sparql_texts()[0]
    assert result["metadata"]["wikidata"]["work"]["title"] == "Sample Film"


def test_a_tmdb_id_is_read_with_the_property_of_its_type() -> None:
    tool, transport = make_tool(routes_for())

    _resolve(tool, tmdb_id=9001, type="movie")
    _resolve(tool, tmdb_id=9001, type="tv")

    assert 'wdt:P4947 "9001"' in transport.sparql_texts()[0] and 'wdt:P4983 "9001"' in transport.sparql_texts()[1]


def test_nothing_found_by_label_or_by_text_search_offers_one_step_elsewhere() -> None:
    tool, transport = make_tool({"search": search_payload()})

    result = _resolve(tool, title="Nessuna Cosa")

    assert transport.kinds == ["label", "search"] and result["metadata"]["wikidata"]["status"] == "not_found"
    assert result["follow_up"]["available"] and result["follow_up"]["reasons"] == ["not_found"]
    assert "tmdb_search" in result["follow_up"]["summary"]


def test_a_title_that_only_resembles_the_asked_one_is_unverified_and_never_gets_data() -> None:
    tool, _ = make_tool(routes_for())

    result = _resolve(tool, title="Sample Film", year=1999)

    assert result["metadata"]["wikidata"]["status"] == "unverified" and "work" not in result["metadata"]["wikidata"]
    assert result["follow_up"]["reasons"] == ["unverified"]


def test_a_work_announced_or_dated_after_today_is_not_identified_and_is_counted() -> None:
    routes = routes_for(
        label=sparql([detail_row(SUBJECT, "Sample Film", pub="2031-01-01T00:00:00Z")]),
        search=search_payload((SUBJECT, "Sample Film")),
        details=sparql([detail_row(SUBJECT, "Sample Film", pub="2031-01-01T00:00:00Z")]),
    )
    tool, _ = make_tool(routes)

    result = _resolve(tool, title="Sample Film")

    assert result["metadata"]["wikidata"]["status"] == "not_found" and result["metadata"]["wikidata"]["excluded_unreleased"] == 1


# --- relations ------------------------------------------------------------------------------------------------


def test_relations_identify_then_read_the_relations_and_the_franchise_in_three_requests() -> None:
    tool, transport = make_tool(routes_for())

    result = _relations(tool, title="Sample Film", year=1982)

    assert transport.kinds == ["label", "relations", "members"]
    data = result["metadata"]["wikidata"]
    assert data["status"] == "ok" and result["outcome"]["status"] == "ok" and "follow_up" not in result
    assert [r["title"] for r in data["based_on"]] == ["Sample Novel"] and data["based_on"][0]["kind"] == "literary"
    assert [r["title"] for r in data["based_on_this"]] == ["Sample Remake"] and [r["title"] for r in data["next_in_series"]] == ["Sample Remake"]
    assert data["franchises"] == [
        {"title": "Sample Franchise", "works": [
            {"title": "Sample Film", "year": 1982, "kind": "film", "description": None},
            {"title": "Sample Remake", "year": 2017, "kind": "film", "description": None},
        ], "omitted": 0}
    ]
    assert "incomplete" in data["note"]


def test_the_model_never_sees_item_ids_or_the_sparql_but_the_trace_has_the_links() -> None:
    tool, _ = make_tool(routes_for())

    result = _relations(tool, title="Sample Film", year=1982)

    seen_by_the_model = json.dumps(result["metadata"])
    assert not re.search(r"\bQ\d{4,}\b|wikidata\.org|SELECT", seen_by_the_model)
    [step] = result["trace"]
    assert step["data"]["relations"]["sources"][0]["url"] == "https://www.wikidata.org/wiki/Q9000010"
    assert step["data"]["franchises"][0]["url"] == f"https://www.wikidata.org/wiki/{FRANCHISE}"


def test_no_franchise_means_no_members_request() -> None:
    routes = routes_for(relations=sparql([related_row("source", "Q9000010", "Sample Novel", kind="literary", pub="1968-01-01T00:00:00Z")]))
    tool, transport = make_tool(routes)

    result = _relations(tool, imdb_id="tt9000001")

    assert transport.kinds == ["details", "relations"] and result["metadata"]["wikidata"]["franchises"] == []


def test_a_work_with_no_recorded_relation_is_empty_and_says_that_it_proves_nothing() -> None:
    tool, _ = make_tool(routes_for(relations=sparql([])))

    result = _relations(tool, imdb_id="tt9000001")

    assert result["outcome"] == {"status": "empty", "reason": "no_relations"}
    assert result["metadata"]["wikidata"]["status"] == "no_relations"
    assert result["follow_up"]["reasons"] == ["no_relations"] and "does not prove" in result["follow_up"]["summary"]


def test_the_budget_of_the_turn_can_stop_the_franchise_and_the_rest_is_still_returned() -> None:
    tool, transport = make_tool(routes_for(), max_calls=2)

    result = _relations(tool, title="Sample Film", year=1982)

    assert transport.kinds == ["label", "relations"]
    data = result["metadata"]["wikidata"]
    assert data["unavailable"] == {"franchise": "turn_limit"} and data["based_on"] and data["franchises"] == []
    assert result["follow_up"]["reasons"] == ["turn_limit"]


def test_a_franchise_query_that_fills_the_row_limit_is_reported_as_partial() -> None:
    rows = [related_row(None, f"Q91{i:05d}", f"Film {i}", pub="1990-01-01T00:00:00Z", container=FRANCHISE) for i in range(SPARQL_ROW_LIMIT)]
    tool, _ = make_tool(routes_for(members=sparql(rows)))

    result = _relations(tool, imdb_id="tt9000001")

    data = result["metadata"]["wikidata"]
    assert data["franchise_list_partial"] is True and data["franchises"][0]["omitted"] > 0 and "follow_up" not in result


def test_the_session_is_shared_by_the_runs_of_a_turn_and_a_new_turn_asks_again() -> None:
    tool, transport = make_tool(routes_for(), max_calls=8)

    _resolve(tool, title="Sample Film", year=1982, **{TOOL_PARAM_TURN_ID: "t1", TOOL_PARAM_TURN_LANGUAGE: "it"})
    again = _relations(tool, title="Sample Film", year=1982, **{TOOL_PARAM_TURN_ID: "t1"})
    assert transport.kinds == ["label", "relations", "members"]  # the label request came from the memo
    assert len(again["trace"][0]["data"]["calls"]) == 2  # only the requests of THIS run

    _resolve(tool, title="Sample Film", year=1982, **{TOOL_PARAM_TURN_ID: "t2"})
    assert transport.kinds[3:] == ["label"]


# --- failures -------------------------------------------------------------------------------------------------


def test_a_failure_of_the_relations_query_keeps_the_identity_and_offers_a_step_elsewhere() -> None:
    tool, _ = make_tool(routes_for(relations=(504, {}, b"timeout")))

    result = _relations(tool, imdb_id="tt9000001")

    assert result["outcome"] == {"status": "error", "reason": "http_error"}
    assert result["metadata"]["wikidata"]["work"]["title"] == "Sample Film"
    assert result["follow_up"]["reasons"] == ["http_error"]
    assert result["trace"][0]["data"]["status"] == "error" and len(result["trace"][0]["data"]["calls"]) == 2


@pytest.mark.parametrize(
    ("failure", "reason"),
    [(TimeoutError("x"), "timeout"), (OSError("x"), "network_error"), ((429, {}, b""), "rate_limited"), ((200, {}, b"<html>"), "http_error")],
)
def test_transport_problems_are_typed_errors_with_the_calls_that_were_sent(failure, reason) -> None:
    tool, transport = make_tool({"label": failure})

    result = _resolve(tool, title="Sample Film")

    assert result["outcome"] == {"status": "error", "reason": reason} and len(transport.calls) == 1
    assert len(result["trace"][0]["data"]["calls"]) == 1 and result["follow_up"]["available"]
    assert "Sample Film" not in json.dumps(result["metadata"])


def test_a_rate_limit_is_not_retried_in_the_same_or_the_next_run_while_the_pause_lasts() -> None:
    tool, transport = make_tool({"label": (429, {"Retry-After": "30"}, b"")})

    first = _resolve(tool, title="a")
    second = _resolve(tool, title="b")

    assert first["outcome"]["reason"] == second["outcome"]["reason"] == "rate_limited" and len(transport.calls) == 1


def test_the_live_smoke_harness_does_nothing_without_the_flag(capsys, monkeypatch) -> None:
    from tool.wikidata.harness import live_smoke

    monkeypatch.setattr("tool.wikidata.http.urllib_transport", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))

    assert live_smoke.main([]) == 0 and "Nothing done" in capsys.readouterr().out


# --- homonyms: every work of the title, not the best known entities (regression of the live case «Crash») ------


def _crash_rows():
    return sparql(
        [
            detail_row("Q9000011", "Crash", pub="1974-01-01T00:00:00Z", director="Rolf Clemens", imdb="tt0071367"),
            detail_row("Q9000012", "Crash", pub="1996-05-17T00:00:00Z", director="David Cronenberg", imdb="tt0115964", tmdb_movie="884"),
            detail_row("Q9000013", "Crash", pub="2004-09-10T00:00:00Z", director="Paul Haggis", imdb="tt0375679", tmdb_movie="1640"),
            detail_row("Q9000014", "Crash", film=False, series=True, start="2008-10-17T00:00:00Z", imdb="tt1178636"),
        ]
    )


def test_a_title_shared_by_a_lesser_known_film_is_ambiguous_because_every_work_of_the_label_is_read() -> None:
    # The text search ranks by notoriety and only the 2004 film was inside its first ten results.
    only_the_best_known = search_payload(("Q9000013", "Crash"))
    tool, transport = make_tool({"label": _crash_rows(), "search": only_the_best_known})

    result = _resolve(tool, title="Crash")

    data = result["metadata"]["wikidata"]
    assert transport.kinds == ["label"]  # one request, and no search to be fooled by
    assert data["status"] == "ambiguous" and "work" not in data and "incomplete" not in data
    assert [(c["year"], c["kind"], c["imdb_id"], c["tmdb_id"]) for c in data["candidates"]] == [
        (1974, "film", "tt0071367", None), (1996, "film", "tt0115964", 884), (2004, "film", "tt0375679", 1640), (2008, "series", "tt1178636", None),
    ]
    assert "follow_up" not in result


def test_the_year_or_the_director_then_pick_the_right_homonym_with_the_same_single_request() -> None:
    tool, transport = make_tool({"label": _crash_rows()})

    by_year = _resolve(tool, title="Crash", year=1996)
    by_director = _resolve(tool, title="Crash", director="Haggis")
    series = _resolve(tool, title="Crash", type="tv")

    assert [by_year["metadata"]["wikidata"]["work"]["imdb_id"], by_director["metadata"]["wikidata"]["work"]["imdb_id"], series["metadata"]["wikidata"]["work"]["imdb_id"]] == ["tt0115964", "tt0375679", "tt1178636"]
    assert transport.kinds == ["label"] * 3


def test_a_label_that_matches_nothing_falls_back_to_the_text_search_in_the_same_run() -> None:
    routes = routes_for(label=sparql([]), search=search_payload((SUBJECT, "Sample Film")))
    tool, transport = make_tool(routes)

    result = _resolve(tool, title="sample film", year=1982)  # another capitalization: no exact label

    assert transport.kinds == ["label", "search", "details"]
    assert result["metadata"]["wikidata"]["work"]["title"] == "Sample Film"


def test_a_label_without_a_fit_for_the_year_is_also_tried_by_text_search() -> None:
    tool, transport = make_tool(routes_for())

    result = _resolve(tool, title="Sample Film", year=1999)

    assert transport.kinds == ["label", "search", "details"] and result["metadata"]["wikidata"]["status"] == "unverified"


def test_a_single_fit_from_a_cut_text_search_is_offered_as_the_only_alternative_not_as_certain() -> None:
    from tool.wikidata.settings import SEARCH_LIMIT

    full_search = search_payload(*[(f"Q91{i:05d}", "Other") for i in range(SEARCH_LIMIT - 1)], (SUBJECT, "Sample Film"))
    routes = routes_for(label=sparql([]), search=full_search, details=sparql([detail_row(SUBJECT, "Sample Film", pub="1982-06-25T00:00:00Z", imdb="tt9000001")]))
    tool, _ = make_tool(routes)

    result = _resolve(tool, title="sample film")

    data = result["metadata"]["wikidata"]
    assert data["status"] == "ambiguous" and data["incomplete"] is True and "work" not in data
    assert [c["imdb_id"] for c in data["candidates"]] == ["tt9000001"]


def test_a_label_list_that_fills_the_row_limit_is_never_certain() -> None:
    rows = [detail_row(SUBJECT, "Sample Film", pub="1982-06-25T00:00:00Z", imdb="tt9000001")]
    rows += [detail_row(SUBJECT, "Sample Film", pub=f"{1983 + i % 20}-01-01T00:00:00Z") for i in range(SPARQL_ROW_LIMIT - 1)]
    tool, _ = make_tool(routes_for(label=sparql(rows)))

    result = _resolve(tool, title="Sample Film")

    assert result["metadata"]["wikidata"]["status"] == "ambiguous" and result["metadata"]["wikidata"]["incomplete"] is True


def test_a_failure_of_the_fallback_search_is_reported_not_hidden() -> None:
    tool, transport = make_tool({"label": sparql([]), "search": (500, {}, b"")})

    result = _resolve(tool, title="Nothing")

    assert result["outcome"] == {"status": "error", "reason": "http_error"} and transport.kinds == ["label", "search"]
    assert len(result["trace"][0]["data"]["calls"]) == 2


def test_the_result_says_how_many_alternatives_are_not_listed() -> None:
    from tool.wikidata.settings import MAX_CANDIDATES

    rows = sparql([detail_row(f"Q90001{i:02d}", "Crash", pub=f"{1950 + i}-01-01T00:00:00Z") for i in range(MAX_CANDIDATES + 4)])
    tool, _ = make_tool({"label": rows})

    result = _resolve(tool, title="Crash")

    data = result["metadata"]["wikidata"]
    assert len(data["candidates"]) == MAX_CANDIDATES and data["omitted_candidates"] == 4 and "incomplete" not in data
    step = result["trace"][0]["data"]
    assert step["candidates_omitted"] == 4 and step["incomplete"] is False


def test_a_complete_short_list_carries_no_omission_and_a_cut_list_is_flagged_incomplete() -> None:
    tool, _ = make_tool({"label": _crash_rows()})
    complete = _resolve(tool, title="Crash")["metadata"]["wikidata"]
    assert "omitted_candidates" not in complete and "incomplete" not in complete

    cut_rows = sparql([detail_row(SUBJECT, "Sample Film", pub=f"{1983 + i % 20}-01-01T00:00:00Z") for i in range(SPARQL_ROW_LIMIT)])
    cut, _ = make_tool({"label": cut_rows})
    flagged = _resolve(cut, title="Sample Film")
    assert flagged["metadata"]["wikidata"]["incomplete"] is True and flagged["trace"][0]["data"]["incomplete"] is True
