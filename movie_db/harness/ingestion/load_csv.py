"""Streaming parsers for the MovieLens 32M CSV files (no I/O on the database)."""
from __future__ import annotations

import csv
import re
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

from movie_db.schema import NO_GENRES_LABEL, normalize_tag

MOVIES_CSV = "movies.csv"
RATINGS_CSV = "ratings.csv"
TAGS_CSV = "tags.csv"
LINKS_CSV = "links.csv"

# "Heat (1995)", "Babylon 5 (1994-1998)", "Mortal Kombat (1995) " → year 1995.
_YEAR_SUFFIX = re.compile(r"\s*\((\d{4})(?:[–-]\d{0,4})?\)\s*$")
# MovieLens moves leading articles to the end: "Matrix, The" → "The Matrix".
_TRAILING_ARTICLE = re.compile(r"^(?P<body>.+), (?P<article>The|A|An|La|Le|Les|L'|Il|Lo|El|Los|Las|Das|Der|Die)$")


class MovieRecord(NamedTuple):
    movie_id: int
    title: str
    clean_title: str
    year: int | None
    genres: tuple[str, ...]


def split_title_year(raw_title: str) -> tuple[str, int | None]:
    """Return (clean title, year) from a MovieLens title."""
    title = raw_title.strip()
    year = None
    match = _YEAR_SUFFIX.search(title)
    if match:
        year = int(match.group(1))
        title = title[: match.start()].strip()
    article = _TRAILING_ARTICLE.match(title)
    if article:
        separator = "" if article.group("article").endswith("'") else " "
        title = f"{article.group('article')}{separator}{article.group('body')}"
    return title, year


def parse_genres(raw_genres: str) -> tuple[str, ...]:
    if not raw_genres or raw_genres.strip() == NO_GENRES_LABEL:
        return ()
    return tuple(genre.strip() for genre in raw_genres.split("|") if genre.strip())


def _rows(path: Path) -> Iterator[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(handle)


def iter_movies(source_dir: Path) -> Iterator[MovieRecord]:
    for row in _rows(source_dir / MOVIES_CSV):
        clean_title, year = split_title_year(row["title"])
        yield MovieRecord(
            movie_id=int(row["movieId"]),
            title=row["title"].strip(),
            clean_title=clean_title,
            year=year,
            genres=parse_genres(row["genres"]),
        )


def iter_ratings(source_dir: Path) -> Iterator[tuple[int, int, float, int]]:
    for row in _rows(source_dir / RATINGS_CSV):
        yield int(row["userId"]), int(row["movieId"]), float(row["rating"]), int(row["timestamp"])


def iter_tags(source_dir: Path) -> Iterator[tuple[int, int, str, str, int]]:
    for row in _rows(source_dir / TAGS_CSV):
        tag = (row["tag"] or "").strip()
        if not tag:
            continue
        yield int(row["userId"]), int(row["movieId"]), tag, normalize_tag(tag), int(row["timestamp"])


def iter_links(source_dir: Path) -> Iterator[tuple[int, str | None, str | None]]:
    for row in _rows(source_dir / LINKS_CSV):
        yield int(row["movieId"]), (row["imdbId"] or None), (row["tmdbId"] or None)
