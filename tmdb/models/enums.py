"""Closed vocabularies of the TMDb tool. Every value maps to a fixed endpoint or parameter."""
from __future__ import annotations

from enum import Enum


class TmdbOperation(str, Enum):
    search = "search"
    find_by_external_id = "find_by_external_id"
    movie_details = "movie_details"
    movie_collection = "movie_collection"
    tv_details = "tv_details"
    tv_season = "tv_season"
    tv_episode = "tv_episode"
    person_details = "person_details"
    collection_details = "collection_details"
    company_details = "company_details"
    discover_movies = "discover_movies"
    discover_tv = "discover_tv"
    trending = "trending"
    chart = "chart"
    genres = "genres"
    watch_providers_catalog = "watch_providers_catalog"
    certifications = "certifications"


class SearchKind(str, Enum):
    movie = "movie"
    tv = "tv"
    person = "person"
    collection = "collection"
    company = "company"
    keyword = "keyword"
    multi = "multi"


class MediaType(str, Enum):
    all = "all"
    movie = "movie"
    tv = "tv"
    person = "person"


class TimeWindow(str, Enum):
    day = "day"
    week = "week"


class ChartList(str, Enum):
    popular = "popular"
    top_rated = "top_rated"
    now_playing = "now_playing"
    upcoming = "upcoming"
    on_the_air = "on_the_air"
    airing_today = "airing_today"


class ExternalSource(str, Enum):
    imdb = "imdb"
    tvdb = "tvdb"
    wikidata = "wikidata"


class Department(str, Enum):
    acting = "acting"
    directing = "directing"
    writing = "writing"
    production = "production"
    camera = "camera"
    editing = "editing"
    sound = "sound"
    art = "art"
    costume_makeup = "costume_makeup"
    visual_effects = "visual_effects"
    lighting = "lighting"
    crew = "crew"


# `known_for_department` as returned by TMDb.
DEPARTMENT_NAMES = {
    Department.acting: "Acting",
    Department.directing: "Directing",
    Department.writing: "Writing",
    Department.production: "Production",
    Department.camera: "Camera",
    Department.editing: "Editing",
    Department.sound: "Sound",
    Department.art: "Art",
    Department.costume_makeup: "Costume & Make-Up",
    Department.visual_effects: "Visual Effects",
    Department.lighting: "Lighting",
    Department.crew: "Crew",
}


class Facet(str, Enum):
    """Sub-resources of a detail request, fetched with `append_to_response` when supported."""

    credits = "credits"
    aggregate_credits = "aggregate_credits"
    images = "images"
    videos = "videos"
    keywords = "keywords"
    reviews = "reviews"
    recommendations = "recommendations"
    similar = "similar"
    release_dates = "release_dates"
    content_ratings = "content_ratings"
    watch_providers = "watch_providers"
    alternative_titles = "alternative_titles"
    translations = "translations"
    external_ids = "external_ids"
    screened_theatrically = "screened_theatrically"
    combined_credits = "combined_credits"
    movie_credits = "movie_credits"
    tv_credits = "tv_credits"


class DiscoverSort(str, Enum):
    popularity_desc = "popularity_desc"
    rating_desc = "rating_desc"
    rating_asc = "rating_asc"
    votes_desc = "votes_desc"
    release_date_desc = "release_date_desc"
    release_date_asc = "release_date_asc"
    revenue_desc = "revenue_desc"


class Monetization(str, Enum):
    flatrate = "flatrate"
    free = "free"
    ads = "ads"
    rent = "rent"
    buy = "buy"


class ReleaseType(str, Enum):
    premiere = "premiere"
    theatrical_limited = "theatrical_limited"
    theatrical = "theatrical"
    digital = "digital"
    physical = "physical"
    tv = "tv"


RELEASE_TYPE_CODES = {
    ReleaseType.premiere: 1,
    ReleaseType.theatrical_limited: 2,
    ReleaseType.theatrical: 3,
    ReleaseType.digital: 4,
    ReleaseType.physical: 5,
    ReleaseType.tv: 6,
}


class TvStatus(str, Enum):
    returning_series = "returning_series"
    planned = "planned"
    in_production = "in_production"
    ended = "ended"
    canceled = "canceled"
    pilot = "pilot"


TV_STATUS_CODES = {status: code for code, status in enumerate(TvStatus)}


class TvType(str, Enum):
    documentary = "documentary"
    news = "news"
    miniseries = "miniseries"
    reality = "reality"
    scripted = "scripted"
    talk_show = "talk_show"
    video = "video"


TV_TYPE_CODES = {tv_type: code for code, tv_type in enumerate(TvType)}
