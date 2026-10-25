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

CMU_DIR = Path("dataset/MovieSummaries")
MOVIELENS_DB = Path("movie_db/data/movielens32m.sqlite3")

_YEAR = re.compile(r"^(\d{4})")


def measure_cmu(directory: Path = CMU_DIR) -> dict[str, Any]:
    """Release years of the CMU films that have a plot summary (the ones the RAG indexes)."""
    with open(directory / "plot_summaries.txt", encoding="utf8") as handle:
        with_summary = {line.split("\t", 1)[0] for line in handle}
    per_year: dict[int, int] = {}
    latest = ""
    with open(directory / "movie.metadata.tsv", encoding="utf8") as handle:
        for line in handle:
            fields = line.split("\t")
            match = _YEAR.match(fields[3]) if len(fields) > 3 else None
            if fields[0] in with_summary and match:
                per_year[int(match.group(1))] = per_year.get(int(match.group(1)), 0) + 1
                latest = max(latest, fields[3])
    return {"films_per_year": per_year, "latest_release": latest, "max_year": max(per_year)}


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
    cmu = measure_cmu()
    ml = measure_movielens()
    print("CMU (con trama):", cmu["max_year"], cmu["latest_release"], {
        y: n for y, n in sorted(cmu["films_per_year"].items())[-5:]})
    print("MovieLens:", ml["max_year"], ml["first_rating"], ml["last_rating"], {
        y: n for y, n in sorted(ml["films_per_year"].items())[-4:]})
