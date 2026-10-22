"""Offline tests of `youtube/relevance.py`: false negatives to keep, homonyms to drop, one
test per drop reason. Titles are shaped like real YouTube results."""
from __future__ import annotations

import pytest

from youtube.models import VideoKind, YoutubeToolInput
from youtube.relevance import Screening, count_reasons, parse_duration, screen, screen_details

K = VideoKind


def req(title: str = "Dune", **fields) -> YoutubeToolInput:
    return YoutubeToolInput.model_validate({"query": "q", "title": title, "kinds": ["making_of"], **fields})


def check(request: YoutubeToolInput, kind: VideoKind, title: str, description: str = "", published_at: str = "") -> Screening:
    return screen(request, kind, title=title, description=description, published_at=published_at)


# --- false negatives: valid videos without the expected words are kept ---------------


@pytest.mark.parametrize(
    ("request_", "kind", "title", "description"),
    [
        # Interview without the word "interview".
        (req("Dune: Part Two", director="Denis Villeneuve"), K.director_interview, "Denis Villeneuve on directing Dune: Part Two", ""),
        # Featurette without "behind the scenes".
        (req("Dune: Part Two", year=2024), K.behind_the_scenes, "Building the Sandworm | DUNE: PART TWO", ""),
        # Italian interview, Italian title, no "intervista".
        (req("C'è ancora domani", director="Paola Cortellesi"), K.director_interview, "Paola Cortellesi racconta C'è ancora domani", ""),
        # Official featurette for a one-word title, confirmed by the release period.
        (req("Oppenheimer", year=2023), K.behind_the_scenes, "'Oppenheimer' | Official Featurette", ""),
        # Film title only in the description.
        (req("Dune: Part Two"), K.making_of, "The making of a desert epic", "Behind the scenes of Dune: Part Two."),
        # Case, punctuation and accents ignored.
        (req("Amélie", year=2001), K.making_of, "AMELIE (2001) — MAKING OF", ""),
        # Alternative title from the conversation.
        (req("The Sea Inside", alternative_titles=["Mar adentro"]), K.making_of, "Mar adentro - Making of", ""),
        # "&" read as "and".
        (req("Mars & Avril"), K.behind_the_scenes, "Mars and Avril : dans les coulisses", ""),
        # HTML entities of the search snippet.
        (req("Schindler's List"), K.making_of, "Schindler&#39;s List: the making of", ""),
        # An interview that mentions trailer and review is still an interview.
        (req("Dune: Part Two", director="Denis Villeneuve"), K.director_interview, "Denis Villeneuve reviews the Dune: Part Two trailer", ""),
        # Director only, film title absent: kept and noted.
        (req("Dune: Part Two", director="Denis Villeneuve"), K.director_interview, "Denis Villeneuve interview 2024", ""),
    ],
)
def test_valid_videos_without_expected_words_are_kept(request_, kind, title, description) -> None:
    result = check(request_, kind, title, description, published_at="2024-03-01T10:00:00Z")

    assert result.kept, result


def test_missing_kind_word_is_kept_with_a_note() -> None:
    result = check(req("Dune: Part Two", director="Denis Villeneuve"), K.director_interview, "Denis Villeneuve on Dune: Part Two")

    assert result.kept and "kind_unconfirmed" in result.notes
    assert result.matched_on == ("title", "director")


def test_notes_say_what_matched_and_what_did_not() -> None:
    in_description = check(req("Dune: Part Two"), K.making_of, "A desert epic", "Making of Dune: Part Two")
    director_only = check(req("Dune: Part Two", director="Denis Villeneuve"), K.director_interview, "Denis Villeneuve interview")

    assert "title_in_description_only" in in_description.notes
    assert director_only.matched_on == ("director",) and "film_title_absent" in director_only.notes


def test_a_generic_title_with_nothing_to_check_is_kept_and_noted() -> None:
    result = check(req("Heat"), K.making_of, "Heat - Making of")

    assert result.kept and "homonym_unchecked" in result.notes


def test_surname_alone_is_a_director_anchor_when_long_enough() -> None:
    long_surname = check(req("Arrival", director="Denis Villeneuve"), K.director_interview, "Villeneuve talks Arrival")
    short_surname = check(req("Arrival", director="Ang Lee"), K.director_interview, "Lee talks Arrival")

    assert long_surname.kept and "director" in long_surname.matched_on
    assert not short_surname.kept and short_surname.reason == "homonym_risk"


# --- homonyms -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("request_", "kind", "title", "published_at"),
    [
        # Another film with the same one-word title, no confirmation.
        (req("Arrival", year=2016, director="Denis Villeneuve"), K.making_of, "Arrival - Making of", "2009-05-01T00:00:00Z"),
        # A cooking video.
        (req("Heat", year=1995, director="Michael Mann"), K.behind_the_scenes, "Heat: behind the scenes of my kitchen", "2022-01-01T00:00:00Z"),
        # "Three" (2005) with nothing that confirms it.
        (req("Three", year=2005, director="Stewart Raffill"), K.making_of, "Three - making of the music video", "2019-06-01T00:00:00Z"),
        # Only the main title of "Dune: Part Two", published for the 2021 film.
        (req("Dune: Part Two", year=2024), K.making_of, "Dune - The Making of", "2021-10-01T00:00:00Z"),
    ],
)
def test_homonyms_are_dropped(request_, kind, title, published_at) -> None:
    result = check(request_, kind, title, published_at=published_at)

    assert (result.kept, result.reason) == (False, "homonym_risk")


@pytest.mark.parametrize(
    ("title", "description", "published_at", "anchor"),
    [
        ("Arrival (2016) - Making of", "", "", "year"),
        ("Arrival making of", "Directed by Denis Villeneuve", "", "director"),
        ("Arrival making of", "", "2016-11-10T00:00:00Z", "release_period"),
        ("Arrival making of", "", "2019-11-10T00:00:00Z", "release_period"),
    ],
)
def test_a_one_word_title_is_confirmed_by_year_director_or_release_period(title, description, published_at, anchor) -> None:
    result = check(req("Arrival", year=2016, director="Denis Villeneuve"), K.making_of, title, description, published_at)

    assert result.kept and anchor in result.matched_on


def test_words_match_whole_not_by_inclusion() -> None:
    # "Dune" is not in "Dunes"; "Three" is not in "Threesome".
    assert check(req("Dune"), K.making_of, "Sand dunes: making of a documentary").reason == "no_anchor"
    assert check(req("Three"), K.making_of, "Threesome making of").reason == "no_anchor"


# --- year conflicts -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "kept"),
    [
        ("The Arrival (1996) Trailer", False),
        ("Arrival (2017) Trailer", True),  # within one year
        ("Arrival (2016) vs The Arrival (1996)", True),  # one parenthesized year matches
        ("Arrival trailer 1996 reupload", True),  # not in parentheses: no conflict
    ],
)
def test_year_conflict_only_from_parenthesized_years_in_the_title(title, kept) -> None:
    result = check(req("Arrival", year=2016, director="Denis Villeneuve"), K.trailer, title, "Denis Villeneuve", "")

    assert result.kept is kept
    if not kept:
        assert result.reason == "year_conflict"


def test_a_year_in_the_description_never_conflicts() -> None:
    result = check(req("Dune: Part Two", year=2024), K.making_of, "Dune: Part Two making of", "Remember Dune (2021)?")

    assert result.kept


# --- every drop reason ----------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "Dune: Part Two REACTION",
        "Dune: Part Two - Trailer Reactions",
        "Dune: Part Two parody",
        "Dune: Part Two | Fan Made trailer",
        "Dune: Part Two concept trailer",
    ],
)
def test_negative_pattern_in_the_video_title(title) -> None:
    assert check(req("Dune: Part Two"), K.trailer, title).reason == "negative_pattern"


def test_negative_words_in_the_description_are_ignored() -> None:
    result = check(req("Dune: Part Two"), K.director_interview, "Dune: Part Two interview", "Our reaction video is linked below.")

    assert result.kept


def test_no_anchor() -> None:
    result = check(req("Dune: Part Two", director="Denis Villeneuve"), K.making_of, "Making of a sci-fi epic", "Desert planet.")

    assert (result.kept, result.reason) == (False, "no_anchor")


# --- duration and Shorts ---------------------------------------------------------------


KEPT = Screening(kept=True, matched_on=("title",))


@pytest.mark.parametrize(
    ("value", "seconds"),
    [("PT45S", 45), ("PT4M13S", 253), ("PT1H2M3S", 3723), ("P1DT1S", 86401), ("P0D", None), ("", None), (None, None), ("4:13", None)],
)
def test_parse_duration(value, seconds) -> None:
    assert parse_duration(value) == seconds


@pytest.mark.parametrize("kind", [K.director_interview, K.making_of, K.behind_the_scenes, K.author_commentary])
def test_a_short_interview_is_never_dropped_by_duration_alone(kind) -> None:
    result = screen_details(KEPT, kind, title="Villeneuve on Dune", description="", duration_seconds=45)

    assert result.kept and "very_short" in result.notes


@pytest.mark.parametrize("seconds", [15, 45, 59, 120])
def test_teasers_and_trailers_are_never_dropped(seconds) -> None:
    result = screen_details(KEPT, K.trailer, title="Dune: Part Two Teaser #shorts", description="", duration_seconds=seconds)

    assert result.kept


@pytest.mark.parametrize(
    ("title", "description", "seconds", "kept"),
    [
        ("Dune making of #shorts", "", 40, False),
        ("Dune making of", "#Shorts #dune", 170, False),
        ("Dune making of #short", "", None, False),  # declared Short, duration unknown
        ("Dune making of #shorts", "", 600, True),  # too long to be a Short: the tag is wrong
        ("Dune making of #shortsfilm", "", 40, True),  # another hashtag
        ("Dune making of", "", 40, True),  # short but not declared: kept, noted
    ],
)
def test_short_video_only_when_self_declared(title, description, seconds, kept) -> None:
    result = screen_details(KEPT, K.making_of, title=title, description=description, duration_seconds=seconds)

    assert result.kept is kept
    if not kept:
        assert result.reason == "short_video"


def test_unknown_duration_is_noted_and_kept() -> None:
    result = screen_details(KEPT, K.making_of, title="Dune making of", description="", duration_seconds=None)

    assert result.kept and "duration_unknown" in result.notes


def test_a_dropped_result_stays_dropped() -> None:
    dropped = Screening(kept=False, reason="no_anchor")

    assert screen_details(dropped, K.making_of, title="x", description="", duration_seconds=600) is dropped


# --- no score, no reordering, data untouched ------------------------------------------


def test_screening_has_no_score_and_input_texts_are_not_changed() -> None:
    title = "Schindler&#39;s List:   the MAKING of"
    result = check(req("Schindler's List"), K.making_of, title)

    assert set(Screening.__dataclass_fields__) == {"kept", "reason", "matched_on", "notes"}
    assert title == "Schindler&#39;s List:   the MAKING of"
    assert result.kept


def test_count_reasons_for_the_trace() -> None:
    screenings = [
        Screening(kept=False, reason="no_anchor"),
        Screening(kept=True),
        Screening(kept=False, reason="no_anchor"),
        Screening(kept=False, reason="homonym_risk"),
    ]

    assert count_reasons(screenings) == {"no_anchor": 2, "homonym_risk": 1}
