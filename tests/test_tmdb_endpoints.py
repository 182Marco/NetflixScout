from __future__ import annotations

import json

import pytest

from tool.tmdb import endpoints
from tool.tmdb.dispatch import OPERATION_HANDLERS
from tool.tmdb.models.enums import ChartList, ExternalSource, Facet, MediaType, SearchKind, TimeWindow, TmdbOperation
from tool.tmdb.models.operation_rules import RULES, describe_operations
from tool.tmdb.models.requests import TmdbToolInput
from tool.tmdb.tool import TmdbTool
from tool.tmdb.config import TmdbConfig


def test_every_operation_has_a_rule_and_a_handler() -> None:
    assert set(RULES) == set(TmdbOperation) == set(OPERATION_HANDLERS)


@pytest.mark.parametrize(
    ("endpoint", "path"),
    [
        (endpoints.search(SearchKind.movie, "Dune", language="it-IT", year=2021), "/search/movie"),
        (endpoints.find("tt0816692", ExternalSource.imdb, language="it-IT"), "/find/tt0816692"),
        (endpoints.details("movie", 157336, language="it-IT"), "/movie/157336"),
        (endpoints.details("tv", 1396, language="it-IT"), "/tv/1396"),
        (endpoints.details("person", 525, language="it-IT"), "/person/525"),
        (endpoints.tv_season(1396, 0, language="it-IT"), "/tv/1396/season/0"),
        (endpoints.tv_episode(1396, 1, 2, language="it-IT"), "/tv/1396/season/1/episode/2"),
        (endpoints.watch_providers("movie", 1), "/movie/1/watch/providers"),
        (endpoints.reviews("tv", 1, language="en-US"), "/tv/1/reviews"),
        (endpoints.collection(10, language="it-IT"), "/collection/10"),
        (endpoints.collection_images(10, image_languages="it,en,null"), "/collection/10/images"),
        (endpoints.collection_translations(10), "/collection/10/translations"),
        (endpoints.company(41077), "/company/41077"),
        (endpoints.discover(MediaType.tv, {}), "/discover/tv"),
        (endpoints.trending(MediaType.all, TimeWindow.week, language="it-IT"), "/trending/all/week"),
        (endpoints.chart(MediaType.tv, ChartList.airing_today, language="it-IT"), "/tv/airing_today"),
        (endpoints.genre_list(MediaType.movie, language="en-US"), "/genre/movie/list"),
        (endpoints.watch_provider_list(MediaType.movie, region="IT", language="en-US"), "/watch/providers/movie"),
        (endpoints.certification_list(MediaType.tv), "/certification/tv/list"),
    ],
)
def test_operation_paths_are_fixed(endpoint, path) -> None:
    assert endpoint.path == path


def test_free_text_only_travels_as_an_encoded_parameter() -> None:
    endpoint = endpoints.search(SearchKind.movie, "../../account?x=1", language="it-IT")

    assert endpoint.path == "/search/movie"
    assert endpoint.params["query"] == "../../account?x=1"
    assert endpoint.params["include_adult"] == "false"
    assert endpoints.discover(MediaType.movie, {}).params["include_adult"] == "false"


def test_append_to_response_respects_the_documented_maximum() -> None:
    keys = endpoints.append_keys([Facet.watch_providers, Facet.credits], always=("credits", "translations"))
    assert keys == ("credits", "translations", "watch/providers")

    with pytest.raises(ValueError):
        endpoints.details("movie", 1, language="en-US", appends=[f"x{i}" for i in range(21)])
    with pytest.raises(ValueError):
        endpoints.details("collection", 1, language="en-US")


def test_collections_never_get_append_to_response() -> None:
    assert "append_to_response" not in endpoints.collection(10, language="it-IT").params


def test_tool_description_is_generated_from_the_rules() -> None:
    tool = TmdbTool(config=TmdbConfig(max_results=5, max_calls_per_turn=6, cache_ttl=0))

    assert describe_operations() in tool.description
    for operation, rule in RULES.items():
        assert operation.value in tool.description
        for facet in rule.facets:
            assert facet.value in describe_operations()


def test_schema_stays_compact_for_the_planner_prompt() -> None:
    schema = json.dumps(TmdbToolInput.model_json_schema(), separators=(",", ":"))

    assert len(schema) < 9_000
    assert len(schema) + len(describe_operations()) < 13_000
