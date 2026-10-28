from __future__ import annotations

import pytest

from omdb_support import search_hit
from tool.omdb.identify import AMBIGUOUS, IDENTIFIED, NOT_FOUND, UNVERIFIED, identify, normalize_title, year_matches


def test_one_exact_title_is_identified() -> None:
    found = identify([search_hit("tt1000001", "Sample Movie", "2016")], title="sample movie", year=None, type=None)

    assert (found.status, found.imdb_id, found.title) == (IDENTIFIED, "tt1000001", "Sample Movie")


def test_the_same_title_in_two_years_is_ambiguous_until_the_year_is_given() -> None:
    hits = [search_hit("tt1000001", "Sample Movie", "1984"), search_hit("tt1000002", "Sample Movie", "2021")]

    ambiguous = identify(hits, title="Sample Movie", year=None, type=None)
    chosen = identify(hits, title="Sample Movie", year=2021, type=None)

    assert ambiguous.status == AMBIGUOUS and [c["year"] for c in ambiguous.candidates] == ["1984", "2021"]
    assert ambiguous.imdb_id is None
    assert (chosen.status, chosen.imdb_id) == (IDENTIFIED, "tt1000002")


def test_a_movie_and_a_series_with_the_same_title_are_ambiguous_unless_the_type_is_given() -> None:
    hits = [search_hit("tt1000001", "Sample", "2010"), search_hit("tt1000002", "Sample", "2008–2013", "series")]

    assert identify(hits, title="Sample", year=None, type=None).status == AMBIGUOUS
    assert identify(hits, title="Sample", year=None, type="series").imdb_id == "tt1000002"


def test_similar_titles_alone_are_unverified_never_chosen() -> None:
    hits = [search_hit("tt1000001", "The Sinners", "2025"), search_hit("tt1000002", "Sinner", "2010")]
    found = identify(hits, title="The Sinner", year=None, type=None)

    assert found.status == UNVERIFIED and found.imdb_id is None and len(found.candidates) == 2


def test_an_exact_title_with_the_wrong_year_is_unverified() -> None:
    found = identify([search_hit("tt1000001", "Sample Movie", "2016")], title="Sample Movie", year=2019, type=None)

    assert found.status == UNVERIFIED and found.imdb_id is None


@pytest.mark.parametrize("results", [None, [], "x", [{}], [{"Title": "x"}], [{"Title": "x", "imdbID": "bad"}]])
def test_no_usable_result_is_not_found(results) -> None:
    assert identify(results, title="x", year=None, type=None).status == NOT_FOUND


def test_episodes_and_repeated_ids_are_not_candidates() -> None:
    hits = [search_hit("tt1000001", "Sample", "2010", "episode"), search_hit("tt1000002", "Sample", "2011"), search_hit("tt1000002", "Sample", "2011")]

    assert identify(hits, title="Sample", year=None, type=None).imdb_id == "tt1000002"


def test_candidates_are_limited() -> None:
    hits = [search_hit(f"tt10000{n:02d}", "Sample", str(1990 + n)) for n in range(1, 9)]

    assert len(identify(hits, title="Sample", year=None, type=None).candidates) == 5


def test_titles_compare_without_case_accents_or_punctuation_but_an_article_is_part_of_the_title() -> None:
    assert normalize_title("Mars & Avril!") == normalize_title("mars and avril")
    assert normalize_title("Amélie") == normalize_title("Amelie")
    assert normalize_title("The Sinner") != normalize_title("Sinner")


@pytest.mark.parametrize(
    ("value", "year", "expected"),
    [
        ("2010", 2010, True),
        ("2010", 2011, False),
        ("2008–2013", 2010, True),
        ("2008–2013", 2014, False),
        ("2019–", 2024, True),
        ("2019–", 2018, False),
        ("N/A", 2010, False),
        (None, 2010, False),
    ],
)
def test_year_spans(value, year, expected) -> None:
    assert year_matches(value, year) is expected
