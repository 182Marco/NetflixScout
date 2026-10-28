"""«Recent» never lists films that are not out yet (live check of 2026-10-28: «five recent science-fiction films»
returned titles announced for 2028-2031). The date is the current one (injected: `tmdb_support.TODAY`); future titles
only when the user explicitly asks (`include_unreleased`)."""
from __future__ import annotations

import pytest

from tmdb_support import TODAY, make_tool, run, tmdb_meta


def _movie(n: int, release_date: str | None) -> dict:
    return {"id": n, "title": f"Film {n}", "release_date": release_date, "vote_average": 7.0, "vote_count": 500,
            "overview": "x", "genre_ids": []}


def _discover(items: list[dict]) -> dict:
    return {"results": items, "total_results": len(items), "page": 1}


def _run(filters: dict, items: list[dict] | None = None):
    tool, transport = make_tool({"/discover/movie": _discover(items or [_movie(1, "2026-01-01")])})
    result = run(tool, {"operation": "discover_movies", "filters": filters})
    return tmdb_meta(result)["requests"][0], transport.params("/discover/movie"), [c["title"] for c in result["chunks"]]


def test_a_recent_request_is_capped_at_today_even_when_the_planner_sorts_by_release_date() -> None:
    request, params, _ = _run({"year_from": 2024, "sort": "release_date_desc"})

    assert params["primary_release_date.lte"] == TODAY.isoformat() and params["primary_release_date.gte"] == "2024-01-01"
    assert request["applied_filters"]["released_up_to"] == TODAY.isoformat()


def test_without_any_date_filter_the_default_listing_is_released_titles_only_too() -> None:
    _, params, _ = _run({"genres": [], "sort": "release_date_desc"})

    assert params["primary_release_date.lte"] == TODAY.isoformat()


def test_an_explicit_request_for_unreleased_titles_has_no_upper_bound() -> None:
    request, params, titles = _run({"sort": "release_date_desc", "include_unreleased": True},
                           [_movie(1, "2031-05-01"), _movie(2, "2028-03-01")])

    assert "primary_release_date.lte" not in params
    # Upcoming titles start tomorrow (not in 1895), and an explicit year range is left alone.
    assert params["primary_release_date.gte"] == "2026-10-29"  # tomorrow: a title out today is out
    assert request["applied_filters"]["include_unreleased"] is True and "released_up_to" not in request["applied_filters"]
    assert request["applied_filters"]["released_from"] == "2026-10-29"
    _, with_years, _ = _run({"include_unreleased": True, "year_from": 2028, "year_to": 2030})
    assert with_years["primary_release_date.gte"] == "2028-01-01" and with_years["primary_release_date.lte"] == "2030-12-31"
    assert titles == ["Film 1", "Film 2"]  # future films kept: asked for


@pytest.mark.parametrize(("year_to", "expected"), [(2020, "2020-12-31"), (2026, TODAY.isoformat()), (2031, TODAY.isoformat())])
def test_an_upper_year_in_the_past_is_kept_and_one_that_reaches_the_future_is_capped(year_to, expected) -> None:
    _, params, _ = _run({"year_from": 2019, "year_to": year_to})

    assert params["primary_release_date.lte"] == expected


def test_a_future_title_that_tmdb_returns_anyway_is_dropped_and_counted() -> None:
    request, _, titles = _run({"year_from": 2024}, [_movie(1, "2025-06-01"), _movie(2, "2029-01-01"), _movie(3, TODAY.isoformat())])

    assert titles == ["Film 1", "Film 3"]  # released today counts as released
    assert "excluded_unreleased:1" in request["notes"]


def test_a_title_without_a_release_date_is_dropped_only_when_the_list_is_about_dates() -> None:
    items = [_movie(1, "2025-06-01"), _movie(2, None), _movie(3, "")]

    by_date, _, titles_by_date = _run({"year_from": 2024}, items)
    _, _, titles_by_sort = _run({"sort": "release_date_desc"}, items)
    not_about_dates, _, titles_other = _run({"sort": "rating_desc"}, items)

    assert titles_by_date == ["Film 1"] and "excluded_undated:2" in by_date["notes"]
    assert titles_by_sort == ["Film 1"]
    # A list by rating keeps an undated title (nothing says it is a recent-releases list), and says nothing is dropped.
    assert titles_other == ["Film 1", "Film 2", "Film 3"]
    assert not any(note.startswith("excluded_") for note in not_about_dates["notes"])


def test_series_use_the_first_air_date_with_the_same_bound() -> None:
    tool, transport = make_tool({"/discover/tv": {"results": [{"id": 1, "name": "S", "first_air_date": "2031-01-01"}], "total_results": 1}})
    result = run(tool, {"operation": "discover_tv", "filters": {"year_from": 2024}})

    assert transport.params("/discover/tv")["first_air_date.lte"] == TODAY.isoformat()
    assert result["chunks"] == []


def test_the_planner_schema_says_when_future_titles_may_be_asked_for() -> None:
    from tool.tmdb.models.requests import DiscoverFilters

    description = DiscoverFilters.model_fields["include_unreleased"].description
    assert "ONLY when the user explicitly asks" in description and DiscoverFilters().include_unreleased is False
