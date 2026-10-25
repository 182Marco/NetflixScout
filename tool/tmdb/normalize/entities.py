"""Raw TMDb objects → `Entity`: identity (P0), essentials (P1), capped facets (P2)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..models.enums import Facet
from ..models.results import Entity
from ..settings import TMDB_WEB_URL
from . import facets as facet_lists
from .common import clean_text, image_url, language_code, localized, names, positive_minutes, truncate, year_of

SUMMARY_CHARS = 280
OVERVIEW_CHARS = 500
TAGLINE_CHARS = 150


@dataclass(frozen=True)
class FacetOptions:
    """What the facet builders need besides the raw data."""

    facets: tuple[Facet, ...]
    region: str
    api_language: str
    limit: int


def _countries(data: dict[str, Any], region: str) -> tuple[str, ...]:
    origin = [c.get("iso_3166_1") for c in data.get("production_countries") or [] if isinstance(c, dict)]
    origin += [c for c in data.get("origin_country") or [] if isinstance(c, str)]
    return tuple(dict.fromkeys([region, *origin]))


def _languages(api_language: str, original_language: str | None) -> tuple[str, ...]:
    return tuple(code for code in dict.fromkeys([language_code(api_language), "en", original_language]) if code)


def _with_facets(entity: Entity, data: dict[str, Any], options: FacetOptions) -> Entity:
    lists = facet_lists.collect_facets(
        data,
        list(options.facets),
        countries=_countries(data, options.region),
        languages=_languages(options.api_language, entity.original_language),
        limit=options.limit,
    )
    for name, (items, total) in lists.items():
        entity.facets[name] = items
        entity.facet_totals[name] = total
    if Facet.watch_providers in options.facets:
        entity.essentials["watch_providers"] = facet_lists.watch_providers(data.get("watch/providers"), options.region)
    return entity


def _text(data: dict[str, Any], field: str, options: FacetOptions, original_language: str | None) -> dict[str, Any]:
    """`{field: text}` plus `{field}_language` when the text is a fallback translation."""
    value, fallback = localized(data, field, api_language=options.api_language, original_language=original_language)
    result: dict[str, Any] = {field: truncate(value, OVERVIEW_CHARS)} if value else {}
    if value and fallback:
        result[f"{field}_language"] = fallback
    return result


def _vote(data: dict[str, Any]) -> dict[str, Any]:
    if not data.get("vote_count"):
        return {}
    return {"vote_average": data.get("vote_average"), "vote_count": data.get("vote_count")}


def _compact(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value not in (None, "", [], {})}


def movie(data: dict[str, Any], options: FacetOptions) -> Entity:
    original_language = data.get("original_language")
    title, _ = localized(data, "title", api_language=options.api_language, original_language=original_language)
    overview = _text(data, "overview", options, original_language)
    credits = data.get("credits")
    collection = data.get("belongs_to_collection") or {}
    entity = Entity(
        kind="movie",
        tmdb_id=data["id"],
        title=title or clean_text(data.get("original_title")) or "?",
        original_title=clean_text(data.get("original_title")),
        original_language=original_language,
        year=year_of(data.get("release_date")),
        imdb_id=data.get("imdb_id") or None,
        summary=truncate(overview.get("overview"), SUMMARY_CHARS),
        genres=names(data.get("genres")),
        score=data.get("vote_average"),
        release_date=data.get("release_date") or None,
        poster_path=data.get("poster_path") or None,
        essentials=_compact(
            {
                **overview,
                "tagline": truncate(clean_text(data.get("tagline")), TAGLINE_CHARS),
                "release_date": data.get("release_date"),
                "runtime_minutes": positive_minutes(data.get("runtime")),
                "status": data.get("status"),
                "genres": names(data.get("genres")),
                **_vote(data),
                "directors": facet_lists.people_with_job(credits, "Director"),
                "top_cast": facet_lists.top_cast(credits),
                "collection": clean_text(collection.get("name")),
                "poster_url": image_url(data.get("poster_path")),
                "tmdb_url": f"{TMDB_WEB_URL}/movie/{data['id']}",
            }
        ),
    )
    return _with_facets(entity, data, options)


def tv(data: dict[str, Any], options: FacetOptions) -> Entity:
    original_language = data.get("original_language")
    title, _ = localized(data, "name", api_language=options.api_language, original_language=original_language)
    overview = _text(data, "overview", options, original_language)
    external = data.get("external_ids") or {}
    entity = Entity(
        kind="tv",
        tmdb_id=data["id"],
        title=title or clean_text(data.get("original_name")) or "?",
        original_title=clean_text(data.get("original_name")),
        original_language=original_language,
        year=year_of(data.get("first_air_date")),
        imdb_id=external.get("imdb_id") or None,
        summary=truncate(overview.get("overview"), SUMMARY_CHARS),
        genres=names(data.get("genres")),
        score=data.get("vote_average"),
        release_date=data.get("first_air_date") or None,
        poster_path=data.get("poster_path") or None,
        essentials=_compact(
            {
                **overview,
                "first_air_date": data.get("first_air_date"),
                "last_air_date": data.get("last_air_date"),
                "status": data.get("status"),
                "in_production": data.get("in_production"),
                "seasons": data.get("number_of_seasons"),
                "episodes": data.get("number_of_episodes"),
                # Series have no runtime or director of their own: only what TMDb lists here.
                "episode_runtime_minutes": [
                    minutes for minutes in map(positive_minutes, data.get("episode_run_time") or []) if minutes
                ],
                "genres": names(data.get("genres")),
                **_vote(data),
                "created_by": names(data.get("created_by")),
                "networks": names(data.get("networks")),
                "top_cast": facet_lists.top_cast(data.get("credits")),
                "poster_url": image_url(data.get("poster_path")),
                "tmdb_url": f"{TMDB_WEB_URL}/tv/{data['id']}",
            }
        ),
    )
    return _with_facets(entity, data, options)


def season(data: dict[str, Any], options: FacetOptions, *, series_id: int, series_title: str | None) -> Entity:
    overview = _text(data, "overview", options, None)
    season_name = clean_text(data.get("name")) or f"Season {data.get('season_number')}"
    episode_rows, episode_total = facet_lists.episodes(data)
    entity = Entity(
        kind="season",
        tmdb_id=data["id"],
        title=f"{series_title} — {season_name}" if series_title else season_name,
        year=year_of(data.get("air_date")),
        summary=truncate(overview.get("overview"), SUMMARY_CHARS),
        score=data.get("vote_average") or None,
        essentials=_compact(
            {
                **overview,
                "series_tmdb_id": series_id,
                "season_number": data.get("season_number"),
                "air_date": data.get("air_date"),
                "episode_count": episode_total,
                "poster_url": image_url(data.get("poster_path")),
                "tmdb_url": f"{TMDB_WEB_URL}/tv/{series_id}/season/{data.get('season_number')}",
            }
        ),
        facets={"episodes": episode_rows},
        facet_totals={"episodes": episode_total},
    )
    return _with_facets(entity, data, options)


def episode(data: dict[str, Any], options: FacetOptions, *, series_id: int, series_title: str | None) -> Entity:
    overview = _text(data, "overview", options, None)
    label = f"S{data.get('season_number')}E{data.get('episode_number')}"
    name = clean_text(data.get("name")) or label
    entity = Entity(
        kind="episode",
        tmdb_id=data["id"],
        title=f"{series_title} — {label} {name}" if series_title else f"{label} {name}",
        year=year_of(data.get("air_date")),
        summary=truncate(overview.get("overview"), SUMMARY_CHARS),
        score=data.get("vote_average") or None,
        essentials=_compact(
            {
                **overview,
                "series_tmdb_id": series_id,
                "season_number": data.get("season_number"),
                "episode_number": data.get("episode_number"),
                "air_date": data.get("air_date"),
                "runtime_minutes": positive_minutes(data.get("runtime")),
                **_vote(data),
                "directors": names([p for p in data.get("crew") or [] if p.get("job") == "Director"]),
                "guest_stars": names(data.get("guest_stars"), limit=facet_lists.TOP_CAST),
                "still_url": image_url(data.get("still_path")),
            }
        ),
    )
    return _with_facets(entity, data, options)


def person(data: dict[str, Any], options: FacetOptions) -> Entity:
    biography = _text(data, "biography", options, None)
    entity = Entity(
        kind="person",
        tmdb_id=data["id"],
        title=clean_text(data.get("name")) or "?",
        imdb_id=data.get("imdb_id") or None,
        summary=truncate(biography.get("biography"), SUMMARY_CHARS),
        essentials=_compact(
            {
                **biography,
                "known_for_department": data.get("known_for_department"),
                "birthday": data.get("birthday"),
                "deathday": data.get("deathday"),
                "place_of_birth": clean_text(data.get("place_of_birth")),
                "also_known_as": [clean_text(n) for n in (data.get("also_known_as") or [])[:3]],
                "profile_url": image_url(data.get("profile_path")),
                "tmdb_url": f"{TMDB_WEB_URL}/person/{data['id']}",
            }
        ),
    )
    return _with_facets(entity, data, options)


def collection(data: dict[str, Any], options: FacetOptions, extra: dict[str, Any] | None = None) -> Entity:
    # Collections do not support append_to_response: images/translations come separately.
    data = {**data, **(extra or {})}
    overview = _text(data, "overview", options, None)
    part_rows, part_total = facet_lists.parts(data)
    entity = Entity(
        kind="collection",
        tmdb_id=data["id"],
        title=clean_text(data.get("name")) or "?",
        original_title=clean_text(data.get("original_name")),
        summary=truncate(overview.get("overview"), SUMMARY_CHARS),
        essentials=_compact(
            {
                **overview,
                "parts_count": part_total,
                "poster_url": image_url(data.get("poster_path")),
                "tmdb_url": f"{TMDB_WEB_URL}/collection/{data['id']}",
            }
        ),
        facets={"parts": part_rows},
        facet_totals={"parts": part_total},
    )
    return _with_facets(entity, data, options)


def company(data: dict[str, Any]) -> Entity:
    parent = data.get("parent_company") or {}
    return Entity(
        kind="company",
        tmdb_id=data["id"],
        title=clean_text(data.get("name")) or "?",
        summary=truncate(clean_text(data.get("description")), SUMMARY_CHARS),
        essentials=_compact(
            {
                "origin_country": data.get("origin_country"),
                "headquarters": clean_text(data.get("headquarters")),
                "parent_company": clean_text(parent.get("name")) if isinstance(parent, dict) else None,
                "homepage": data.get("homepage"),
                "logo_url": image_url(data.get("logo_path")),
                "tmdb_url": f"{TMDB_WEB_URL}/company/{data['id']}",
            }
        ),
    )


_LIST_KINDS = {"movie", "tv", "person", "collection", "company", "keyword"}


def list_item(raw: dict[str, Any], *, kind: str, genre_names: dict[int, str]) -> Entity | None:
    """One result of a search/discover/trending/chart list (kind from `media_type` if present)."""
    kind = raw.get("media_type") or kind
    if kind not in _LIST_KINDS or not isinstance(raw.get("id"), int):
        return None
    title = clean_text(raw.get("title") or raw.get("name")) or "?"
    original = clean_text(raw.get("original_title") or raw.get("original_name"))
    summary = truncate(clean_text(raw.get("overview")), SUMMARY_CHARS)
    if kind == "person":
        known_for = names(raw.get("known_for"), "title", limit=3) or names(raw.get("known_for"), "name", limit=3)
        details = [raw.get("known_for_department"), ("noto per: " + ", ".join(known_for)) if known_for else None]
        summary = " · ".join(part for part in details if part) or None
    return Entity(
        kind=kind,
        tmdb_id=raw["id"],
        title=title,
        original_title=original if original != title else None,
        original_language=raw.get("original_language"),
        year=year_of(raw.get("release_date") or raw.get("first_air_date")),
        summary=summary,
        genres=[genre_names[g] for g in raw.get("genre_ids") or [] if g in genre_names],
        score=raw.get("vote_average") if raw.get("vote_count") else None,
        release_date=raw.get("release_date") or raw.get("first_air_date") or None,
        poster_path=raw.get("poster_path") or None,
    )
