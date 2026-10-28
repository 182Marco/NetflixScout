from __future__ import annotations

import pytest

from omdb_support import record
from tool.omdb.ratings import any_available, extract_ratings


def _by_source(rows):
    return {row["source"]: row for row in rows}


def test_all_three_scores_are_parsed_in_a_fixed_order() -> None:
    rows = extract_ratings(record())

    assert [row["source"] for row in rows] == ["imdb", "metascore", "rotten_tomatoes"]
    by = _by_source(rows)
    assert (by["imdb"]["value"], by["imdb"]["kind"], by["imdb"]["votes"]) == (7.9, "audience", 720000)
    assert (by["metascore"]["value"], by["metascore"]["kind"]) == (81.0, "critics")
    assert (by["rotten_tomatoes"]["value"], by["rotten_tomatoes"]["kind"]) == (94.0, "critics")
    assert all(row["status"] == "available" for row in rows) and any_available(rows)


def test_na_and_missing_scores_are_not_available_never_zero() -> None:
    rows = _by_source(extract_ratings(record(imdb=None, metascore=None, rotten=None)))

    assert all(row["status"] == "not_available" and row["value"] is None for row in rows.values())
    assert not any_available(list(rows.values()))


def test_one_missing_score_does_not_touch_the_others_or_get_estimated() -> None:
    rows = _by_source(extract_ratings(record(rotten=None)))

    assert rows["rotten_tomatoes"]["status"] == "not_available" and rows["rotten_tomatoes"]["value"] is None
    assert rows["imdb"]["value"] == 7.9 and rows["metascore"]["value"] == 81.0


def test_a_bare_dict_with_no_fields_is_all_not_available() -> None:
    for empty in ({}, None, "x", []):
        rows = extract_ratings(empty)
        assert [row["status"] for row in rows] == ["not_available"] * 3


def test_the_ratings_array_fills_in_when_the_top_level_field_is_na() -> None:
    raw = record()
    raw["imdbRating"], raw["Metascore"] = "N/A", "N/A"
    rows = _by_source(extract_ratings(raw))

    assert rows["imdb"]["value"] == 7.9 and rows["metascore"]["value"] == 81.0


@pytest.mark.parametrize(
    ("field", "value", "source"),
    [
        ("imdbRating", "eleven", "imdb"),
        ("imdbRating", "11.5", "imdb"),
        ("imdbRating", "-1", "imdb"),
        ("Metascore", "101", "metascore"),
        ("Metascore", "good", "metascore"),
    ],
)
def test_unreadable_or_out_of_range_values_are_unparsed_and_not_shown(field, value, source) -> None:
    raw = record()
    raw[field] = value
    raw["Ratings"] = []
    row = _by_source(extract_ratings(raw))[source]

    assert row["status"] == "unparsed" and row["value"] is None


def test_rotten_tomatoes_needs_the_percent_form() -> None:
    raw = record(rotten="94%")
    raw["Ratings"] = [{"Source": "Rotten Tomatoes", "Value": "9.4/10"}]

    assert _by_source(extract_ratings(raw))["rotten_tomatoes"]["status"] == "unparsed"


def test_votes_are_read_only_for_an_available_imdb_score() -> None:
    assert _by_source(extract_ratings(record(votes="N/A")))["imdb"]["votes"] is None
    assert "votes" not in _by_source(extract_ratings(record(imdb=None)))["imdb"]


def test_nothing_is_averaged_or_added() -> None:
    rows = extract_ratings(record())

    assert set().union(*(row.keys() for row in rows)) <= {"source", "kind", "scale", "status", "value", "votes", "display"}


def test_every_available_score_carries_its_own_scale_in_display_and_rotten_tomatoes_is_a_percentage() -> None:
    rows = _by_source(extract_ratings(record(imdb="9.3", metascore="82", rotten="93%")))

    assert (rows["imdb"]["display"], rows["metascore"]["display"], rows["rotten_tomatoes"]["display"]) == ("9.3/10", "82/100", "93%")
    assert "/100" not in rows["rotten_tomatoes"]["display"]
    assert _by_source(extract_ratings(record(imdb="8", rotten="7%")))["imdb"]["display"] == "8/10"


def test_a_score_that_is_not_available_or_unreadable_has_no_display() -> None:
    rows = _by_source(extract_ratings(record(imdb=None, metascore="good", rotten=None)))

    assert all("display" not in row for row in rows.values())
