"""Build the MovieLens SQLite database from the 32M CSV files.

Non destructive: an existing database is replaced only with `--force`, and the new
one is written to a temporary file that is renamed into place only when complete.

    python -m movie_db.harness.ingestion.build [--source-dir DIR] [--db-path FILE] [--force]

The result is `movie_db/data/movielens32m.sqlite3`, the INPUT of the offline build of `cinema_db` (`cinema_db/harness/build/movielens_layer.py`
and `verify_movielens.py` read it). Nothing reads it at runtime. MovieLens is static: ml-32m always gives 87,585 movies, 32,000,204 ratings and
2,000,066 tags. Download: https://files.grouplens.org/datasets/movielens/ml-32m.zip (unzip into `movie_db/data/raw/`).
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from collections.abc import Iterable, Iterator
from itertools import islice
from pathlib import Path
from dataclasses import dataclass
from typing import Any

from movie_db import schema

from .load_csv import (
    LINKS_CSV,
    MOVIES_CSV,
    RATINGS_CSV,
    TAGS_CSV,
    iter_links,
    iter_movies,
    iter_ratings,
    iter_tags,
)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_DIR = ROOT / "movie_db/data/raw/ml-32m"
DEFAULT_DB_PATH = ROOT / "movie_db/data/movielens32m.sqlite3"
_TMP_SUFFIX = ".building"


@dataclass(frozen=True)
class IngestionConfig:
    """What the offline load keeps. The defaults are the ones of the database the cinema build was validated on (ratings and tags included)."""

    batch_size: int = 100_000
    include_ratings: bool = True
    include_tags: bool = True


def _batches(rows: Iterable[tuple], size: int) -> Iterator[list[tuple]]:
    iterator = iter(rows)
    while batch := list(islice(iterator, size)):
        yield batch


def _insert_sql(table: str) -> str:
    columns = schema.TABLES[table]
    return f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})"


def _required_files(ingestion: IngestionConfig) -> list[str]:
    files = [MOVIES_CSV, RATINGS_CSV, LINKS_CSV]
    if ingestion.include_tags:
        files.append(TAGS_CSV)
    return files


def _load_movies(conn: sqlite3.Connection, source_dir: Path, batch_size: int) -> None:
    movie_rows: list[tuple] = []
    genre_rows: list[tuple] = []
    for movie in iter_movies(source_dir):
        movie_rows.append((movie.movie_id, movie.title, movie.clean_title, movie.year))
        genre_rows.extend((movie.movie_id, genre) for genre in dict.fromkeys(movie.genres))
    for batch in _batches(movie_rows, batch_size):
        conn.executemany(_insert_sql(schema.MOVIES), batch)
    for batch in _batches(genre_rows, batch_size):
        conn.executemany(_insert_sql(schema.MOVIE_GENRES), batch)


def _load_ratings_and_stats(
    conn: sqlite3.Connection,
    source_dir: Path,
    ingestion: IngestionConfig,
) -> int:
    # movie_id -> [count, sum, first, last]: stats are computed in the same pass,
    # so they exist also when the raw ratings table is not kept.
    stats: dict[int, list[Any]] = {}

    def _with_stats() -> Iterator[tuple[int, int, float, int]]:
        for row in iter_ratings(source_dir):
            _, movie_id, rating, rated_at = row
            entry = stats.get(movie_id)
            if entry is None:
                stats[movie_id] = [1, rating, rated_at, rated_at]
            else:
                entry[0] += 1
                entry[1] += rating
                entry[2] = min(entry[2], rated_at)
                entry[3] = max(entry[3], rated_at)
            yield row

    total = 0
    for batch in _batches(_with_stats(), ingestion.batch_size):
        total += len(batch)
        if ingestion.include_ratings:
            conn.executemany(_insert_sql(schema.RATINGS), batch)
            conn.commit()

    stat_rows = [
        (movie_id, count, round(rating_sum / count, 4), first, last)
        for movie_id, (count, rating_sum, first, last) in stats.items()
    ]
    for batch in _batches(stat_rows, ingestion.batch_size):
        conn.executemany(_insert_sql(schema.MOVIE_STATS), batch)
    return total


def build_movie_db(
    *,
    source_dir: Path,
    db_path: Path,
    ingestion: IngestionConfig = IngestionConfig(),
    force: bool = False,
    verbose: bool = False,
) -> Path:
    """Create the database at `db_path` from the CSV files in `source_dir`."""
    source_dir = Path(source_dir)
    db_path = Path(db_path)
    missing = [name for name in _required_files(ingestion) if not (source_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"Missing MovieLens files in {source_dir}: {', '.join(missing)}. "
            "Download ml-32m.zip from https://grouplens.org/datasets/movielens/32m/ and unzip it there."
        )
    if db_path.exists() and not force:
        raise FileExistsError(f"{db_path} already exists. Re-run with --force to rebuild it.")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = db_path.with_name(db_path.name + _TMP_SUFFIX)
    tmp_path.unlink(missing_ok=True)

    def _log(message: str) -> None:
        if verbose:
            print(message)

    conn = sqlite3.connect(tmp_path)
    try:
        # The temporary file is discarded on failure, so durability is not needed while loading.
        conn.execute("PRAGMA journal_mode = OFF")
        conn.execute("PRAGMA synchronous = OFF")
        for statement in schema.CREATE_TABLES:
            conn.execute(statement)

        _log("🎬 Loading movies and genres...")
        _load_movies(conn, source_dir, ingestion.batch_size)
        _log("🔗 Loading links...")
        for batch in _batches(iter_links(source_dir), ingestion.batch_size):
            conn.executemany(_insert_sql(schema.LINKS), batch)
        _log("⭐ Loading ratings and computing stats...")
        total = _load_ratings_and_stats(conn, source_dir, ingestion)
        _log(f"   {total} ratings read")
        if ingestion.include_tags:
            _log("🏷️  Loading tags...")
            for batch in _batches(iter_tags(source_dir), ingestion.batch_size):
                conn.executemany(_insert_sql(schema.TAGS), batch)

        _log("📇 Creating indexes...")
        for statement in schema.CREATE_INDEXES:
            conn.execute(statement)
        conn.commit()
        conn.execute("ANALYZE")
        conn.commit()
    except BaseException:
        conn.close()
        tmp_path.unlink(missing_ok=True)
        raise
    conn.close()

    os.replace(tmp_path, db_path)
    _log(f"✅ Movie DB ready: {db_path}")
    return db_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the MovieLens 32M SQLite database.")
    parser.add_argument("--source-dir", default=str(DEFAULT_SOURCE_DIR), help="Folder with movies.csv, ratings.csv, tags.csv, links.csv.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="Output SQLite file.")
    parser.add_argument("--force", action="store_true", help="Replace an existing database.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    build_movie_db(source_dir=Path(args.source_dir), db_path=Path(args.db_path), force=args.force, verbose=True)


if __name__ == "__main__":
    main()
