"""Reranker query (D4): semantic intent plus every explicit requirement, from real signals.

Signals below are copied from the real e2e runs of 2026-10-22 (e2e_results*.json).
"""
from __future__ import annotations

from tool.rag.FromQueryEmbeddingToRes.models import QuerySignals
from tool.rag.FromQueryEmbeddingToRes.retrieval import compose_rerank_query

CASE_20 = QuerySignals(  # run 1 and 2: the semantic sentence dropped "1950s"
    semantic_query="A Japanese science fiction comedy set on Mars with an open ending and emotional resonance.",
    positive_signals=["Japanese", "1950s", "Mars setting", "open ending", "emotionally moving"],
    genres=["Science Fiction", "Comedy"],
)
CASE_13 = QuerySignals(
    semantic_query=("A somber reflective drama exploring euthanasia, personal autonomy, disability, human dignity, "
                    "and existential questions about life and death."),
    positive_signals=["euthanasia and right to die", "disability and autonomy", "existential questions", "human dignity"],
    genres=["Drama"],
)
CASE_11 = QuerySignals(
    semantic_query="A realistic film about euthanasia with a delicate tone and complex, believable characters.",
    positive_signals=["euthanasia", "delicate tone", "complex characters", "realistic characters"],
    genres=["Drama"], excluded_genres=["Science Fiction"],
)
CASE_12 = QuerySignals(
    semantic_query=("A crime drama about organized crime, family dynamics, and moral conflict with an intense "
                    "atmosphere and a non-tragic ending."),
    positive_signals=["intense atmosphere", "organized crime", "family dynamics", "moral conflict", "non-tragic ending"],
    genres=["Crime Fiction", "Drama"],
)
CASE_16 = QuerySignals(
    semantic_query="A revenge film centered on a solitary protagonist seeking retribution.",
    positive_signals=["revenge plot", "solitary protagonist", "ratings requested"],
)


def test_case_20_keeps_the_decade_the_semantic_sentence_dropped() -> None:
    query = compose_rerank_query(CASE_20, "Cerco una commedia fantascientifica giapponese degli anni Cinquanta…")

    assert query.startswith(CASE_20.semantic_query)
    assert "1950s" in query and "Mars setting" in query
    assert query.count("Japanese") == 1 and "Comedy;" not in query  # already in the sentence


def test_case_13_thematic_query_is_left_almost_unchanged() -> None:
    query = compose_rerank_query(CASE_13, "Mare dentro mi ha colpito molto…")

    assert query.startswith(CASE_13.semantic_query)
    # Only what the sentence lacks is appended: "right to die" ("drama" is already there).
    assert query.endswith("Must match: euthanasia and right to die.")


def test_case_11_excluded_genres_are_not_turned_into_requirements() -> None:
    query = compose_rerank_query(CASE_11, "Cerco un film sull'eutanasia…")

    assert "Science Fiction" not in query and query.endswith("Must match: Drama.")


def test_case_12_requirements_already_in_the_sentence_are_not_repeated() -> None:
    query = compose_rerank_query(CASE_12, "Consigliami qualcosa simile a Il Padrino…")

    assert query == f"{CASE_12.semantic_query} Must match: Crime Fiction."


def test_case_16_answer_requests_never_reach_the_reranker() -> None:
    query = compose_rerank_query(CASE_16, "Consigliami un film di vendetta… e indicami anche i voti")

    assert "rating" not in query.lower()
    assert query.endswith("Must match: revenge plot.")


def test_without_semantic_query_the_user_query_is_the_base() -> None:
    assert compose_rerank_query(QuerySignals(), "film con robot") == "film con robot"
