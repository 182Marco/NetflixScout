"""`film_record`: English record of one movie by ID, through the turn budget; no network."""
from __future__ import annotations

from tests.tmdb_support import MOVIE_ID, make_tool, movie_payload
from tool.tmdb.film_record import english_overview, read_film_record, record_from_details

LONG = "A crew crosses a wormhole to find a new home for humanity while time slows down around them."


def details(**extra):
    return movie_payload(
        translations={"translations": [
            {"iso_639_1": "it", "iso_3166_1": "IT", "data": {"overview": "Un gruppo di esploratori."}},
            {"iso_639_1": "en", "iso_3166_1": "GB", "data": {"overview": "UK text. " + LONG}},
            {"iso_639_1": "en", "iso_3166_1": "US", "data": {"overview": LONG}},
        ]},
        alternative_titles={"titles": [{"title": "Interestelar"}, {"title": "Interstellar"}]},
        release_dates={"results": [{"release_dates": [{"release_date": "2014-10-26T00:00:00.000Z"}]}]},
        spoken_languages=[{"english_name": "English"}],
        production_countries=[{"name": "United States of America"}],
        genres=[{"id": 80, "name": "Crime"}],
        **extra,
    )


def test_record_is_english_whatever_the_turn_language_and_has_the_catalog_fields():
    tool, transport = make_tool({f"/movie/{MOVIE_ID}": details()})
    record, reason = read_film_record(tool, MOVIE_ID, turn_id="t1", now_ms=lambda: 123)
    assert reason == "" and record["overview"] == LONG  # US translation first
    assert record["tmdb_id"] == MOVIE_ID and record["fetched_ts"] == 123 and record["year"] == 2014
    assert record["release_years"] == (2014,) and record["genres"] == ("Crime",)
    assert record["cast"][0] == "Actor 0" and len(record["cast"]) == 15
    assert record["alternative_titles"] == ("Interestelar", "Interstellar")
    assert transport.params(f"/movie/{MOVIE_ID}")["language"] == "en-US"
    assert "translations" in transport.params(f"/movie/{MOVIE_ID}")["append_to_response"]


def test_non_english_film_without_an_english_translation_has_no_overview():
    data = details(original_language="ja", overview="日本語のあらすじ。" * 20)
    data["translations"] = {"translations": [{"iso_639_1": "ja", "data": {"overview": "日本語"}}]}
    assert english_overview(data) is None
    tool, _ = make_tool({f"/movie/{MOVIE_ID}": data})
    record, _ = read_film_record(tool, MOVIE_ID)
    assert record["overview"] is None


def test_english_original_uses_its_own_overview():
    data = movie_payload(overview=LONG)
    data["translations"] = {"translations": []}
    assert english_overview(data) == LONG
    assert english_overview({**data, "original_language": "fr"}) is None


def test_all_release_years_are_reported():
    data = details(release_date="1964-01-01")
    data["release_dates"] = {"results": [{"release_dates": [{"release_date": "1962-05-01T00:00:00.000Z"}]}]}
    assert record_from_details(data, fetched_ts=1)["release_years"] == (1962, 1964)


def test_adult_and_failures_return_a_reason_not_an_exception():
    tool, _ = make_tool({f"/movie/{MOVIE_ID}": details(adult=True)})
    assert read_film_record(tool, MOVIE_ID) == (None, "adult")
    tool, _ = make_tool({})
    assert read_film_record(tool, MOVIE_ID) == (None, "not_found")


def test_the_call_spends_the_turn_budget_and_a_repeat_is_free():
    tool, transport = make_tool({f"/movie/{MOVIE_ID}": details()}, max_calls=1)
    assert read_film_record(tool, MOVIE_ID, turn_id="t")[1] == ""
    assert read_film_record(tool, MOVIE_ID, turn_id="t")[1] == ""  # memo/cache: no second call
    assert len(transport.calls) == 1
    other_tool, _ = make_tool({f"/movie/{MOVIE_ID}": details()}, max_calls=1)
    ctx = other_tool.new_context(other_tool._credentials(), api_language="en-US", turn_id="t")
    ctx.budget.try_reserve()
    assert read_film_record(other_tool, MOVIE_ID, turn_id="t") == (None, "call_limit_reached")
