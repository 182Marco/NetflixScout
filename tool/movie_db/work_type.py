"""Keep series out of MovieLens rankings, when a checker can tell them from films.

MovieLens mixes films and TV series and has no type column. A `WorkTypeChecker` (injected by
`app.py`, backed by TMDb; this package never imports it) answers `"movie"` or `"series"` for
the IMDb ids it can settle. Policy for a ranking, in the order MovieLens gives the rows:
- `series`      → dropped, never shown;
- `movie`       → kept, `work_type: "movie"`;
- unverifiable  → kept in place, `work_type: "unverified"` (no IMDb id, TMDb has no answer,
  error, budget spent, or no checker at all): losing real films because TMDb is down would be
  worse, and the answer must not present them as verified films.
Rows are checked in batches of the missing size until `limit` are kept; the cost is bounded by
the rows fetched (see `RANKING_FETCH_FACTOR` in the tool) and by the checker's own budget.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

WORK_MOVIE = "movie"
WORK_SERIES = "series"
WORK_UNVERIFIED = "unverified"


class WorkTypeChecker(Protocol):
    def classify(self, imdb_ids: Sequence[str]) -> dict[str, str]:
        """`{imdb_id: "movie" | "series"}`; ids it cannot settle are left out."""


def filter_series(
    rows: list[dict[str, Any]], *, limit: int, checker: WorkTypeChecker | None
) -> tuple[list[dict[str, Any]], int]:
    """Return at most `limit` rows with `work_type` set, and how many series were dropped."""
    if checker is None:
        return [{**row, "work_type": WORK_UNVERIFIED} for row in rows[:limit]], 0
    kept: list[dict[str, Any]] = []
    dropped = 0
    position = 0
    while len(kept) < limit and position < len(rows):
        # Only as many rows as are still missing: ids beyond the limit are not looked up.
        batch = rows[position : position + limit - len(kept)]
        position += len(batch)
        ids = [str(row["imdb_id"]) for row in batch if row.get("imdb_id")]
        verdicts = checker.classify(ids) if ids else {}
        for row in batch:
            verdict = verdicts.get(str(row.get("imdb_id") or ""))
            if verdict == WORK_SERIES:
                dropped += 1
            else:
                kept.append({**row, "work_type": WORK_MOVIE if verdict == WORK_MOVIE else WORK_UNVERIFIED})
    return kept, dropped
