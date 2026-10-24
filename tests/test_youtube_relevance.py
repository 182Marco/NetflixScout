"""Offline tests of `youtube/relevance.py`: false negatives to keep, homonyms to drop, one
test per drop reason. Titles are shaped like real YouTube results."""
from __future__ import annotations

import inspect

import pytest

from youtube.models import VideoKind, YoutubeToolInput
from youtube.relevance import (
    Screening,
    count_reasons,
    parse_duration,
    prescreen,
    screen,
    screen_details,
    verification,
)

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


@pytest.mark.parametrize("kind", [K.trailer, K.making_of, K.behind_the_scenes])
def test_release_period_confirms_promotional_videos(kind) -> None:
    result = check(req("Arrival", year=2016, director="Denis Villeneuve"), kind, "Arrival", published_at="2016-11-10T00:00:00Z")

    assert result.kept and "release_period" in result.matched_on


@pytest.mark.parametrize("kind", [K.director_interview, K.author_commentary])
def test_release_period_never_confirms_interviews_or_commentaries(kind) -> None:
    # Published in the release year, but nothing in the text confirms it is this "Arrival".
    result = check(
        req("Arrival", year=2016, director="Denis Villeneuve"),
        kind,
        "Arrival interview with Amy Adams",
        published_at="2016-11-10T00:00:00Z",
    )

    assert (result.kept, result.reason) == (False, "homonym_risk")
    assert "release_period" not in result.matched_on


def test_interviews_are_confirmed_by_text_anchors() -> None:
    request_ = req("Arrival", year=2016, director="Denis Villeneuve")

    assert check(request_, K.director_interview, "Arrival (2016) cast interview").kept
    assert check(request_, K.director_interview, "Arrival interview", "Denis Villeneuve on the film").kept


def test_one_word_interview_with_nothing_to_check_is_kept_unchecked_only_with_film_context() -> None:
    title = "Arrival interview with Amy Adams"
    with_context = check(req("Arrival"), K.director_interview, title, "The cast of the movie on set.", "2016-11-10T00:00:00Z")
    without_context = check(req("Arrival"), K.director_interview, title, published_at="2016-11-10T00:00:00Z")

    assert with_context.kept and "homonym_unchecked" in with_context.notes
    assert (without_context.kept, without_context.reason) == (False, "homonym_risk")


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


# --- prescreen: what the snippet title alone may decide ---------------------------------------


@pytest.mark.parametrize(
    ("title", "reason"),
    [
        ("Dune: Part Two REACTION", "negative_pattern"),
        ("Dune: Part Two | Fan Made trailer", "negative_pattern"),
        ("The Arrival (1996) Making of", "year_conflict"),
    ],
)
def test_prescreen_drops_only_what_the_title_proves(title, reason) -> None:
    dropped = prescreen(req("Arrival", year=2016), title=title)

    assert dropped is not None and (dropped.kept, dropped.reason) == (False, reason)


@pytest.mark.parametrize(
    "title",
    [
        "Making of a sci-fi epic",  # no anchor in the title: decided later on the full description
        "Her - Making of",  # one-word title: the director may be in the full description
        "Arrival (2017) making of",  # within one year
    ],
)
def test_prescreen_never_decides_anchors_or_homonyms(title) -> None:
    assert prescreen(req("Arrival", year=2016, director="Denis Villeneuve"), title=title) is None


def test_prescreen_reads_only_the_title() -> None:
    # No description parameter: the truncated snippet description can never drop a video.
    assert list(inspect.signature(prescreen).parameters) == ["request", "title"]


# --- other_format: the title declares another format (fix 2 after the live run) ---------------
# Titles paraphrase the false positives of the live run (real API data is not kept in the repo).


@pytest.mark.parametrize(
    ("request_", "kind", "title"),
    [
        # Run 1: a review kept as an interview.
        (req("Dune: Parte Due", director="Denis Villeneuve"), K.director_interview, "MovieBlog 900: Recensione Dune: Parte Due"),
        # Run 7: the Italian trailer kept as an interview.
        (req("Parasite", year=2019, director="Bong Joon-ho"), K.director_interview, "PARASITE - Trailer Italiano Ufficiale (2019)"),
        # Run 9: a review of an Italian film, director not in the request.
        (req("C'è ancora domani"), K.director_interview, "C'è ancora domani - Recensione e Analisi"),
        # Run 17: a full movie upload kept as an interview.
        (req("Mare dentro", alternative_titles=["Mar adentro"]), K.director_interview, "MAR ADENTRO PELÍCULA COMPLETA EN ESPAÑOL"),
        # Run 20: a full movie kept as a trailer.
        (req("The Dungeon of Harrow", year=1962), K.trailer, "The Dungeon of Harrow (1962) | Full Movie"),
        # A trailer breakdown is not a making-of.
        (req("Interstellar"), K.making_of, "Interstellar | Teaser Trailer"),
        (req("Interstellar"), K.behind_the_scenes, "Interstellar Movie Review"),
        (req("Interstellar"), K.author_commentary, "Interstellar - film completo in italiano"),
    ],
)
def test_other_format_titles_are_dropped(request_, kind, title) -> None:
    result = check(request_, kind, title, "", "2019-06-01T00:00:00Z")

    assert (result.kept, result.reason) == (False, "other_format")


@pytest.mark.parametrize(
    ("request_", "kind", "title"),
    [
        # The requested person is named in the title.
        (req("Dune: Part Two", director="Denis Villeneuve"), K.director_interview, "Denis Villeneuve reviews the Dune: Part Two trailer"),
        (req("Arrival", director="Denis Villeneuve"), K.director_interview, "Villeneuve on the Arrival trailer"),
        # A word of the requested kind is in the title.
        (req("Dune: Part Two"), K.director_interview, "Dune: Part Two | Official Trailer & Interview"),
        (req("Interstellar"), K.making_of, "Making of the Interstellar trailer"),
        (req("Interstellar"), K.behind_the_scenes, "Interstellar review and behind the scenes"),
        (req("Inception"), K.author_commentary, "Inception review: Nolan explains the ending"),
        # A trailer title is compatible with a trailer request.
        (req("Dune: Part Two"), K.trailer, "Dune: Part Two | Official Trailer"),
        (req("Dune: Part Two"), K.trailer, "Dune: Part Two teaser trailer review"),
        # Whole words only: "preview" is not "review", "trailerpark" is not "trailer".
        # (no word of the requested kind here, so only whole-word matching keeps them)
        (req("Interstellar"), K.behind_the_scenes, "Interstellar exclusive preview"),
        (req("Interstellar"), K.making_of, "Interstellar at the Trailerpark festival"),
    ],
)
def test_mixed_titles_stay_valid(request_, kind, title) -> None:
    # Film context in the description: one-word titles with nothing to check need it.
    assert check(request_, kind, title, "A film by Christopher Nolan.").kept


def test_a_review_naming_the_director_stays_known_limit() -> None:
    """Run 17 residue: the person exemption keeps a review that names the director in its title."""
    request_ = req("Mare dentro", alternative_titles=["Mar adentro"], director="Alejandro Amenábar")

    assert check(request_, K.director_interview, "Sea Inside Movie Review (Mar adentro) - Alejandro Amenábar").kept


def test_a_declared_format_without_conflict_keeps_the_previous_behaviour() -> None:
    # No format word: the title is judged by the usual anchors (kept, kind not confirmed).
    result = check(req("Dune: Parte Due", director="Denis Villeneuve"), K.director_interview, "Dune: Parte Due (2024) di Denis Villeneuve")

    assert result.kept and "kind_unconfirmed" in result.notes


def test_format_words_in_the_description_never_drop() -> None:
    result = check(req("Dune: Part Two"), K.making_of, "Dune: Part Two making of", "Full movie review and trailer below.")

    assert result.kept


def test_other_format_is_decided_on_the_title_only_not_in_prescreen() -> None:
    # Prescreen has no kind: a "trailer" title may be a valid trailer request.
    assert prescreen(req("Interstellar"), title="Interstellar | Teaser Trailer") is None



# --- fix 3: cast members as people of the film ---------------------------------------------------


def test_oppenheimer_historic_clip_is_a_homonym_once_the_cast_is_known() -> None:
    """Live run 5: clips about the physicist kept for "interviews with the Oppenheimer cast"."""
    request_ = req("Oppenheimer", cast=["Cillian Murphy"], kinds=["cast_interview"])

    historic = check(request_, K.cast_interview, 'J. Robert Oppenheimer: "I am become Death, the destroyer of worlds."')
    interview = check(request_, K.cast_interview, "Cillian Murphy on playing Oppenheimer")

    assert (historic.kept, historic.reason) == (False, "homonym_risk")
    assert interview.kept and interview.matched_on == ("title", "cast")


def test_oppenheimer_without_names_needs_film_context() -> None:
    """Nothing to check without a year or a person (never invented): a clip about the physicist
    with no word of film context is a homonym; with film context it is kept and noted."""
    request_ = req("Oppenheimer", kinds=["cast_interview"])
    historic = check(request_, K.cast_interview, 'J. Robert Oppenheimer: "I am become Death"', "Archive footage, 1965.")
    film = check(request_, K.cast_interview, "Oppenheimer cast interview", "The cast of the Christopher Nolan film.")

    assert (historic.kept, historic.reason) == (False, "homonym_risk")
    assert film.kept and "homonym_unchecked" in film.notes


def test_a_cast_member_alone_is_an_anchor_noted_as_film_title_absent() -> None:
    result = check(req("Oppenheimer: the film", cast=["Cillian Murphy"]), K.cast_interview, "Cillian Murphy interview 2023")

    assert result.kept and result.matched_on == ("cast",) and "film_title_absent" in result.notes


def test_cast_surname_follows_the_same_rule_as_the_director() -> None:
    request_ = req("Arrival", cast=["Amy Adams", "Ang Lee"])

    assert "cast" in check(request_, K.cast_interview, "Adams talks Arrival").matched_on
    assert check(request_, K.cast_interview, "Lee talks Arrival").reason == "homonym_risk"


def test_cast_interview_kind_words() -> None:
    request_ = req("Dune: Part Two")

    assert "kind_unconfirmed" not in check(request_, K.cast_interview, "Dune: Part Two red carpet").notes
    assert "kind_unconfirmed" not in check(request_, K.cast_interview, "Dune: Part Two cast interview").notes
    assert "kind_unconfirmed" in check(request_, K.cast_interview, "Dune: Part Two | Zendaya").notes


def test_a_review_naming_a_requested_cast_member_is_not_other_format() -> None:
    # Same exemption as the director (fix 2): the requested person is named in the title.
    request_ = req("Dune: Part Two", cast=["Zendaya"])

    assert check(request_, K.cast_interview, "Zendaya reviews her Dune: Part Two trailer").kept
    assert check(request_, K.cast_interview, "Dune: Part Two review").reason == "other_format"


def test_release_period_still_never_confirms_cast_interviews() -> None:
    result = check(
        req("Arrival", year=2016, cast=["Amy Adams"]),
        K.cast_interview,
        "Arrival interview",
        published_at="2016-11-10T00:00:00Z",
    )

    assert (result.kept, result.reason) == (False, "homonym_risk")


# --- live E2E 2026-10-24: wrong confirmations and homonyms -------------------------------------
# Titles are the real ones of the live run; the full descriptions were not saved, so the
# descriptions below are illustrative credits and tags.


def test_a_kind_word_only_in_the_description_does_not_confirm_the_kind() -> None:
    """Case 1: a cast video confirmed as a director interview by credits in the description."""
    request_ = req("Past Lives", kinds=["director_interview"])
    cast_video = check(
        request_,
        K.director_interview,
        "The Cast of Past Lives Talk About Their Past Lives",
        "Greta Lee, Teo Yoo and John Magaro on the film by writer-director Celine Song.",
    )

    assert cast_video.kept and "kind_unconfirmed" in cast_video.notes
    assert verification(cast_video.notes) == "to_verify"


def test_a_podcast_naming_the_film_is_not_a_confirmed_cast_interview() -> None:
    """Case 17: a podcast episode listing several films, confirmed as a cast interview."""
    request_ = req("Il ragazzo e l'airone", kinds=["cast_interview"])
    podcast = check(
        request_,
        K.cast_interview,
        "Deadpool & Wolverine, Il Ragazzo e l'Airone, CENTO CHILI DI MUSICAL | 🍕 PPP 295",
        "Il cast di Power Pizza parla dei film della settimana.",
    )

    assert podcast.kept and "kind_unconfirmed" in podcast.notes
    assert verification(podcast.notes) == "to_verify"


def test_a_kind_word_in_the_title_still_confirms() -> None:
    request_ = req("Anatomia di una caduta", alternative_titles=["Anatomie d'une chute"], kinds=["cast_interview"])
    result = check(request_, K.cast_interview, "Anatomie d’une chute – Press Conference - EV – Cannes 2023")

    assert result.kept and verification(result.notes) == "confirmed"


@pytest.mark.parametrize(
    ("title", "kind", "description"),
    [
        # Case 5 ("Parasite", no year, no person).
        ("Parasite Explains Circularity on GameSir G7", K.author_commentary, "Testing the stick drift of a gamepad."),
        ("This Parasite Replaces a Fish’s Tongue With Its Own Body", K.author_commentary, "Nature is weird."),
        ("Hulda Clark talks about the mighty green hulls of the black walnut as a powerful #parasite cleanse.",
         K.director_interview, "Natural health tips."),
        # Case 14 ("Her", no year, no person): the pronoun matches.
        ("H.E.R. Surprises 10-Year-Old Viral Singer After Seeing Her ‘Best Part’ Cover!", K.director_interview,
         "Watch the full episode of the show."),
        ("Tracee Ellis Ross says loving her appearance was a choice", K.director_interview, "A conversation about self-love."),
    ],
)
def test_unverifiable_one_word_homonyms_without_film_context_are_dropped(title, kind, description) -> None:
    film = "Parasite" if "arasite" in title else "Her"
    result = check(req(film, kinds=[kind.value]), kind, title, description)

    assert (result.kept, result.reason) == (False, "homonym_risk")


@pytest.mark.parametrize(
    ("film", "kind", "title", "description"),
    [
        ("Parasite", K.director_interview, "Bong Joon-Ho Reveals Where He Got the Idea for 'Parasite'",
         "The director of the film talks to IMDb."),
        ("Parasite", K.cast_interview, "The Cast of 'Parasite' Talks Celebrity Sightings | SAG Awards 2020", ""),
        ("Her", K.director_interview, "Spike Jonze on Her", "The director on his 2013 movie."),
    ],
)
def test_one_word_titles_with_film_context_stay_unchecked(film, kind, title, description) -> None:
    result = check(req(film, kinds=[kind.value]), kind, title, description)

    assert result.kept and "homonym_unchecked" in result.notes

