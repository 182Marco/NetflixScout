from __future__ import annotations

import json

import pytest

from app import CONFIG
from movie_db.config import load_movie_db_config
from movie_db.schema import GENRES
from movie_db.tool.models import MovieDbOperation
from movie_db.tool.parser import MovieDbParseError, parse_query

PARSER = load_movie_db_config(CONFIG["movie_db"]).parser


class FakeClient:
    def __init__(self, output: str | Exception) -> None:
        self.output = output
        self.calls: list[dict] = []
        self.responses = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.output, Exception):
            raise self.output
        return type("Response", (), {"output_text": self.output})()


def test_valid_json_becomes_a_query_and_genres_reach_the_prompt() -> None:
    client = FakeClient(json.dumps({"operation": "by_genre_year", "genre": "sci-fi", "year_from": 1980, "year_to": 1989}))

    query = parse_query("fantascienza anni 80", PARSER, client)

    assert query.operation is MovieDbOperation.by_genre_year
    assert query.genre == "Sci-Fi"
    assert client.calls[0]["model"] == PARSER.model
    assert client.calls[0]["input"] == "fantascienza anni 80"
    assert ", ".join(GENRES) in client.calls[0]["instructions"]
    assert "{genres}" not in client.calls[0]["instructions"]


def test_fenced_json_is_accepted() -> None:
    client = FakeClient('```json\n{"operation": "most_rated", "limit": 3}\n```')

    assert parse_query("i più votati", PARSER, client).limit == 3


@pytest.mark.parametrize(
    "output",
    [
        '{"operation": "drop_table"}',
        '{"operation": "top_rated", "sql": "DELETE FROM movies"}',
        '{"operation": "top_rated", "genre": "Telenovela"}',
        '{"operation": "top_rated", "year_from": 3000}',
        '{"operation": "top_rated", "year_from": 1999, "year_to": 1990}',
        '{"operation": "by_title"}',
        '{"operation": "top_rated", "limit": 0}',
        "SELECT * FROM movies",
        "[]",
        "",
    ],
)
def test_invalid_outputs_are_rejected(output) -> None:
    with pytest.raises(MovieDbParseError):
        parse_query("x", PARSER, FakeClient(output))


def test_llm_errors_become_parse_errors() -> None:
    with pytest.raises(MovieDbParseError):
        parse_query("x", PARSER, FakeClient(RuntimeError("offline")))
