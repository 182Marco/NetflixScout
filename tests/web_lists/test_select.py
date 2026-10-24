"""Which references are accepted: authorized id, quote in the answer, name in the quote, no cue."""
from __future__ import annotations

from web_lists.hydrate.index_steps import index_steps
from web_lists.schema.llm.lists_output import ListsOutput
from web_lists.select.select_refs import select_refs
from web_lists_support import ANSWER, MOVIE_REF, TMDB_STEP, TV_REF, VIDEO_REF, YOUTUBE_STEP, raw_list

INDEX = index_steps([TMDB_STEP, YOUTUBE_STEP])


def _select(*refs, answer=ANSWER, index=INDEX, lists=None):
    raw = lists if lists is not None else [raw_list(*refs)]
    selected = select_refs(ListsOutput.model_validate({"lists": raw}).lists, answer, index)
    return [item for web_list in selected for item in web_list.items]


def _ref(quote, **base):
    return {**MOVIE_REF, "quote": quote, **base}


def test_valid_refs_are_kept_in_order() -> None:
    assert [r.reason for r in _select(MOVIE_REF, TV_REF, VIDEO_REF)] == ["Spazio.", "Serie.", "Intervista."]


def test_unknown_id_wrong_type_and_other_turn_ids_are_dropped() -> None:
    assert _select(_ref(MOVIE_REF["quote"], id=999), _ref(MOVIE_REF["quote"], media_type="tv")) == []
    assert _select({**VIDEO_REF, "video_id": "zzzzzzzzzzz"}) == []


def test_resource_in_the_index_but_not_in_the_answer_is_dropped() -> None:
    answer = "Ecco solo Breaking Bad: la serie sulla chimica."
    assert [r.reason for r in _select(MOVIE_REF, TV_REF, answer=answer)] == ["Serie."]


def test_quote_must_be_in_the_answer() -> None:
    assert _select(_ref("Interstellar è un capolavoro assoluto")) == []
    assert _select(_ref("")) == []


def test_quote_must_name_the_resource_and_the_id_must_match_the_title() -> None:
    assert _select(_ref("un viaggio nello spazio.")) == []  # no title in the quote
    # Right quote, but the id belongs to another title of the turn.
    assert _select(_ref("Breaking Bad: la serie sulla chimica.", id=157336)) == []


def test_markdown_accents_and_articles_do_not_break_the_match() -> None:
    step = TMDB_STEP.model_copy(update={"data": {"items": [
        {"id": 2, "media_type": "movie", "title": "The Dungeon of Harrow"}]}})
    index = index_steps([step])
    ref = {**MOVIE_REF, "id": 2, "quote": "__Dungeon of Harrow__ è un horror"}
    assert len(_select(ref, answer="Provalo: __Dungeon of Harrow__ è un horror.", index=index)) == 1


def test_negation_and_comparison_before_the_title_are_dropped() -> None:
    for sentence in (
        "Non ti consiglio Interstellar perché è lungo.",
        "Meglio di Interstellar c'è poco.",
        "A differenza di Interstellar questo è breve.",
        "Unlike Interstellar, this one is short.",
    ):
        assert _select(_ref(sentence), answer=sentence) == [], sentence


def test_a_cue_after_the_title_or_outside_the_quote_does_not_drop_it() -> None:
    sentence = "Interstellar non è breve ma ne vale la pena."
    assert len(_select(_ref(sentence), answer=sentence)) == 1
    answer = "Non cerchi horror? Interstellar è perfetto."
    assert len(_select(_ref("Interstellar è perfetto."), answer=answer)) == 1


def test_known_limit_a_comparison_without_a_cue_word_passes() -> None:
    sentence = "Interstellar è simile ma meno riuscito."
    assert len(_select(_ref(sentence), answer=sentence)) == 1


def test_same_title_records_need_the_year_in_the_quote() -> None:
    step = TMDB_STEP.model_copy(update={"data": {"items": [
        {"id": 1, "media_type": "movie", "title": "Dune", "release_date": "1984-12-14"},
        {"id": 2, "media_type": "movie", "title": "Dune", "release_date": "2021-09-15"}]}})
    index = index_steps([step])
    answer = "Guarda Dune (2021), più recente. Oppure Dune."
    assert [i.id for i in _select({**MOVIE_REF, "id": 2, "quote": "Guarda Dune (2021), più recente."}, answer=answer, index=index)] == [2]
    assert _select({**MOVIE_REF, "id": 2, "quote": "Oppure Dune."}, answer=answer, index=index) == []


URL = "https://www.youtube.com/watch?v=t3NQUGtQeAo"


def _video(quote):
    # The quote carries the id but not the title, so the id is what identifies the video.
    return _select({**VIDEO_REF, "quote": quote}, answer=quote)


def test_video_can_be_matched_by_its_id() -> None:
    assert len(_video(f"Intervista al regista: {URL}")) == 1


def test_video_identified_by_id_needs_a_real_id() -> None:
    assert _video("Intervista al regista: https://www.youtube.com/watch?v=aaaaaaaaaaa") == []
    assert _video("Intervista al regista, senza link") == []


def test_video_identified_by_id_is_dropped_in_an_exclusion_context() -> None:
    assert _video(f"Non ti consiglio questa intervista: {URL}") == []
    assert _video(f"Tranne questo video ({URL}) il resto va bene") == []


def test_video_identified_by_id_is_dropped_in_a_comparison_the_cues_catch() -> None:
    assert _video(f"Meglio di {URL} non c'è nulla") == []
    assert _video(f"Unlike {URL}, the rest is worse") == []


def test_video_cue_after_the_id_does_not_drop_it() -> None:
    assert len(_video(f"Guarda {URL}: non è lunga")) == 1


def test_video_recommended_by_title_is_accepted_and_excluded_by_title_is_dropped() -> None:
    assert len(_select(VIDEO_REF)) == 1
    sentence = "Non guardare Nolan on Interstellar su YouTube."
    assert _select({**VIDEO_REF, "quote": sentence}, answer=sentence) == []


def test_duplicates_are_kept_once_inside_and_across_lists() -> None:
    lists = [raw_list(MOVIE_REF, MOVIE_REF, list_id="a"), raw_list(MOVIE_REF, TV_REF, list_id="b")]
    assert [r.reason for r in _select(lists=lists)] == ["Spazio.", "Serie."]


def test_empty_lists_are_removed() -> None:
    ghost = _ref(MOVIE_REF["quote"], id=999)
    selected = select_refs(ListsOutput.model_validate({"lists": [raw_list(ghost)]}).lists, ANSWER, INDEX)
    assert selected == []
