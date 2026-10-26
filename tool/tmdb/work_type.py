"""Tell films from TV series for MovieLens rankings, using TMDb `/find` by IMDb id.

MovieLens has no work type, so `movie_db_search` asks (through the app wiring, never by
importing this package) which of its IMDb ids are films and which are series. One `/find`
call per id: TMDb answers with `movie_results` and/or `tv_results`. The verdict is
`"movie"` only for movie results alone, `"series"` only for TV results alone; no result,
both, an error, a missing key or an exhausted budget leave the id out of the answer
(unverifiable). The checks draw on their own small budget, not on the turn's.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .budget import CallBudget
from .endpoints import find
from .errors import TmdbAuthError, TmdbBudgetExhausted, TmdbConfigError, TmdbError, TmdbRateLimited
from .http import get_json
from .models.enums import ExternalSource
from .settings import REFERENCE_LANGUAGE
from .tool import TmdbTool

MOVIE = "movie"
SERIES = "series"
# Calls allowed per `classify`; cached ids cost nothing.
MAX_CHECKS = 12
_IMDB_DIGITS = 7
_STOP = (TmdbAuthError, TmdbBudgetExhausted, TmdbRateLimited)


def imdb_tt(imdb_id: str) -> str | None:
    """MovieLens stores "0114709"; TMDb wants "tt0114709". None if it is not numeric."""
    digits = str(imdb_id).strip().removeprefix("tt")
    return f"tt{digits.zfill(_IMDB_DIGITS)}" if digits.isdigit() else None


@dataclass(kw_only=True)
class TmdbWorkTypeChecker:
    tool: TmdbTool
    max_checks: int = MAX_CHECKS

    def classify(self, imdb_ids: Sequence[str]) -> dict[str, str]:
        """`{imdb_id: "movie" | "series"}` for the ids TMDb settles; the others are absent."""
        try:
            credentials = self.tool._credentials()
        except TmdbConfigError:
            return {}
        ctx = self.tool.new_context(credentials, api_language=REFERENCE_LANGUAGE)
        ctx.budget = CallBudget(self.max_checks)
        verdicts: dict[str, str] = {}
        for imdb_id in imdb_ids:
            external = imdb_tt(imdb_id)
            if external is None:
                continue
            try:
                data = get_json(ctx, find(external, ExternalSource.imdb, language=REFERENCE_LANGUAGE))
            except _STOP:
                break
            except TmdbError:
                continue
            has_movie, has_tv = bool(data.get("movie_results")), bool(data.get("tv_results"))
            if has_movie != has_tv:
                verdicts[imdb_id] = MOVIE if has_movie else SERIES
        return verdicts
