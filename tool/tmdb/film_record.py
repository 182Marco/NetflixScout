"""Read one movie from TMDb by ID, in English, for the catalog (the vector index of plots).

The catalog stores the English overview of the movie, so this module asks for `en-US` whatever
the language of the turn and never falls back to the original language (`normalize.common.localized`
would: a Japanese film would be indexed with a Japanese plot). Missing English overview → `None`
in `overview`; the catalog then refuses the film.

The result is a plain dict whose keys are the fields of the catalog record, so the catalog does
not import this domain and this domain does not import the catalog. The call goes through the
turn's `CallBudget` and the TTL cache like any other TMDb call; the key never leaves `http.py`.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from . import endpoints
from .errors import TmdbError
from .http import get_json
from .normalize.common import clean_text, year_of
from .tool import TmdbTool

CATALOG_LANGUAGE = "en-US"
MAX_CAST = 15
MAX_ALTERNATIVE_TITLES = 40


def _names(items: Any, key: str = "name") -> tuple[str, ...]:
    if not isinstance(items, list):
        return ()
    found = (clean_text(item.get(key)) for item in items if isinstance(item, dict))
    return tuple(dict.fromkeys(name for name in found if name))


def english_overview(data: dict[str, Any]) -> str | None:
    """English overview: the `en` translation (US first); for an English original, its own overview.

    The top-level `overview` of a non-English film is never trusted: TMDb may serve the original
    language there, and a plot in another language would be indexed as if it were English.
    """
    translations = (data.get("translations") or {}).get("translations") or []
    english = [t for t in translations if isinstance(t, dict) and t.get("iso_639_1") == "en"]
    english.sort(key=lambda t: t.get("iso_3166_1") != "US")  # US first, stable otherwise
    for translation in english:
        text = clean_text((translation.get("data") or {}).get("overview"))
        if text:
            return text
    return clean_text(data.get("overview")) if data.get("original_language") == "en" else None


def release_years(data: dict[str, Any]) -> tuple[int, ...]:
    """Every release year TMDb records for the movie, primary date included."""
    years = {year_of(data.get("release_date"))}
    for country in (data.get("release_dates") or {}).get("results") or []:
        for release in (country or {}).get("release_dates") or []:
            years.add(year_of((release or {}).get("release_date")))
    return tuple(sorted(y for y in years if y is not None))


def record_from_details(data: dict[str, Any], *, fetched_ts: int) -> dict[str, Any]:
    """Fields of the catalog record from the raw `/movie/{id}` JSON (with the identity appends)."""
    cast = (data.get("credits") or {}).get("cast") or []
    ordered = sorted((c for c in cast if isinstance(c, dict)), key=lambda c: c.get("order", 10**6))
    alternatives = (data.get("alternative_titles") or {}).get("titles") or []
    return {
        "tmdb_id": int(data["id"]),
        "title": clean_text(data.get("title")) or clean_text(data.get("original_title")) or "",
        "original_title": clean_text(data.get("original_title")),
        "alternative_titles": _names(alternatives, "title")[:MAX_ALTERNATIVE_TITLES],
        "overview": english_overview(data),
        "year": year_of(data.get("release_date")),
        "release_years": release_years(data),
        "release_date": data.get("release_date") or "",
        "genres": _names(data.get("genres")),
        "cast": _names(ordered)[:MAX_CAST],
        "languages": _names(data.get("spoken_languages"), "english_name"),
        "countries": _names(data.get("production_countries")),
        "fetched_ts": int(fetched_ts),
    }


def read_film_record(
    tool: TmdbTool,
    tmdb_id: int,
    *,
    turn_id: str | None = None,
    now_ms: Callable[[], int] = lambda: int(time.time() * 1000),
) -> tuple[dict[str, Any] | None, str]:
    """`(record, "")` or `(None, reason)`; reasons are TMDb error codes, `adult` or `invalid_response`.

    Same details endpoint and appends as `movie_details` without facets: in an English turn that
    is the cached call the details operation already made, so it costs nothing.
    """
    try:
        ctx = tool.new_context(tool._credentials(), api_language=CATALOG_LANGUAGE, turn_id=turn_id)
        endpoint = endpoints.details(
            "movie", tmdb_id, language=CATALOG_LANGUAGE, appends=endpoints.MOVIE_IDENTITY_APPENDS)
        fetched = now_ms()
        data = get_json(ctx, endpoint)
    except TmdbError as exc:
        return None, exc.code
    if not isinstance(data, dict) or not isinstance(data.get("id"), int):
        return None, "invalid_response"
    if data.get("adult") is True:
        return None, "adult"
    return record_from_details(data, fetched_ts=fetched), ""
