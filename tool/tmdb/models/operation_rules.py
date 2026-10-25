"""Per-operation rules: required fields, allowed fields, facets and media.

One table drives both the validation in `requests.py` and the operation guide in the
tool description, so the planner prompt and the validator cannot drift apart.
"""
from __future__ import annotations

from dataclasses import dataclass

from .enums import ChartList, ExternalSource, Facet, MediaType, TmdbOperation

_TARGET = ("tmdb_id", "external_id", "external_source", "title", "year")
_PERSON_TARGET = ("tmdb_id", "external_id", "external_source", "name", "department")

MOVIE_FACETS = (
    Facet.credits,
    Facet.images,
    Facet.videos,
    Facet.keywords,
    Facet.reviews,
    Facet.recommendations,
    Facet.similar,
    Facet.release_dates,
    Facet.watch_providers,
    Facet.alternative_titles,
    Facet.translations,
    Facet.external_ids,
)
TV_FACETS = (
    Facet.aggregate_credits,
    Facet.credits,
    Facet.images,
    Facet.videos,
    Facet.keywords,
    Facet.reviews,
    Facet.recommendations,
    Facet.similar,
    Facet.content_ratings,
    Facet.watch_providers,
    Facet.alternative_titles,
    Facet.translations,
    Facet.external_ids,
    Facet.screened_theatrically,
)
SEASON_FACETS = (
    Facet.aggregate_credits,
    Facet.credits,
    Facet.images,
    Facet.videos,
    Facet.watch_providers,
    Facet.external_ids,
    Facet.translations,
)
EPISODE_FACETS = (Facet.credits, Facet.images, Facet.videos, Facet.external_ids, Facet.translations)
PERSON_FACETS = (
    Facet.combined_credits,
    Facet.movie_credits,
    Facet.tv_credits,
    Facet.images,
    Facet.external_ids,
    Facet.translations,
)
COLLECTION_FACETS = (Facet.images, Facet.translations)

CHART_LISTS = {
    MediaType.movie: (ChartList.popular, ChartList.top_rated, ChartList.now_playing, ChartList.upcoming),
    MediaType.tv: (ChartList.popular, ChartList.top_rated, ChartList.on_the_air, ChartList.airing_today),
    MediaType.person: (ChartList.popular,),
}

# IMDb IDs are tt… for titles and nm… for people.
EXTERNAL_ID_PATTERNS = {
    ExternalSource.imdb: r"^(tt|nm)\d{7,10}$",
    ExternalSource.tvdb: r"^\d{1,10}$",
    ExternalSource.wikidata: r"^Q\d{1,12}$",
}


@dataclass(frozen=True)
class OperationRule:
    summary: str
    # Each group needs at least one of its fields.
    required: tuple[tuple[str, ...], ...] = ()
    fields: tuple[str, ...] = ()
    facets: tuple[Facet, ...] = ()
    media: tuple[MediaType, ...] = ()

    @property
    def allowed(self) -> frozenset[str]:
        return frozenset(self.fields) | {field for group in self.required for field in group}


RULES: dict[TmdbOperation, OperationRule] = {
    TmdbOperation.search: OperationRule(
        "Text search (original, translated and alternative titles); returns a list.",
        required=(("kind",), ("search_query",)),
        fields=("kind", "search_query", "year", "limit"),
    ),
    TmdbOperation.find_by_external_id: OperationRule(
        "Find a movie, series or person by IMDb, TVDB or Wikidata ID.",
        required=(("external_id",), ("external_source",)),
    ),
    TmdbOperation.movie_details: OperationRule(
        "Movie details (title, overview, director, main cast); facets come in the same call.",
        required=(("tmdb_id", "external_id", "title"),),
        fields=(*_TARGET, "facets", "region"),
        facets=MOVIE_FACETS,
    ),
    TmdbOperation.movie_collection: OperationRule(
        "The collection (saga) a movie belongs to, with all its parts.",
        required=(("tmdb_id", "external_id", "title"),),
        fields=_TARGET,
    ),
    TmdbOperation.tv_details: OperationRule(
        "TV series details (seasons, creators, networks); facets come in the same call.",
        required=(("tmdb_id", "external_id", "title"),),
        fields=(*_TARGET, "facets", "region"),
        facets=TV_FACETS,
    ),
    TmdbOperation.tv_season: OperationRule(
        "One season of a series (season 0 = specials) with its episodes.",
        required=(("tmdb_id", "external_id", "title"), ("season",)),
        fields=(*_TARGET, "season", "facets", "region"),
        facets=SEASON_FACETS,
    ),
    TmdbOperation.tv_episode: OperationRule(
        "One episode of a series.",
        required=(("tmdb_id", "external_id", "title"), ("season",), ("episode",)),
        fields=(*_TARGET, "season", "episode", "facets"),
        facets=EPISODE_FACETS,
    ),
    TmdbOperation.person_details: OperationRule(
        "Person details (biography); add credits facets for the filmography.",
        required=(("tmdb_id", "external_id", "name"),),
        fields=(*_PERSON_TARGET, "facets"),
        facets=PERSON_FACETS,
    ),
    TmdbOperation.collection_details: OperationRule(
        "A collection (saga) by name or ID, with all its parts.",
        required=(("tmdb_id", "name"),),
        fields=("tmdb_id", "name", "facets"),
        facets=COLLECTION_FACETS,
    ),
    TmdbOperation.company_details: OperationRule(
        "A production company by name or ID.",
        required=(("tmdb_id", "name"),),
        fields=("tmdb_id", "name"),
    ),
    TmdbOperation.discover_movies: OperationRule(
        "Movies matching filters (genres, years, cast, people, companies, keywords, ratings, providers). "
        "Ratings are TMDb user votes, not critics' reviews.",
        fields=("filters", "limit"),
    ),
    TmdbOperation.discover_tv: OperationRule(
        "Series matching filters (genres, years, companies, keywords, ratings, providers, status).",
        fields=("filters", "limit"),
    ),
    TmdbOperation.trending: OperationRule(
        "Trending titles or people today or this week.",
        required=(("media",), ("window",)),
        fields=("limit",),
        media=(MediaType.all, MediaType.movie, MediaType.tv, MediaType.person),
    ),
    TmdbOperation.chart: OperationRule(
        "Current lists: movie popular/top_rated/now_playing/upcoming, "
        "tv popular/top_rated/on_the_air/airing_today, person popular.",
        required=(("media",), ("chart",)),
        fields=("region", "limit"),
        media=(MediaType.movie, MediaType.tv, MediaType.person),
    ),
    TmdbOperation.genres: OperationRule(
        "Official genre list for movies or series.",
        required=(("media",),),
        media=(MediaType.movie, MediaType.tv),
    ),
    TmdbOperation.watch_providers_catalog: OperationRule(
        "Streaming services available in a country.",
        required=(("media",),),
        fields=("region", "limit"),
        media=(MediaType.movie, MediaType.tv),
    ),
    TmdbOperation.certifications: OperationRule(
        "Age ratings (certifications) of a country and their meaning.",
        required=(("media",),),
        fields=("region",),
        media=(MediaType.movie, MediaType.tv),
    ),
}

MOVIE_ONLY_FILTERS = frozenset({"people", "cast", "certification", "certification_country", "release_types", "region"})
TV_ONLY_FILTERS = frozenset({"tv_status", "tv_type"})


def describe_operations() -> str:
    """Compact operation guide for the planner, generated from `RULES`."""
    lines = []
    for operation, rule in RULES.items():
        parts = [f"{operation.value}: {rule.summary}"]
        if rule.required:
            parts.append("required: " + "; ".join(" or ".join(group) for group in rule.required))
        optional = [field for field in rule.fields if field not in {f for g in rule.required for f in g}]
        if optional:
            parts.append("optional: " + ", ".join(optional))
        if rule.facets:
            parts.append("facets: " + ", ".join(facet.value for facet in rule.facets))
        if rule.media:
            parts.append("media: " + ", ".join(media.value for media in rule.media))
        lines.append("- " + " | ".join(parts))
    return "\n".join(lines)
