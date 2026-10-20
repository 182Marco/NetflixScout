from __future__ import annotations

import pytest

from movie_db.config import MovieDbConfig, load_movie_db_config
from movie_db.harness.evaluation.cases import EVAL_OVERRIDES
from movie_db.harness.fixtures.build_fixture_db import build_fixture_db


def _fixture_config(db_path) -> MovieDbConfig:
    from app import build_runtime_config

    overrides = {"movie_db": {**EVAL_OVERRIDES["movie_db"], "db_path": str(db_path)}}
    return load_movie_db_config(build_runtime_config(overrides)["movie_db"])


@pytest.fixture(scope="session")
def movie_db_config(tmp_path_factory) -> MovieDbConfig:
    """Config pointing to a mini MovieLens DB built once with the real ingestion code."""
    db_path = tmp_path_factory.mktemp("movie_db") / "fixture.sqlite3"
    config = _fixture_config(db_path)
    build_fixture_db(db_path, config.ingestion)
    return config
