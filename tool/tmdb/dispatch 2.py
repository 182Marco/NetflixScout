"""Deterministic operation → handler table."""
from __future__ import annotations

from collections.abc import Callable

from .context import TmdbContext
from .models.enums import TmdbOperation
from .models.requests import TmdbRequest
from .models.results import RequestOutcome
from .operations import collections, discovery, lists, movies, people, reference, resolve, tv

Handler = Callable[[TmdbContext, TmdbRequest], RequestOutcome]

OPERATION_HANDLERS: dict[TmdbOperation, Handler] = {
    TmdbOperation.search: resolve.search_operation,
    TmdbOperation.find_by_external_id: resolve.find_operation,
    TmdbOperation.movie_details: movies.movie_details,
    TmdbOperation.movie_collection: movies.movie_collection,
    TmdbOperation.tv_details: tv.tv_details,
    TmdbOperation.tv_season: tv.tv_season,
    TmdbOperation.tv_episode: tv.tv_episode,
    TmdbOperation.person_details: people.person_details,
    TmdbOperation.collection_details: collections.collection_details,
    TmdbOperation.company_details: collections.company_details,
    TmdbOperation.discover_movies: discovery.discover_movies,
    TmdbOperation.discover_tv: discovery.discover_tv,
    TmdbOperation.trending: lists.trending,
    TmdbOperation.chart: lists.chart,
    TmdbOperation.genres: reference.genres_operation,
    TmdbOperation.watch_providers_catalog: reference.providers_catalog_operation,
    TmdbOperation.certifications: reference.certifications_operation,
}
