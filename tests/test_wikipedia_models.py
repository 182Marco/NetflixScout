from __future__ import annotations

import pytest
from pydantic import ValidationError

from wikipedia.models import Depth, Subject, WikipediaToolInput, describe_validation_errors, normalize_text


def _input(**fields) -> WikipediaToolInput:
    return WikipediaToolInput.model_validate({"query": "domanda", "topic": "Park Chan-wook", **fields})


def test_defaults_are_the_cheapest_reading() -> None:
    request = _input()

    assert request.kind is Subject.topic and request.depth is Depth.intro
    assert request.year is None and request.language is None and request.page is None and request.sections == []


def test_values_are_normalized_and_sections_deduplicated() -> None:
    request = _input(topic="  Park   Chan-wook ", page=" Park  Chan-wook ", sections=["Carriera", "carriera", " Vita  privata ", ""])

    assert request.topic == "Park Chan-wook" and request.page == "Park Chan-wook"
    assert request.sections == ["Carriera", "Vita privata"]


@pytest.mark.parametrize(
    "fields",
    [
        {"topic": ""},
        {"topic": "x" * 201},
        {"kind": "company"},
        {"depth": "everything"},
        {"language": "fr"},
        {"year": 1500},
        {"sections": [f"s{i}" for i in range(11)]},
        {"unknown": 1},
    ],
)
def test_invalid_input_is_rejected(fields) -> None:
    with pytest.raises(ValidationError):
        _input(**fields)


def test_a_blank_page_becomes_none() -> None:
    assert _input(page="   ").page is None


def test_validation_errors_never_contain_the_values() -> None:
    secret = "VALORE-DELL-UTENTE" * 20
    with pytest.raises(ValidationError) as caught:
        _input(topic=secret, extra_field=secret)

    rows = describe_validation_errors(caught.value)

    assert {"field": "unknown_field", "error": "extra_forbidden"} in rows
    assert secret not in repr(rows)


def test_normalize_text_folds_case_accents_and_punctuation() -> None:
    assert normalize_text("Amélie") == "amelie"
    assert normalize_text("Mars & Avril") == "mars and avril"
    assert normalize_text(None) == ""


def test_keywords_are_cleaned_deduplicated_and_limited() -> None:
    request = _input(keywords=["  Military   service ", "military service", "", "Dubbing", "x" * 61])

    assert request.keywords == ["Military service", "Dubbing"]
    with pytest.raises(ValidationError):
        _input(keywords=[f"word{i}" for i in range(7)])
    assert _input().keywords == []


def test_the_language_is_optional_and_the_planner_is_told_english_is_the_default() -> None:
    description = WikipediaToolInput.model_fields["language"].description

    assert _input().language is None and "English" in description and "another language" in description


@pytest.mark.parametrize(
    ("topic", "year", "expected_topic", "expected_year"),
    [
        ("Kwaidan (1964)", None, "Kwaidan", 1964),
        ("The Congress (2013)", None, "The Congress", 2013),
        ("Blade Runner 2049 (2017)", None, "Blade Runner 2049", 2017),
        ("Kwaidan (1964)", 1965, "Kwaidan", 1965),  # a year given explicitly wins
        ("Kwaidan (film)", None, "Kwaidan (film)", None),  # a real qualifier stays
        ("The Congress (2013 film)", None, "The Congress (2013 film)", None),
        ("Metropolis (1500)", None, "Metropolis (1500)", None),  # not a plausible year
        ("(1964)", None, "(1964)", None),
        ("1984 (1984)", None, "1984", 1984),
    ],
)
def test_a_year_in_parentheses_at_the_end_of_the_topic_becomes_the_year(topic, year, expected_topic, expected_year) -> None:
    request = _input(topic=topic, **({"year": year} if year else {}))

    assert (request.topic, request.year) == (expected_topic, expected_year)


def test_the_topic_asks_for_the_title_of_the_edition_and_forbids_inventing_one() -> None:
    description = WikipediaToolInput.model_fields["topic"].description

    assert "edition searched" in description and "English title if known for sure" in description
    assert "never invent one" in description and "the user's words" in description
