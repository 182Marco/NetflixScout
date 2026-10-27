from __future__ import annotations

import pytest
from tmdb_support import MOVIE_ID, make_tool, movie_payload, run, tmdb_meta


def _essentials(result: dict) -> dict:
    return tmdb_meta(result)["requests"][0]["entities"][f"movie:{MOVIE_ID}"]["essentials"]


@pytest.mark.parametrize(("turn_language", "api_language"), [("it", "it-IT"), ("en", "en-US"), (None, "en-US"), ("de", "de-DE"), ("fr", "en-US")])
def test_api_language_follows_the_turn(turn_language, api_language) -> None:
    tool, transport = make_tool({f"/movie/{MOVIE_ID}": movie_payload()})

    result = run(tool, {"operation": "movie_details", "tmdb_id": MOVIE_ID}, language=turn_language)

    assert transport.params(f"/movie/{MOVIE_ID}")["language"] == api_language
    assert tmdb_meta(result)["language"] == api_language


def test_translations_are_always_appended_and_fill_missing_fields() -> None:
    tool, transport = make_tool({f"/movie/{MOVIE_ID}": movie_payload(overview="", title="")})

    result = run(tool, {"operation": "movie_details", "tmdb_id": MOVIE_ID}, language="it")

    assert "translations" in transport.params(f"/movie/{MOVIE_ID}")["append_to_response"]
    assert len(transport.calls) == 1  # fallback without extra calls
    assert _essentials(result)["overview"] == "English overview."
    assert _essentials(result)["overview_language"] == "en"
    assert result["chunks"][0]["title"] == "Interstellar"


def test_localized_text_is_kept_and_identity_stays_stable() -> None:
    payload = movie_payload(title="Interstellare", original_title="Interstellar")
    tool, _ = make_tool({f"/movie/{MOVIE_ID}": payload})

    result = run(tool, {"operation": "movie_details", "tmdb_id": MOVIE_ID}, language="it")

    card = result["chunks"][0]["testo"]
    assert "Interstellare (2014)" in card and "titolo originale: Interstellar [en]" in card
    assert f"TMDb movie/{MOVIE_ID}" in card and "IMDb tt0816692" in card
    assert "overview_language" not in _essentials(result)


def test_image_and_video_language_fallbacks_ride_on_the_same_call() -> None:
    tool, transport = make_tool({f"/movie/{MOVIE_ID}": movie_payload()})

    run(tool, {"operation": "movie_details", "tmdb_id": MOVIE_ID, "facets": ["images", "videos"]}, language="it")

    params = transport.params(f"/movie/{MOVIE_ID}")
    assert params["include_image_language"] == "it,en,null"
    assert params["include_video_language"] == "it,en"
    assert len(transport.calls) == 1


def test_empty_italian_reviews_fall_back_to_english_with_one_counted_call() -> None:
    reviews_en = {"results": [{"author": "A", "content": "Great.", "author_details": {"rating": 9}}]}
    tool, transport = make_tool(
        {f"/movie/{MOVIE_ID}": movie_payload(reviews={"results": []}), f"/movie/{MOVIE_ID}/reviews": reviews_en}
    )

    result = run(tool, {"operation": "movie_details", "tmdb_id": MOVIE_ID, "facets": ["reviews"]}, language="it")

    assert transport.paths == [f"/movie/{MOVIE_ID}", f"/movie/{MOVIE_ID}/reviews"]
    assert transport.params(f"/movie/{MOVIE_ID}/reviews")["language"] == "en-US"
    facets = tmdb_meta(result)["requests"][0]["entities"][f"movie:{MOVIE_ID}"]["facets"]
    assert facets["reviews"][0]["author"] == "A"


def test_language_is_part_of_the_cache_key() -> None:
    tool, transport = make_tool({f"/movie/{MOVIE_ID}": movie_payload()})
    request = {"operation": "movie_details", "tmdb_id": MOVIE_ID}

    run(tool, request, language="it")
    run(tool, request, language="it")
    run(tool, request, language="en")

    assert [call[1]["language"] for call in transport.calls] == ["it-IT", "en-US"]


def test_turn_language_is_not_part_of_the_llm_schema() -> None:
    from tool.tmdb.models.requests import TmdbToolInput

    schema = repr(TmdbToolInput.model_json_schema())
    assert "turn_language" not in schema
    tool, _ = make_tool({})
    nested = tool.run(query="q", params={"requests": [{"operation": "genres", "media": "movie", "turn_language": "it"}]})
    assert tmdb_meta(nested)["error"] == "invalid_request"
