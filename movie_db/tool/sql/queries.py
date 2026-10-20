"""Whitelisted SQL for every `MovieDbOperation`.

The SQL text is built only from the constant fragments below: which fragments are
used depends on which filters are present, but no value from the request ever enters
the SQL text. Values travel only as bind parameters (`?`).
"""
from __future__ import annotations

from collections.abc import Callable

from movie_db.schema import normalize_tag

from ..models import ExecutedQuery, MovieDbOperation, MovieDbQuery, SqlParam

_GENRES_OF_MOVIE = (
    "(SELECT group_concat(g.genre, '|') FROM movie_genres g WHERE g.movie_id = m.movie_id) AS genres"
)
_MOVIE_COLUMNS = f"m.movie_id, m.clean_title AS title, m.year, s.avg_rating, s.n_ratings, {_GENRES_OF_MOVIE}"

_FILTER_GENRE = (
    "EXISTS (SELECT 1 FROM movie_genres fg WHERE fg.movie_id = m.movie_id AND fg.genre = ?)"
)
_FILTER_YEAR_FROM = "m.year >= ?"
_FILTER_YEAR_TO = "m.year <= ?"

_ORDER_BY = {
    "rating": "s.avg_rating DESC, s.n_ratings DESC, m.movie_id",
    "count": "s.n_ratings DESC, s.avg_rating DESC, m.movie_id",
}


def escape_like(value: str) -> str:
    """Escape LIKE wildcards so user text matches literally (used with ESCAPE '\\')."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _movie_filters(query: MovieDbQuery) -> tuple[list[str], list[SqlParam]]:
    clauses: list[str] = []
    params: list[SqlParam] = []
    if query.genre:
        clauses.append(_FILTER_GENRE)
        params.append(query.genre)
    if query.year_from:
        clauses.append(_FILTER_YEAR_FROM)
        params.append(query.year_from)
    if query.year_to:
        clauses.append(_FILTER_YEAR_TO)
        params.append(query.year_to)
    return clauses, params


def _ranking(order: str) -> Callable[[MovieDbQuery, int, int], ExecutedQuery]:
    def build(query: MovieDbQuery, limit: int, min_ratings: int) -> ExecutedQuery:
        clauses, params = _movie_filters(query)
        where = " AND ".join(["s.n_ratings >= ?", *clauses])
        sql = (
            f"SELECT {_MOVIE_COLUMNS} FROM movies m JOIN movie_stats s ON s.movie_id = m.movie_id "
            f"WHERE {where} ORDER BY {_ORDER_BY[order]} LIMIT ?"
        )
        return ExecutedQuery(sql=sql, params=[min_ratings, *params, limit])

    return build


def _by_title(query: MovieDbQuery, limit: int, min_ratings: int) -> ExecutedQuery:
    clauses, params = _movie_filters(query)
    where = " AND ".join(["m.clean_title LIKE ? ESCAPE '\\'", *clauses])
    sql = (
        f"SELECT {_MOVIE_COLUMNS}, l.imdb_id, l.tmdb_id FROM movies m "
        "LEFT JOIN movie_stats s ON s.movie_id = m.movie_id "
        "LEFT JOIN links l ON l.movie_id = m.movie_id "
        f"WHERE {where} ORDER BY coalesce(s.n_ratings, 0) DESC, m.movie_id LIMIT ?"
    )
    return ExecutedQuery(sql=sql, params=[f"%{escape_like(query.title or '')}%", *params, limit])


def _by_tag(query: MovieDbQuery, limit: int, min_ratings: int) -> ExecutedQuery:
    clauses, params = _movie_filters(query)
    where = " AND ".join(["t.tag_norm = ?", *clauses])
    sql = (
        f"SELECT {_MOVIE_COLUMNS}, count(DISTINCT t.user_id) AS tag_count FROM tags t "
        "JOIN movies m ON m.movie_id = t.movie_id "
        "LEFT JOIN movie_stats s ON s.movie_id = m.movie_id "
        f"WHERE {where} GROUP BY m.movie_id "
        "ORDER BY tag_count DESC, coalesce(s.avg_rating, 0) DESC, m.movie_id LIMIT ?"
    )
    return ExecutedQuery(sql=sql, params=[normalize_tag(query.tag or ""), *params, limit])


def _stats_by_genre(query: MovieDbQuery, limit: int, min_ratings: int) -> ExecutedQuery:
    clauses = ["s.n_ratings >= ?"]
    params: list[SqlParam] = [min_ratings]
    if query.genre:
        clauses.append("g.genre = ?")
        params.append(query.genre)
    if query.year_from:
        clauses.append(_FILTER_YEAR_FROM)
        params.append(query.year_from)
    if query.year_to:
        clauses.append(_FILTER_YEAR_TO)
        params.append(query.year_to)
    sql = (
        "SELECT g.genre, count(*) AS n_movies, round(avg(s.avg_rating), 3) AS avg_rating, "
        "sum(s.n_ratings) AS n_ratings FROM movie_genres g "
        "JOIN movie_stats s ON s.movie_id = g.movie_id "
        "JOIN movies m ON m.movie_id = g.movie_id "
        f"WHERE {' AND '.join(clauses)} GROUP BY g.genre ORDER BY avg_rating DESC, g.genre LIMIT ?"
    )
    return ExecutedQuery(sql=sql, params=[*params, limit])


QUERY_BUILDERS: dict[MovieDbOperation, Callable[[MovieDbQuery, int, int], ExecutedQuery]] = {
    MovieDbOperation.top_rated: _ranking("rating"),
    MovieDbOperation.by_genre_year: _ranking("rating"),
    MovieDbOperation.most_rated: _ranking("count"),
    MovieDbOperation.by_title: _by_title,
    MovieDbOperation.by_tag: _by_tag,
    MovieDbOperation.stats_by_genre: _stats_by_genre,
}


def build_query(query: MovieDbQuery, *, limit: int, min_ratings: int) -> ExecutedQuery:
    return QUERY_BUILDERS[query.operation](query, limit, min_ratings)
