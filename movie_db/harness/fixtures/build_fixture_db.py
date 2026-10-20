"""Build a small movie DB from `movielens_mini/` with the real ingestion code."""
from __future__ import annotations

from pathlib import Path

from movie_db.config import IngestionConfig
from movie_db.harness.ingestion.build import build_movie_db

FIXTURE_DIR = Path(__file__).parent / "movielens_mini"


def build_fixture_db(db_path: Path, ingestion: IngestionConfig) -> Path:
    return build_movie_db(source_dir=FIXTURE_DIR, db_path=db_path, ingestion=ingestion)
