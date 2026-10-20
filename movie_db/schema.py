"""Tables, columns and DDL of the MovieLens SQLite database.

Single source shared by the offline ingestion (which creates the tables) and the
runtime (whose read-only guard allows reading only these tables). No I/O here.
"""
from __future__ import annotations

MOVIES = "movies"
MOVIE_GENRES = "movie_genres"
RATINGS = "ratings"
MOVIE_STATS = "movie_stats"
TAGS = "tags"
LINKS = "links"

TABLES: dict[str, tuple[str, ...]] = {
    MOVIES: ("movie_id", "title", "clean_title", "year"),
    MOVIE_GENRES: ("movie_id", "genre"),
    RATINGS: ("user_id", "movie_id", "rating", "rated_at"),
    MOVIE_STATS: ("movie_id", "n_ratings", "avg_rating", "first_rated_at", "last_rated_at"),
    TAGS: ("user_id", "movie_id", "tag", "tag_norm", "tagged_at"),
    LINKS: ("movie_id", "imdb_id", "tmdb_id"),
}

# Genre vocabulary of MovieLens 32M ("(no genres listed)" is stored as no genre).
GENRES: tuple[str, ...] = (
    "Action",
    "Adventure",
    "Animation",
    "Children",
    "Comedy",
    "Crime",
    "Documentary",
    "Drama",
    "Fantasy",
    "Film-Noir",
    "Horror",
    "IMAX",
    "Musical",
    "Mystery",
    "Romance",
    "Sci-Fi",
    "Thriller",
    "War",
    "Western",
)
NO_GENRES_LABEL = "(no genres listed)"


def normalize_tag(tag: str) -> str:
    """Form stored in `tags.tag_norm` and used to look tags up."""
    return " ".join(tag.split()).casefold()


CREATE_TABLES: tuple[str, ...] = (
    f"""CREATE TABLE {MOVIES} (
        movie_id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        clean_title TEXT NOT NULL,
        year INTEGER
    )""",
    f"""CREATE TABLE {MOVIE_GENRES} (
        movie_id INTEGER NOT NULL REFERENCES {MOVIES}(movie_id),
        genre TEXT NOT NULL,
        PRIMARY KEY (movie_id, genre)
    )""",
    f"""CREATE TABLE {RATINGS} (
        user_id INTEGER NOT NULL,
        movie_id INTEGER NOT NULL,
        rating REAL NOT NULL,
        rated_at INTEGER NOT NULL
    )""",
    f"""CREATE TABLE {MOVIE_STATS} (
        movie_id INTEGER PRIMARY KEY REFERENCES {MOVIES}(movie_id),
        n_ratings INTEGER NOT NULL,
        avg_rating REAL NOT NULL,
        first_rated_at INTEGER,
        last_rated_at INTEGER
    )""",
    f"""CREATE TABLE {TAGS} (
        user_id INTEGER NOT NULL,
        movie_id INTEGER NOT NULL,
        tag TEXT NOT NULL,
        tag_norm TEXT NOT NULL,
        tagged_at INTEGER NOT NULL
    )""",
    f"""CREATE TABLE {LINKS} (
        movie_id INTEGER PRIMARY KEY REFERENCES {MOVIES}(movie_id),
        imdb_id TEXT,
        tmdb_id TEXT
    )""",
)

# Created after the bulk load: building indexes once is much faster than updating them.
CREATE_INDEXES: tuple[str, ...] = (
    f"CREATE INDEX idx_movies_year ON {MOVIES}(year)",
    f"CREATE INDEX idx_movies_clean_title ON {MOVIES}(clean_title COLLATE NOCASE)",
    f"CREATE INDEX idx_movie_genres_genre ON {MOVIE_GENRES}(genre, movie_id)",
    f"CREATE INDEX idx_ratings_movie ON {RATINGS}(movie_id)",
    f"CREATE INDEX idx_movie_stats_avg ON {MOVIE_STATS}(avg_rating, n_ratings)",
    f"CREATE INDEX idx_movie_stats_count ON {MOVIE_STATS}(n_ratings)",
    f"CREATE INDEX idx_tags_norm ON {TAGS}(tag_norm, movie_id)",
)
