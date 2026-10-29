"""Config, input model, queries, identification and normalization of the TVmaze tool (offline, pure)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from tool.tvmaze.config import TvmazeConfig, load_tvmaze_config
from tool.tvmaze.identify import AMBIGUOUS, IDENTIFIED, NOT_FOUND, UNVERIFIED, identify, normalize_title
from tool.tvmaze.models import TvmazeToolInput, describe_validation_errors
from tool.tvmaze.normalize import cast_rows, episode_rows, plain_text, season_rows, show_info, show_url
from tool.tvmaze.queries import episodes_request, search_request, seasons_request, show_request
from tvmaze_support import episode, search, show


def test_config_rejects_missing_extra_and_out_of_range_values() -> None:
    assert load_tvmaze_config({"max_calls_per_turn": 6}).max_calls_per_turn == 6
    for bad in ({}, {"max_calls_per_turn": 6, "cache_ttl": 1}, {"max_calls_per_turn": 0}, {"max_calls_per_turn": 11}):
        with pytest.raises(ValidationError):
            TvmazeConfig.model_validate(bad)


def test_input_needs_season_for_episodes_and_dedups_facets() -> None:
    ok = TvmazeToolInput.model_validate({"query": "q", "title": "  Sample   Show ", "facets": ["cast", "cast"]})
    assert ok.title == "Sample Show" and ok.facets == ["cast"]
    with pytest.raises(ValidationError):
        TvmazeToolInput.model_validate({"query": "q", "title": "x", "facets": ["episodes"]})
    with pytest.raises(ValidationError):
        TvmazeToolInput.model_validate({"query": "q", "title": "x", "episode": 2})
    with pytest.raises(ValidationError):
        TvmazeToolInput.model_validate({"query": "q", "title": "x", "unknown": 1})


def test_validation_errors_never_report_values() -> None:
    with pytest.raises(ValidationError) as caught:
        TvmazeToolInput.model_validate({"query": "q", "title": "secret-title", "facets": ["nope"], "extra": "secret"})
    rows = describe_validation_errors(caught.value)
    assert "secret" not in str(rows) and {"field": "unknown_field", "error": "extra_forbidden"} in rows


def test_requests_are_constant_paths_with_documented_embeds() -> None:
    assert search_request("The Bear") == ("/search/shows", (("q", "The Bear"),))
    assert show_request(7, cast=True, next_episode=True) == ("/shows/7", (("embed[]", "cast"), ("embed[]", "nextepisode")))
    assert show_request(7, cast=False, next_episode=True)[1] == (("embed[]", "nextepisode"),)
    assert seasons_request(7) == ("/shows/7/seasons", ())
    assert episodes_request(7) == ("/shows/7/episodes", (("specials", "1"),))


def test_identify_requires_the_exact_title_and_keeps_the_article() -> None:
    assert normalize_title("The  Bear!") == "the bear" != normalize_title("Bear")
    assert identify(search(show(1, "The Bear")), title="the bear", year=None).status == IDENTIFIED
    assert identify(search(show(1, "The Bear")), title="Bear", year=None).status == UNVERIFIED
    assert identify([], title="x", year=None).status == NOT_FOUND
    assert identify(None, title="x", year=None).status == NOT_FOUND


def test_identify_uses_the_premiere_year_to_tell_remakes_apart() -> None:
    results = search(show(1, "The Office", "2005-03-24"), show(2, "The Office", "2001-07-09"))
    assert identify(results, title="The Office", year=None).status == AMBIGUOUS
    found = identify(results, title="The Office", year=2001)
    assert found.status == IDENTIFIED and found.show["id"] == 2
    assert identify(results, title="The Office", year=1999).status == UNVERIFIED


def test_normalization_strips_html_and_never_reads_episode_summaries() -> None:
    info = show_info(show())
    assert info["summary"] == "A sample premise & more."
    assert info["network"] == "Sample Net" and info["imdb_id"] == "tt1000001" and info["runtime_minutes"] == 60
    assert plain_text("<p>" + "x" * 900 + "</p>").endswith("…")
    rows, total = episode_rows([episode(1, 1), episode(1, 2), episode(2, 1)], season=1, episode=None)
    assert total == 2 and all("summary" not in row for row in rows)
    assert episode_rows([episode(1, 1), episode(1, 2)], season=1, episode=2)[0][0]["number"] == 2
    assert season_rows([{"number": 1, "episodeOrder": 10, "premiereDate": "2016-07-15", "endDate": None}])[0]["episodes"] == 10
    assert cast_rows([{"person": {"name": "A"}, "character": {"name": "B"}}, "junk"]) == [{"person": "A", "character": "B"}]


def test_only_tvmaze_pages_are_offered_as_links() -> None:
    assert show_url(show()) == "https://www.tvmaze.com/shows/1/sample-show"
    assert show_url({"url": "https://evil.example/x"}) is None
