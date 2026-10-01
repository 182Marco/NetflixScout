from __future__ import annotations

import ast
import csv
from pathlib import Path


def _strip_invalid_surrogates(value: str) -> str:
    return "".join(ch for ch in value if not 0xD800 <= ord(ch) <= 0xDFFF)


def _normalize_values(raw_value) -> list[str]:
    if raw_value in (None, "", "\\N", "None"):
        return []
    if isinstance(raw_value, str):
        value = _strip_invalid_surrogates(raw_value).strip()
        if not value or value in {"\\N", "None", "nan"}:
            return []
        if value.startswith("{") or value.startswith("["):
            try:
                parsed = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                cleaned = value.strip("{}[]")
                return [
                    _strip_invalid_surrogates(piece).strip().strip('"')
                    for piece in cleaned.split(",")
                    if _strip_invalid_surrogates(piece).strip()
                ]
            if isinstance(parsed, dict):
                values = []
                for item in parsed.values():
                    cleaned = _strip_invalid_surrogates(str(item)).strip()
                    if cleaned:
                        values.append(cleaned)
                return values
            if isinstance(parsed, (list, tuple, set)):
                values = []
                for item in parsed:
                    cleaned = _strip_invalid_surrogates(str(item)).strip()
                    if cleaned:
                        values.append(cleaned)
                return values
        return [_strip_invalid_surrogates(value)]
    if isinstance(raw_value, (list, tuple, set)):
        values = []
        for item in raw_value:
            cleaned = _strip_invalid_surrogates(str(item)).strip()
            if cleaned:
                values.append(cleaned)
        return values
    return [_strip_invalid_surrogates(str(raw_value)).strip()]


def _clean_string_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _strip_invalid_surrogates(value).strip()
    if isinstance(value, (int, float, bool)):
        return _strip_invalid_surrogates(str(value)).strip()
    if isinstance(value, (list, tuple, set)):
        items = []
        for item in value:
            cleaned = _strip_invalid_surrogates(str(item)).strip()
            if cleaned:
                items.append(cleaned)
        return "; ".join(items)
    if isinstance(value, dict):
        items = []
        for key, item in value.items():
            cleaned = _strip_invalid_surrogates(str(item)).strip()
            if cleaned:
                items.append(f"{key}: {cleaned}")
        return "; ".join(items)
    return _strip_invalid_surrogates(str(value)).strip()


def load_movie_metadata(path: Path) -> dict[str, dict[str, str]]:
    movies: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        for row in reader:
            if len(row) < 9:
                continue
            movie_id = row[0].strip()
            if not movie_id:
                continue
            release_date = row[3].strip()
            movies[movie_id] = {
                "movie_id": _clean_string_value(movie_id),
                "title": _clean_string_value(row[2]),
                "release_date": _clean_string_value(release_date),
                "release_year": _clean_string_value(release_date[:4] if release_date and release_date[:4].isdigit() else ""),
                "languages": _clean_string_value("; ".join(_normalize_values(row[6]))),
                "countries": _clean_string_value("; ".join(_normalize_values(row[7]))),
                "genres": _clean_string_value("; ".join(_normalize_values(row[8]))),
            }
    return movies


def load_cast_by_movie(path: Path) -> dict[str, list[str]]:
    cast_by_movie: dict[str, list[str]] = {}
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        for row in reader:
            if len(row) < 9:
                continue
            movie_id = row[0].strip()
            if not movie_id:
                continue
            actor_name = row[8].strip()
            if not actor_name:
                continue
            if movie_id not in cast_by_movie:
                cast_by_movie[movie_id] = []
            if actor_name not in cast_by_movie[movie_id]:
                cast_by_movie[movie_id].append(actor_name)
    return cast_by_movie


def iter_plot_rows(dataset_dir: Path):
    movie_metadata = load_movie_metadata(dataset_dir / "MovieSummaries" / "movie.metadata.tsv")
    cast_by_movie = load_cast_by_movie(dataset_dir / "MovieSummaries" / "character.metadata.tsv")

    plot_path = dataset_dir / "MovieSummaries" / "plot_summaries.txt"
    with plot_path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line_number, line in enumerate(handle):
            value = line.strip()
            if not value:
                continue
            parts = value.split("\t", 1)
            movie_id = parts[0].strip() if len(parts) == 2 else ""
            text = parts[1].strip() if len(parts) == 2 else value
            if not text:
                continue
            yield {
                "rel": "MovieSummaries/plot_summaries.txt",
                "doc_index": line_number,
                "movie_id": movie_id,
                "text": text,
                "movie_info": movie_metadata.get(movie_id, {}),
                "cast_names": cast_by_movie.get(movie_id, []),
            }