"""The only mapping from operations to TMDb paths and parameters.

Path segments come from validated integers, closed enums or pattern-validated external
IDs; free text (titles, names) only travels as an encoded query parameter. `include_adult`
is always false.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from urllib.parse import quote

from .models.enums import ChartList, ExternalSource, Facet, MediaType, SearchKind, TimeWindow

# Documented limit of `append_to_response` ("20 items max").
MAX_APPEND = 20

# Appended to every movie and series details call (free): credits for director and cast,
# translations for fallbacks, translations and alternative titles to verify a title TMDb
# does not show as its own (e.g. "Survival Island" is an alternative title of "Three").
# Resolution and details use the same appends, so a verification call is the cached call
# the details operation would make anyway.
IDENTITY_APPENDS = ("credits", "translations", "alternative_titles")
# Movies also carry every release date TMDb records (premieres, other countries): a year
# can be confirmed by any of them, not only by the primary date (e.g. "The Dungeon of
# Harrow": primary 1964, premiere 1962).
MOVIE_IDENTITY_APPENDS = (*IDENTITY_APPENDS, "release_dates")


def identity_appends(namespace: str) -> tuple[str, ...]:
    return MOVIE_IDENTITY_APPENDS if namespace == "movie" else IDENTITY_APPENDS

# Facet → `append_to_response` value (the response key has the same name).
APPEND_KEYS = {facet: facet.value for facet in Facet} | {Facet.watch_providers: "watch/providers"}

_SEARCH_WITH_LANGUAGE = {SearchKind.movie, SearchKind.tv, SearchKind.person, SearchKind.collection, SearchKind.multi}
_FIND_SOURCES = {
    ExternalSource.imdb: "imdb_id",
    ExternalSource.tvdb: "tvdb_id",
    ExternalSource.wikidata: "wikidata_id",
}


@dataclass(frozen=True)
class Endpoint:
    path: str
    params: dict[str, str] = field(default_factory=dict)


def append_keys(facets: Iterable[Facet], *, always: Iterable[str] = ()) -> tuple[str, ...]:
    """Deduplicated appends; the 20-item limit is checked where the endpoint is built."""
    return tuple(dict.fromkeys([*always, *(APPEND_KEYS[facet] for facet in facets)]))


def _with_append(params: dict[str, str], appends: Iterable[str]) -> dict[str, str]:
    appends = tuple(appends)
    if len(appends) > MAX_APPEND:
        raise ValueError(f"append_to_response accepts at most {MAX_APPEND} items.")
    if appends:
        params["append_to_response"] = ",".join(appends)
    return params


def search(kind: SearchKind, text: str, *, language: str, year: int | None = None) -> Endpoint:
    params = {"query": text, "page": "1"}
    if kind in _SEARCH_WITH_LANGUAGE:
        params["language"] = language
        params["include_adult"] = "false"
    if year is not None and kind is SearchKind.movie:
        params["year"] = str(year)
    elif year is not None and kind is SearchKind.tv:
        params["first_air_date_year"] = str(year)
    return Endpoint(f"/search/{kind.value}", params)


def find(external_id: str, source: ExternalSource, *, language: str) -> Endpoint:
    return Endpoint(
        f"/find/{quote(external_id, safe='')}",
        {"external_source": _FIND_SOURCES[source], "language": language},
    )


def details(
    namespace: str,
    tmdb_id: int,
    *,
    language: str,
    appends: Iterable[str] = (),
    extra: dict[str, str] | None = None,
) -> Endpoint:
    """Movie, tv or person details: the namespaces that support `append_to_response`."""
    if namespace not in ("movie", "tv", "person"):
        raise ValueError(f"Unsupported namespace: {namespace}")
    params = _with_append({"language": language, **(extra or {})}, appends)
    return Endpoint(f"/{namespace}/{int(tmdb_id)}", params)


def tv_season(
    series_id: int,
    season: int,
    *,
    language: str,
    appends: Iterable[str] = (),
    extra: dict[str, str] | None = None,
) -> Endpoint:
    params = _with_append({"language": language, **(extra or {})}, appends)
    return Endpoint(f"/tv/{int(series_id)}/season/{int(season)}", params)


def tv_episode(
    series_id: int,
    season: int,
    episode: int,
    *,
    language: str,
    appends: Iterable[str] = (),
    extra: dict[str, str] | None = None,
) -> Endpoint:
    params = _with_append({"language": language, **(extra or {})}, appends)
    return Endpoint(f"/tv/{int(series_id)}/season/{int(season)}/episode/{int(episode)}", params)


def watch_providers(namespace: str, tmdb_id: int) -> Endpoint:
    if namespace not in ("movie", "tv"):
        raise ValueError(f"Unsupported namespace: {namespace}")
    return Endpoint(f"/{namespace}/{int(tmdb_id)}/watch/providers")


def reviews(namespace: str, tmdb_id: int, *, language: str) -> Endpoint:
    if namespace not in ("movie", "tv"):
        raise ValueError(f"Unsupported namespace: {namespace}")
    return Endpoint(f"/{namespace}/{int(tmdb_id)}/reviews", {"language": language, "page": "1"})


def collection(collection_id: int, *, language: str) -> Endpoint:
    return Endpoint(f"/collection/{int(collection_id)}", {"language": language})


def collection_images(collection_id: int, *, image_languages: str) -> Endpoint:
    return Endpoint(f"/collection/{int(collection_id)}/images", {"include_image_language": image_languages})


def collection_translations(collection_id: int) -> Endpoint:
    return Endpoint(f"/collection/{int(collection_id)}/translations")


def company(company_id: int) -> Endpoint:
    return Endpoint(f"/company/{int(company_id)}")


def discover(media: MediaType, params: dict[str, str]) -> Endpoint:
    if media not in (MediaType.movie, MediaType.tv):
        raise ValueError(f"Unsupported media: {media}")
    return Endpoint(f"/discover/{media.value}", {**params, "include_adult": "false", "page": "1"})


def trending(media: MediaType, window: TimeWindow, *, language: str) -> Endpoint:
    return Endpoint(f"/trending/{media.value}/{window.value}", {"language": language})


def chart(media: MediaType, chart_list: ChartList, *, language: str, region: str | None = None) -> Endpoint:
    params = {"language": language, "page": "1"}
    if region and media is MediaType.movie:
        params["region"] = region
    return Endpoint(f"/{media.value}/{chart_list.value}", params)


def genre_list(media: MediaType, *, language: str) -> Endpoint:
    return Endpoint(f"/genre/{media.value}/list", {"language": language})


def watch_provider_list(media: MediaType, *, region: str, language: str) -> Endpoint:
    return Endpoint(f"/watch/providers/{media.value}", {"watch_region": region, "language": language})


def certification_list(media: MediaType) -> Endpoint:
    return Endpoint(f"/certification/{media.value}/list")
