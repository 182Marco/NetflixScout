from __future__ import annotations

from web_lists.hydrate.hydrate_lists import hydrate_lists
from web_lists.hydrate.index_steps import index_steps
from web_lists.hydrate.item_key import item_key
from web_lists.schema.llm.lists_output import ListsOutput
from web_lists_support import MOVIE_REF, TMDB_STEP, TV_REF, VIDEO_REF, YOUTUBE_STEP, raw_list


def _hydrate(*refs, steps=None):
    index = index_steps([TMDB_STEP, YOUTUBE_STEP] if steps is None else steps)
    return hydrate_lists(ListsOutput.model_validate({"lists": [raw_list(*refs)]}).lists, index)


def test_item_key_is_stable() -> None:
    assert item_key("tmdb", "movie", 157336) == "tmdb:movie:157336"
    assert item_key("youtube", "video", "abc") == "youtube:video:abc"


def test_index_has_tmdb_and_youtube_keys() -> None:
    assert set(index_steps([TMDB_STEP, YOUTUBE_STEP])) == {
        "tmdb:movie:157336", "tmdb:tv:1396", "youtube:video:t3NQUGtQeAo",
    }


def test_movie_has_the_card_shape() -> None:
    (web_list,) = _hydrate(MOVIE_REF)
    assert web_list["list_id"] == "film-di-nolan" and web_list["kind"] == "mixed"
    (item,) = web_list["items"]
    assert item["key"] == "tmdb:movie:157336" and item["title"] == "Interstellar" and "name" not in item
    assert item["vote_average"] == 8.4 and item["poster_path"] == "/gEU2.jpg" and item["youtube_key"] is None
    assert item["links"] == [{"label": "TMDb", "url": "https://www.themoviedb.org/movie/157336"}]
    assert item["attribution"] == "JustWatch" and item["reason"] == "Spazio."
    assert "quote" not in item


def test_series_uses_name_and_first_air_date_as_release_date() -> None:
    (item,) = _hydrate(TV_REF)[0]["items"]
    assert item["name"] == "Breaking Bad" and "title" not in item
    assert item["release_date"] == "2008-01-20" and item["media_type"] == "tv"
    assert item["links"][0]["url"] == "https://www.themoviedb.org/tv/1396"


def test_missing_optional_fields_are_null_and_never_invented() -> None:
    bare = {"id": 5, "media_type": "movie", "title": "Bare"}
    step = TMDB_STEP.model_copy(update={"data": {"items": [bare]}})
    ref = {**MOVIE_REF, "id": 5}
    (item,) = _hydrate(ref, steps=[step])[0]["items"]
    assert item["overview"] is None and item["vote_average"] is None and item["poster_path"] is None
    assert item["release_date"] is None and item["attribution"] is None


def test_video_keeps_step_values_and_strips_control_characters() -> None:
    (item,) = _hydrate(VIDEO_REF)[0]["items"]
    assert item["title"] == "Nolan on Interstellar" and item["channel"] == "Canale"
    assert item["links"] == [{"label": "YouTube", "url": "https://www.youtube.com/watch?v=t3NQUGtQeAo"}]
    assert item["poster_url"] == "https://i.ytimg.com/vi/t3NQUGtQeAo/hqdefault.jpg"
    assert item["poster_path"] is None and item["youtube_key"] == "t3NQUGtQeAo"
    assert item["published_at"] == "2014-11-10" and item["attribution"] == "YouTube"
    assert item["id"] == "t3NQUGtQeAo" and item["media_type"] == "video"


def test_unknown_refs_are_dropped_and_empty_lists_removed() -> None:
    ghost = {**MOVIE_REF, "id": 1}
    wrong_type = {**MOVIE_REF, "media_type": "tv"}
    ghost_video = {**VIDEO_REF, "video_id": "zzzzzzzzzzz"}
    assert _hydrate(ghost, wrong_type, ghost_video) == []
    (web_list,) = _hydrate(ghost, MOVIE_REF)
    assert [item["id"] for item in web_list["items"]] == [157336]


def test_repeated_ref_is_kept_once() -> None:
    (web_list,) = _hydrate(MOVIE_REF, MOVIE_REF)
    assert len(web_list["items"]) == 1


def test_no_justwatch_attribution_without_it_in_the_step() -> None:
    step = TMDB_STEP.model_copy(update={"data": {**TMDB_STEP.data, "attributions": []}})
    (item,) = _hydrate(MOVIE_REF, steps=[step])[0]["items"]
    assert item["attribution"] is None


def test_malformed_step_rows_are_skipped() -> None:
    step = TMDB_STEP.model_copy(update={"data": {"items": [{"id": "x"}, "junk", {"id": 1, "media_type": "person", "title": "A"}]}})
    assert index_steps([step]) == {}
