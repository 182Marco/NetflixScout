"""Facet normalizers with fixed per-list caps (prompt size, not HTTP limits).

Each builder returns {list name: (items, total before the cap)}, so the packer can tell
the model how much was left out. Lists of titles (recommendations, similar) use
`max_results`; the other caps are internal constants.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..endpoints import APPEND_KEYS
from ..models.enums import Facet
from .common import clean_text, image_url, names, truncate, year_of

TOP_CAST = 5
CAST_CAP = 15
CREW_CAP = 10
KEY_CREW_JOBS = (
    "Director",
    "Screenplay",
    "Writer",
    "Novel",
    "Producer",
    "Original Music Composer",
    "Director of Photography",
    "Editor",
)
VIDEOS_CAP = 5
REVIEWS_CAP = 3
REVIEW_CHARS = 500
IMAGES_PER_TYPE = 3
KEYWORDS_CAP = 20
COUNTRY_ROWS_CAP = 10
TRANSLATIONS_CAP = 5
TRANSLATION_OVERVIEW_CHARS = 200
EPISODES_CAP = 30
PARTS_CAP = 20
PERSON_CREDITS_CAP = 20
SCREENED_CAP = 20
PROVIDER_NAMES_CAP = 10

RELEASE_TYPE_NAMES = {1: "premiere", 2: "theatrical_limited", 3: "theatrical", 4: "digital", 5: "physical", 6: "tv"}
_VIDEO_SITES = {"YouTube": "https://www.youtube.com/watch?v={}", "Vimeo": "https://vimeo.com/{}"}
_IMAGE_TYPES = ("posters", "backdrops", "logos", "profiles", "stills")
_EXTERNAL_ID_KEYS = ("imdb_id", "tvdb_id", "wikidata_id", "facebook_id", "instagram_id", "twitter_id")

Capped = tuple[list[Any], int]
Lists = dict[str, Capped]


def _results(section: Any, key: str = "results") -> list[dict[str, Any]]:
    if not isinstance(section, dict):
        return []
    return [item for item in section.get(key) or [] if isinstance(item, dict)]


def top_cast(credits: Any, limit: int = TOP_CAST) -> list[str]:
    cast = sorted(_results(credits, "cast"), key=lambda person: person.get("order", 999))
    return names(cast, limit=limit)


def people_with_job(credits: Any, job: str) -> list[str]:
    return names([person for person in _results(credits, "crew") if person.get("job") == job])


def _cast(credits: Any) -> Capped:
    cast = sorted(_results(credits, "cast"), key=lambda person: person.get("order", 999))
    rows = [{"name": clean_text(p.get("name")), "character": clean_text(p.get("character"))} for p in cast]
    return rows[:CAST_CAP], len(rows)


def _crew(credits: Any) -> Capped:
    crew = [p for p in _results(credits, "crew") if p.get("job") in KEY_CREW_JOBS]
    crew.sort(key=lambda person: KEY_CREW_JOBS.index(person["job"]))
    rows = [{"name": clean_text(p.get("name")), "job": p["job"]} for p in crew]
    return rows[:CREW_CAP], len(rows)


def credits(section: Any, **_: Any) -> Lists:
    return {"cast": _cast(section), "crew": _crew(section)}


def aggregate_credits(section: Any, **_: Any) -> Lists:
    cast = sorted(_results(section, "cast"), key=lambda person: person.get("order", 999))
    rows = [
        {
            "name": clean_text(p.get("name")),
            "character": " / ".join(names(p.get("roles"), "character", limit=2)) or None,
            "episodes": p.get("total_episode_count"),
        }
        for p in cast
    ]
    return {"cast": (rows[:CAST_CAP], len(rows))}


def videos(section: Any, **_: Any) -> Lists:
    usable = [v for v in _results(section) if v.get("site") in _VIDEO_SITES and v.get("key")]
    usable.sort(key=lambda v: (not v.get("official"), v.get("type") not in ("Trailer", "Teaser")))
    rows = [
        {
            "name": clean_text(v.get("name")),
            "type": v.get("type"),
            "language": v.get("iso_639_1"),
            "url": _VIDEO_SITES[v["site"]].format(v["key"]),
        }
        for v in usable
    ]
    return {"videos": (rows[:VIDEOS_CAP], len(rows))}


def reviews(section: Any, **_: Any) -> Lists:
    rows = [
        {
            "author": clean_text(r.get("author")),
            "rating": (r.get("author_details") or {}).get("rating"),
            "date": (r.get("created_at") or "")[:10] or None,
            "content": truncate(clean_text(r.get("content")), REVIEW_CHARS),
            "url": r.get("url"),
        }
        for r in _results(section)
    ]
    return {"reviews": (rows[:REVIEWS_CAP], len(rows))}


def images(section: Any, **_: Any) -> Lists:
    if not isinstance(section, dict):
        return {}
    rows: list[dict[str, Any]] = []
    total = 0
    for image_type in _IMAGE_TYPES:
        items = [item for item in section.get(image_type) or [] if isinstance(item, dict)]
        total += len(items)
        for item in items[:IMAGES_PER_TYPE]:
            url = image_url(item.get("file_path"))
            if url:
                rows.append({"type": image_type[:-1], "language": item.get("iso_639_1"), "url": url})
    return {"images": (rows, total)}


def keywords(section: Any, **_: Any) -> Lists:
    # Movies use "keywords", series use "results".
    items = _results(section, "keywords") or _results(section)
    rows = names(items)
    return {"keywords": (rows[:KEYWORDS_CAP], len(rows))}


def release_dates(section: Any, *, countries: tuple[str, ...], **_: Any) -> Lists:
    rows: list[dict[str, Any]] = []
    total = 0
    for country in _results(section):
        dates = country.get("release_dates") or []
        total += len(dates)
        if country.get("iso_3166_1") not in countries:
            continue
        for date in dates:
            rows.append(
                {
                    "country": country["iso_3166_1"],
                    "date": (date.get("release_date") or "")[:10] or None,
                    "type": RELEASE_TYPE_NAMES.get(date.get("type")),
                    "certification": clean_text(date.get("certification")),
                }
            )
    return {"release_dates": (rows[:COUNTRY_ROWS_CAP], total)}


def content_ratings(section: Any, *, countries: tuple[str, ...], **_: Any) -> Lists:
    items = _results(section)
    rows = [
        {"country": item["iso_3166_1"], "rating": clean_text(item.get("rating"))}
        for item in items
        if item.get("iso_3166_1") in countries
    ]
    return {"content_ratings": (rows[:COUNTRY_ROWS_CAP], len(items))}


def alternative_titles(section: Any, *, countries: tuple[str, ...], **_: Any) -> Lists:
    # Movies use "titles", series use "results".
    items = _results(section, "titles") or _results(section)
    rows = [
        {"country": item.get("iso_3166_1"), "title": clean_text(item.get("title")), "type": clean_text(item.get("type"))}
        for item in items
        if item.get("iso_3166_1") in countries
    ]
    return {"alternative_titles": (rows[:COUNTRY_ROWS_CAP], len(items))}


def translations(section: Any, *, languages: tuple[str, ...], **_: Any) -> Lists:
    items = _results(section, "translations")
    rows = []
    for item in items:
        if item.get("iso_639_1") not in languages:
            continue
        data = item.get("data") or {}
        rows.append(
            {
                "language": f"{item.get('iso_639_1')}-{item.get('iso_3166_1')}",
                "title": clean_text(data.get("title") or data.get("name")),
                "overview": truncate(clean_text(data.get("overview") or data.get("biography")), TRANSLATION_OVERVIEW_CHARS),
            }
        )
    return {"translations": (rows[:TRANSLATIONS_CAP], len(items))}


def external_ids(section: Any, **_: Any) -> Lists:
    if not isinstance(section, dict):
        return {}
    ids = {key: section[key] for key in _EXTERNAL_ID_KEYS if section.get(key)}
    return {"external_ids": ([ids], 1)} if ids else {}


def related_titles(name: str) -> Callable[..., Lists]:
    def build(section: Any, *, limit: int, **_: Any) -> Lists:
        items = _results(section)
        rows = [
            {
                "tmdb_id": item.get("id"),
                "title": clean_text(item.get("title") or item.get("name")),
                "year": year_of(item.get("release_date") or item.get("first_air_date")),
                "score": item.get("vote_average"),
            }
            for item in items
        ]
        return {name: (rows[:limit], len(items))}

    return build


def person_credits(name: str) -> Callable[..., Lists]:
    def build(section: Any, **_: Any) -> Lists:
        rows = []
        for credit in [*_results(section, "cast"), *_results(section, "crew")]:
            rows.append(
                {
                    "title": clean_text(credit.get("title") or credit.get("name")),
                    "year": year_of(credit.get("release_date") or credit.get("first_air_date")),
                    "media": credit.get("media_type"),
                    "role": clean_text(credit.get("character") or credit.get("job")),
                    "popularity": credit.get("popularity") or 0,
                }
            )
        rows.sort(key=lambda row: row["popularity"], reverse=True)
        for row in rows:
            del row["popularity"]
        return {name: (rows[:PERSON_CREDITS_CAP], len(rows))}

    return build


def screened_theatrically(section: Any, **_: Any) -> Lists:
    rows = [{"season": item.get("season_number"), "episode": item.get("episode_number")} for item in _results(section)]
    return {"screened_theatrically": (rows[:SCREENED_CAP], len(rows))}


def episodes(season: dict[str, Any]) -> Capped:
    items = [item for item in season.get("episodes") or [] if isinstance(item, dict)]
    rows = [
        {"episode": item.get("episode_number"), "title": clean_text(item.get("name")), "air_date": item.get("air_date")}
        for item in items
    ]
    return rows[:EPISODES_CAP], len(rows)


def parts(collection: dict[str, Any]) -> Capped:
    items = [item for item in collection.get("parts") or [] if isinstance(item, dict)]
    items.sort(key=lambda item: item.get("release_date") or "9999")
    rows = [
        {"tmdb_id": item.get("id"), "title": clean_text(item.get("title")), "year": year_of(item.get("release_date"))}
        for item in items
    ]
    return rows[:PARTS_CAP], len(rows)


def watch_providers(section: Any, region: str) -> dict[str, Any]:
    """Offers for one country. P1 data: its presence triggers the JustWatch attribution."""
    offers = ((section or {}).get("results") or {}).get(region) if isinstance(section, dict) else None
    if not isinstance(offers, dict):
        return {"region": region, "available": False}
    result: dict[str, Any] = {"region": region, "link": offers.get("link")}
    for offer_type in ("flatrate", "free", "ads", "rent", "buy"):
        provider_names = names(offers.get(offer_type), "provider_name", limit=PROVIDER_NAMES_CAP)
        if provider_names:
            result[offer_type] = provider_names
    result["available"] = any(key in result for key in ("flatrate", "free", "ads", "rent", "buy"))
    return result


FACET_BUILDERS: dict[Facet, Callable[..., Lists]] = {
    Facet.credits: credits,
    Facet.aggregate_credits: aggregate_credits,
    Facet.images: images,
    Facet.videos: videos,
    Facet.keywords: keywords,
    Facet.reviews: reviews,
    Facet.recommendations: related_titles("recommendations"),
    Facet.similar: related_titles("similar"),
    Facet.release_dates: release_dates,
    Facet.content_ratings: content_ratings,
    Facet.alternative_titles: alternative_titles,
    Facet.translations: translations,
    Facet.external_ids: external_ids,
    Facet.screened_theatrically: screened_theatrically,
    Facet.combined_credits: person_credits("combined_credits"),
    Facet.movie_credits: person_credits("movie_credits"),
    Facet.tv_credits: person_credits("tv_credits"),
}


def collect_facets(
    data: dict[str, Any],
    facets: list[Facet],
    *,
    countries: tuple[str, ...],
    languages: tuple[str, ...],
    limit: int,
) -> Lists:
    """Normalize the requested facets found in `data` (watch providers are P1, handled apart)."""
    lists: Lists = {}
    for facet in facets:
        if facet is Facet.watch_providers:
            continue
        section = data.get(APPEND_KEYS[facet])
        if section is None:
            continue
        lists.update(FACET_BUILDERS[facet](section, countries=countries, languages=languages, limit=limit))
    return lists
