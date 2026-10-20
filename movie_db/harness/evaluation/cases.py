"""Evaluation cases: question → expected operation and expected titles on the fixture DB.

Expected titles assume the fixture DB and `EVAL_OVERRIDES` (`min_ratings` lowered
to fit the mini dataset).
"""
from __future__ import annotations

from dataclasses import dataclass

from movie_db.tool.models import MovieDbOperation, MovieDbQuery

EVAL_OVERRIDES = {"movie_db": {"query": {"min_ratings": 2}}}

# Ranking by rating with a genre and no year range: both operations are valid readings.
_RATING_RANKINGS = frozenset({MovieDbOperation.top_rated, MovieDbOperation.by_genre_year})


@dataclass(frozen=True)
class EvalCase:
    question: str
    expected: MovieDbQuery
    # Leading titles of the result, in order.
    expected_titles: tuple[str, ...]

    def equivalent_operations(self) -> frozenset[MovieDbOperation]:
        """Operations other than `expected.operation` that are also a correct reading.

        Only candidates: the run must still execute exactly the expected SQL and params.
        """
        expected = self.expected
        if (
            expected.operation in _RATING_RANKINGS
            and expected.genre
            and not (expected.year_from or expected.year_to)
        ):
            return _RATING_RANKINGS - {expected.operation}
        return frozenset()


CASES: tuple[EvalCase, ...] = (
    EvalCase(
        question="Quali sono i film di fantascienza con il voto più alto?",
        expected=MovieDbQuery(operation=MovieDbOperation.top_rated, genre="Sci-Fi"),
        expected_titles=("The Matrix", "Blade Runner", "Alien", "Back to the Future"),
    ),
    EvalCase(
        question="Consigliami un horror degli anni '70 o '80 molto votato",
        expected=MovieDbQuery(
            operation=MovieDbOperation.by_genre_year,
            genre="Horror",
            year_from=1970,
            year_to=1989,
        ),
        expected_titles=("Alien",),
    ),
    EvalCase(
        question="Dammi i 3 film con più voti",
        expected=MovieDbQuery(operation=MovieDbOperation.most_rated, limit=3),
        expected_titles=("Toy Story", "The Matrix", "Blade Runner"),
    ),
    EvalCase(
        question="Che voto medio ha Matrix?",
        expected=MovieDbQuery(operation=MovieDbOperation.by_title, title="Matrix"),
        expected_titles=("The Matrix",),
    ),
    EvalCase(
        question="Film con il tag viaggi nel tempo",
        expected=MovieDbQuery(operation=MovieDbOperation.by_tag, tag="time travel"),
        expected_titles=("Back to the Future",),
    ),
    EvalCase(
        question="Qual è il genere con il voto medio più alto?",
        expected=MovieDbQuery(operation=MovieDbOperation.stats_by_genre, limit=1),
        expected_titles=("Action",),
    ),
)
