"""The contract of `rag_search` as the planner sees it."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FilmIndexToolInput(BaseModel):
    """Search the film index (about 41,000 films with the plot of Italian Wikipedia) by plot, themes, mood, genre, setting, era, style, people, year or country.

    Put the whole request in `query`, positive and negative parts together ("come X ma senza Y"): exclusions, cited films, franchises and filters are
    extracted from it. `k_finale` is how many films to return.
    """

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    k_finale: int | None = Field(
        default=None,
        description=("How many films to return: the number the user asked for ('un film' = 1, 'dammi 5 film' = 5), null when no number is given."),
    )
