"""Map DB rows to the chunk shape read by `LLMOrchestrator._build_final_context`."""
from __future__ import annotations

from typing import Any

SOURCE = "movielens"


def _movie_text(row: dict[str, Any]) -> str:
    parts = []
    if row.get("n_ratings"):
        parts.append(f"Voto medio {row['avg_rating']:.2f}/5 su {row['n_ratings']} voti.")
    else:
        parts.append("Nessun voto nel database.")
    if row.get("tag_count"):
        parts.append(f"Tag assegnato da {row['tag_count']} utenti.")
    if row.get("imdb_id"):
        parts.append(f"IMDb: tt{row['imdb_id']}.")
    return " ".join(parts)


def _genre_text(row: dict[str, Any]) -> str:
    return (
        f"Genere {row['genre']}: {row['n_movies']} film, voto medio {row['avg_rating']:.2f}/5, "
        f"{row['n_ratings']} voti totali."
    )


def row_to_chunk(row: dict[str, Any]) -> dict[str, Any]:
    if "genre" in row and "movie_id" not in row:
        return {
            "id": f"genre:{row['genre']}",
            "testo": _genre_text(row),
            "score": float(row.get("avg_rating") or 0.0),
            "source": SOURCE,
            "title": row["genre"],
            "genres": row["genre"],
            "n_movies": row["n_movies"],
            "n_ratings": row["n_ratings"],
        }
    return {
        "id": f"movielens:{row['movie_id']}",
        "testo": _movie_text(row),
        "score": float(row.get("avg_rating") or 0.0),
        "source": SOURCE,
        "movie_id": str(row["movie_id"]),
        "title": row["title"],
        "release_year": str(row["year"]) if row.get("year") else None,
        "genres": (row.get("genres") or "").replace("|", ", ") or None,
        "n_ratings": row.get("n_ratings") or 0,
    }
