"""Pure parts of the Wikidata tool: the constant requests, the normalization of the answers and the decision
on which work a search identifies (offline, no I/O)."""
from __future__ import annotations

import re
from datetime import date

import pytest
from wikidata_support import (
    FRANCHISE,
    SUBJECT,
    TODAY,
    detail_row,
    related_row,
    search_payload,
    sparql,
)

from tool.wikidata import queries
from tool.wikidata.identify import AMBIGUOUS, IDENTIFIED, NOT_FOUND, UNVERIFIED, identify, normalize_title, parse_search
from tool.wikidata.models import WikidataToolInput
from tool.wikidata.normalize import (
    parse_candidates,
    parse_date,
    parse_members,
    parse_relations,
)
from tool.wikidata.settings import MAX_PER_GROUP, SPARQL_ROW_LIMIT


def _items(*rows):
    return parse_candidates(sparql(list(rows)))


# --- requests ------------------------------------------------------------------------------------------------


def test_the_title_is_only_a_search_parameter_and_never_part_of_a_sparql_text() -> None:
    endpoint, params = queries.search_request('Crash"} DROP', "it")
    assert endpoint == "api" and dict(params)["search"] == 'Crash"} DROP' and dict(params)["language"] == "it"

    texts = [
        dict(queries.details_request(["Q1", "Q2"])[1])["query"],
        dict(queries.relations_request("Q3")[1])["query"],
        dict(queries.members_request(["Q4"])[1])["query"],
        dict(queries.imdb_request("tt0000001")[1])["query"],
        dict(queries.tmdb_request(5, "tv")[1])["query"],
    ]
    assert all("DROP" not in text and "\n" not in text and "  " not in text for text in texts)


@pytest.mark.parametrize("bad", ["Q1} DROP", "q1", "Q", "Q0", "1", "Q1 Q2", "wd:Q1", "Q" + "9" * 20])
def test_only_item_ids_can_be_written_into_a_query(bad) -> None:
    for build in (lambda: queries.relations_request(bad), lambda: queries.details_request([bad]), lambda: queries.members_request([bad])):
        with pytest.raises(ValueError):
            build()


def test_external_ids_must_match_their_pattern_and_tmdb_ids_are_integers() -> None:
    for bad in ("tt12", "nm0000001", 'tt0000001" . ?w ?p ?o #'):
        with pytest.raises(ValueError):
            queries.imdb_request(bad)
    assert 'wdt:P4983 "7"' in dict(queries.tmdb_request(7, "tv")[1])["query"]
    assert 'wdt:P4947 "7"' in dict(queries.tmdb_request("7", "movie")[1])["query"]


def test_every_query_is_bound_to_given_items_and_limited() -> None:
    for request in (queries.details_request(["Q1"]), queries.relations_request("Q1"), queries.members_request(["Q1"])):
        text = dict(request[1])["query"]
        assert f"LIMIT {SPARQL_ROW_LIMIT}" in text and ("wd:Q1" in text)
    assert dict(queries.relations_request("Q1")[1])["format"] == "json"


def test_relations_cover_both_directions_of_each_declared_property() -> None:
    text = dict(queries.relations_request("Q1")[1])["query"]

    for fragment in ("wd:Q1 wdt:P144 ?o", "?o wdt:P144 wd:Q1", "wd:Q1 wdt:P4969 ?o", "?o wdt:P4969 wd:Q1", "wd:Q1 wdt:P155 ?o", "?o wdt:P156 wd:Q1"):
        assert fragment in text


def test_the_input_needs_an_identity_and_a_type_for_a_tmdb_id() -> None:
    base = {"query": "q", "operation": "resolve"}
    assert WikidataToolInput.model_validate({**base, "title": "Crash"}).language == "en"
    for bad in ({}, {"tmdb_id": 5}, {"imdb_id": "nope"}, {"title": "x", "extra": 1}, {"title": "x", "operation": "sparql"}):
        with pytest.raises(Exception):
            WikidataToolInput.model_validate({**base, **bad})
    assert WikidataToolInput.model_validate({**base, "tmdb_id": 5, "type": "tv"}).tmdb_id == 5


# --- normalization -------------------------------------------------------------------------------------------


def test_dates_with_unknown_month_or_day_read_as_the_first() -> None:
    assert parse_date("1982-06-25T00:00:00Z") == date(1982, 6, 25)
    assert parse_date("1999-00-00T00:00:00Z") == date(1999, 1, 1)
    assert parse_date("not a date") is None and parse_date(None) is None and parse_date("-0500-01-01T00:00:00Z") is None


def test_rows_of_one_item_are_merged_so_it_is_never_listed_twice() -> None:
    items = _items(
        detail_row("Q9000001", "Film", pub="1996-01-01T00:00:00Z", director="A B", imdb="tt1234567"),
        detail_row("Q9000001", "Film", pub="1997-01-01T00:00:00Z", director="C D", imdb="tt1234567"),
    )

    assert list(items) == ["Q9000001"]
    assert sorted(d.year for d in items["Q9000001"].dates) == [1996, 1997] and items["Q9000001"].directors == {"A B", "C D"}


def test_the_relations_are_grouped_filtered_and_ordered() -> None:
    rows = [
        related_row("source", "Q9000010", "Novel", kind="literary", pub="1968-01-01T00:00:00Z"),
        related_row("derived", "Q9000011", "Game", kind="game", pub="1997-01-01T00:00:00Z"),
        related_row("derived", "Q9000012", "Second Film", pub="2017-01-01T00:00:00Z"),
        related_row("derived", "Q9000013", "First Film", pub="1990-01-01T00:00:00Z"),
        related_row("derived", "Q9000014", "Album", kind="none"),
        related_row("derived", "Q9000015", "Q9000015", pub="1990-01-01T00:00:00Z"),
        related_row("derived", "Q9000016", "Announced", project=True),
        related_row("derived", "Q9000017", "Future Film", pub="2031-01-01T00:00:00Z"),
        related_row("next", "Q9000012", "Second Film", pub="2017-01-01T00:00:00Z"),
        related_row("container", FRANCHISE, "Franchise", kind="none"),
        related_row("source", SUBJECT, "Itself"),
    ]

    related = parse_relations(sparql(rows), subject=SUBJECT, today=TODAY)

    assert [r["title"] for r in related["sources"]] == ["Novel"]
    assert [r["title"] for r in related["derived"]] == ["First Film", "Second Film", "Game"]  # films by year, then games
    assert [r["title"] for r in related["next"]] == ["Second Film"] and related["previous"] == []
    assert related["containers"] == [{"id": FRANCHISE, "title": "Franchise"}]
    assert related["excluded_unreleased"] == 2  # the announced project and the film dated after today
    assert all(r["id"] != SUBJECT for group in ("sources", "derived", "next") for r in related[group])


def test_a_long_group_is_cut_and_the_rest_is_counted() -> None:
    rows = [related_row("derived", f"Q90001{i:02d}", f"Film {i:02d}", pub=f"{1950 + i}-01-01T00:00:00Z") for i in range(MAX_PER_GROUP + 3)]

    related = parse_relations(sparql(rows), subject=SUBJECT, today=TODAY)

    assert len(related["derived"]) == MAX_PER_GROUP and related["omitted"] == {"derived": 3}


def test_members_are_listed_per_franchise_oldest_first_without_unreleased_works() -> None:
    rows = [
        related_row(None, "Q9000021", "Later", pub="2010-01-01T00:00:00Z", container=FRANCHISE),
        related_row(None, "Q9000020", "Earlier", pub="1980-01-01T00:00:00Z", container=FRANCHISE),
        related_row(None, "Q9000022", "Announced", project=True, container=FRANCHISE),
        related_row(None, "Q9000023", "Track", kind="none", container=FRANCHISE),
    ]

    [franchise] = parse_members(sparql(rows), containers=[{"id": FRANCHISE, "title": "F"}], today=TODAY)

    assert [m["title"] for m in franchise["members"]] == ["Earlier", "Later"] and franchise["excluded_unreleased"] == 1


# --- identification ------------------------------------------------------------------------------------------


def test_titles_are_compared_without_case_accents_or_punctuation_but_with_the_article() -> None:
    assert normalize_title("  Léon: The Professional! ") == normalize_title("leon the professional")
    assert normalize_title("Mars & Avril") == normalize_title("Mars and Avril")
    assert normalize_title("The Sinner") != normalize_title("Sinner")


def _crash():
    search = parse_search(search_payload(("Q9000001", "Crash"), ("Q9000002", "Crash"), ("Q9000003", "Crash"), ("Q9000004", "Crash Bandicoot")))
    items = _items(
        detail_row("Q9000001", "Crash", pub="1996-05-17T00:00:00Z", director="David Cronenberg", imdb="tt0115964", tmdb_movie="884"),
        detail_row("Q9000002", "Crash", pub="2004-09-10T00:00:00Z", director="Paul Haggis", imdb="tt0375679", tmdb_movie="1640"),
        detail_row("Q9000003", "Crash", film=False, series=True, start="2008-10-17T00:00:00Z", imdb="tt1178636"),
        detail_row("Q9000004", "Crash Bandicoot", film=False),
    )
    return search, items


def test_a_title_shared_by_several_works_is_ambiguous_and_the_alternatives_tell_them_apart() -> None:
    search, items = _crash()

    found = identify(items, today=TODAY, media=None, search=search, title="Crash")

    assert found.status == AMBIGUOUS and found.work is None
    assert [(c["year"], c["kind"], c["imdb_id"], c["tmdb_id"]) for c in found.candidates] == [
        (1996, "film", "tt0115964", 884), (2004, "film", "tt0375679", 1640), (2008, "series", "tt1178636", None),
    ]


def test_year_director_and_type_each_narrow_the_title_down_to_one_work() -> None:
    search, items = _crash()

    by_year = identify(items, today=TODAY, media=None, search=search, title="Crash", year=2004)
    by_director = identify(items, today=TODAY, media=None, search=search, title="crash", director="cronenberg")
    by_type = identify(items, today=TODAY, media="tv", search=search, title="Crash")

    assert (by_year.status, by_year.work["imdb_id"]) == (IDENTIFIED, "tt0375679")
    assert (by_director.status, by_director.work["tmdb_id"]) == (IDENTIFIED, 884)
    assert (by_type.status, by_type.work["kind"]) == (IDENTIFIED, "series")


def test_a_year_or_director_the_data_does_not_have_is_not_a_match() -> None:
    search, items = _crash()

    wrong_year = identify(items, today=TODAY, media="movie", search=search, title="Crash", year=1999)
    no_director = identify(items, today=TODAY, media="tv", search=search, title="Crash", director="Anyone")

    assert wrong_year.status == UNVERIFIED and no_director.status == UNVERIFIED
    assert wrong_year.work is None and wrong_year.candidates  # alternatives are shown, nothing is attributed


def test_works_that_only_resemble_the_title_are_unverified() -> None:
    search = parse_search(search_payload(("Q9000004", "Crash Bandicoot Movie")))
    items = _items(detail_row("Q9000004", "Crash Bandicoot Movie", pub="2001-01-01T00:00:00Z"))

    assert identify(items, today=TODAY, media=None, search=search, title="Crash").status == UNVERIFIED


def test_an_alias_the_search_matched_counts_as_the_title() -> None:
    search = [{"id": "Q9000001", "texts": ["Infernal Affairs", "Mou gaan dou"]}]
    items = _items(detail_row("Q9000001", "Infernal Affairs", pub="2002-12-12T00:00:00Z"))

    assert identify(items, today=TODAY, media=None, search=search, title="Mou gaan dou").status == IDENTIFIED


def test_projects_and_future_works_are_never_candidates_and_are_counted() -> None:
    search = parse_search(search_payload(("Q9000001", "Saga"), ("Q9000002", "Saga")))
    items = _items(
        detail_row("Q9000001", "Saga", pub="2031-01-01T00:00:00Z"),
        detail_row("Q9000002", "Saga", project=True),
    )

    found = identify(items, today=TODAY, media=None, search=search, title="Saga")

    assert (found.status, found.excluded_unreleased) == (NOT_FOUND, 2) and found.candidates == []


def test_an_external_id_is_the_identity_and_a_non_screen_item_is_not_found() -> None:
    assert identify(_items(detail_row("Q9000001", "X", pub="1990-01-01T00:00:00Z")), today=TODAY, media=None).status == IDENTIFIED
    assert identify(_items(detail_row("Q9000001", "X", film=False)), today=TODAY, media=None).status == NOT_FOUND
    two = _items(detail_row("Q9000001", "X", pub="1990-01-01T00:00:00Z"), detail_row("Q9000002", "Y", pub="1991-01-01T00:00:00Z"))
    assert identify(two, today=TODAY, media=None).status == AMBIGUOUS


def test_the_public_form_of_a_work_carries_only_imdb_and_tmdb_ids() -> None:
    search, items = _crash()
    work = identify(items, today=TODAY, media=None, search=search, title="Crash", year=1996).work

    assert set(work) == {"id", "title", "year", "kind", "directors", "imdb_id", "tmdb_id", "description"}
    assert not re.search(r"letterboxd|rotten|netflix", repr(work), re.I)


# --- titles in SPARQL: exact label requests ------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    ['Crash"} DROP', 'a" . ?w ?p ?o #', "back\\slash", 'x"@en . ?s ?p ?o . FILTER("', "line\nbreak\r\x00"],
)
def test_a_title_in_a_label_request_stays_inside_one_string_literal(title) -> None:
    literal = queries.sparql_literal(title)

    # Read the literal the way SPARQL does: from the opening quote to the first quote not preceded by a backslash.
    body = literal[1:]
    closing = next(i for i, ch in enumerate(body) if ch == '"' and (len(re.match(r"\\*", body[:i][::-1]).group()) % 2 == 0))
    assert closing == len(body) - 1  # the only unescaped quote is the last character
    assert "\n" not in literal and "\r" not in literal and "\x00" not in literal
    text = dict(queries.label_request(title, "en")[1])["query"]
    assert text.count("?w rdfs:label ") == 1 and "\n" not in text


def test_the_label_request_keeps_only_films_and_series_and_checks_the_language_code() -> None:
    text = dict(queries.label_request("Crash", "it")[1])["query"]

    assert '?w rdfs:label "Crash"@it .' in text and "FILTER(?film || ?series)" in text
    assert text.index("FILTER(?film || ?series)") < text.index("OPTIONAL")  # before the rows multiply
    for bad in ('en" . ?s', "EN", "e", "english"):
        with pytest.raises(ValueError):
            queries.label_request("Crash", bad)


def test_a_director_shown_by_its_own_id_is_not_a_director() -> None:
    items = _items(detail_row("Q9000001", "Film", pub="1984-01-01T00:00:00Z", director="Q5047009"), detail_row("Q9000001", "Film", director="Ann Real"))

    assert items["Q9000001"].directors == {"Ann Real"}


def test_a_single_fit_in_a_list_cut_at_its_limit_is_not_certain() -> None:
    items = _items(detail_row("Q9000001", "Crash", pub="2004-09-10T00:00:00Z", imdb="tt0375679"))
    search = [{"id": "Q9000001", "texts": ["Crash"]}]

    cut = identify(items, today=TODAY, media=None, search=search, title="Crash", complete=False)
    whole = identify(items, today=TODAY, media=None, search=search, title="Crash", complete=True)

    assert (cut.status, cut.work, cut.incomplete, [c["imdb_id"] for c in cut.candidates]) == (AMBIGUOUS, None, True, ["tt0375679"])
    assert whole.status == IDENTIFIED and not whole.incomplete


def test_alternatives_beyond_the_limit_are_counted_not_dropped_silently() -> None:
    from tool.wikidata.settings import MAX_CANDIDATES

    many = [detail_row(f"Q90001{i:02d}", "Crash", pub=f"{1950 + i}-01-01T00:00:00Z") for i in range(MAX_CANDIDATES + 3)]
    items = _items(*many)
    search = [{"id": qid, "texts": ["Crash"]} for qid in items]

    found = identify(items, today=TODAY, media=None, search=search, title="Crash")

    assert found.status == AMBIGUOUS and len(found.candidates) == MAX_CANDIDATES and found.omitted == 3
    assert [c["year"] for c in found.candidates] == sorted(c["year"] for c in found.candidates)  # the oldest are listed
    few = identify(_items(*many[:2]), today=TODAY, media=None, search=search, title="Crash")
    assert few.omitted == 0
