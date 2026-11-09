"""What time span the local data sources cover, and the planner rule built from it.

`measure_*` read the local datasets deterministically (used by tests and by
`python data_coverage.py`); `coverage_rule` turns the configured years into the text appended
to the planner instructions. Stdlib only, no network.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

MOVIELENS_DB = Path("movie_db/data/movielens32m.sqlite3")

_YEAR = re.compile(r"^(\d{4})")


def measure_movielens(db_path: Path = MOVIELENS_DB) -> dict[str, Any]:
    """Release years and rating timestamps of the MovieLens database (read-only)."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        per_year = dict(
            con.execute("SELECT year, COUNT(*) FROM movies WHERE year IS NOT NULL GROUP BY year")
        )
        first, last = con.execute(
            "SELECT datetime(MIN(rated_at), 'unixepoch'), datetime(MAX(rated_at), 'unixepoch') "
            "FROM ratings"
        ).fetchone()
    finally:
        con.close()
    return {
        "films_per_year": per_year,
        "max_year": max(per_year),
        "first_rating": first,
        "last_rating": last,
    }


def coverage_rule(coverage: dict[str, dict[str, Any]], tmdb_tool: str = "tmdb_search") -> str:
    """Planner rule: a source whose data stops at a year is not the start for later years."""
    if not coverage:
        return ""
    lines = []
    for tool, info in coverage.items():
        lines.append(
            f"{tool}: film fino al {info['last_complete_year']} compreso"
            f" ({info['note']})"
        )
    return (
        "\nCopertura temporale dei dati locali (calcolata dai dataset): "
        + "; ".join(lines)
        + ". Regola di copertura, che prevale sulle regole 2 e 3: se l'utente chiede "
        "specificamente film, voti, classifiche o dati su film usciti DOPO l'ultimo anno "
        f"coperto da un tool (anni, decenni o periodi successivi, oppure 'ultimi', 'recenti', "
        f"'nuovi', 'in uscita', 'quest'anno' riferiti al presente), non partire da quel tool: "
        f"scegli {tmdb_tool}, che ha dati aggiornati. Se la richiesta non fissa un periodo "
        "(raccomandazioni generiche, classici) la regola non si applica."
    )


if __name__ == "__main__":
    ml = measure_movielens()
    print("MovieLens:", ml["max_year"], ml["first_rating"], ml["last_rating"], {
        y: n for y, n in sorted(ml["films_per_year"].items())[-4:]})
