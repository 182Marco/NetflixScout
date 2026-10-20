"""Routing cases: does the orchestrator pick `movie_db_search` or `rag_search`?

Each case runs only the domain classifier and the planning call (`_plan_turn`): no
tool is executed, so no SQL, embedding or rerank call happens.
"""
from __future__ import annotations

from dataclasses import dataclass, field

DB = "movie_db_search"
RAG = "rag_search"


@dataclass(frozen=True)
class RoutingCase:
    question: str
    expected_tool: str
    history: tuple[dict[str, str], ...] = ()
    # Lowercase fragments the standalone query must contain (follow-ups only).
    standalone_must_contain: tuple[str, ...] = field(default_factory=tuple)


_HORROR_80S = (
    {"role": "user", "content": "Quali sono i film horror più votati degli anni '80?"},
    {"role": "assistant", "content": "I più votati sono The Shining (1980), Alien (1979) e The Thing (1982)."},
)

ROUTING_CASES: tuple[RoutingCase, ...] = (
    RoutingCase("Quali sono i 10 film più votati di sempre?", DB),
    RoutingCase("Che voto medio ha Pulp Fiction?", DB),
    RoutingCase("Classifica dei migliori thriller degli anni 2000", DB),
    RoutingCase("Quali film hanno più spesso il tag 'time travel'?", DB),
    RoutingCase("Qual è il genere con il voto medio più alto?", DB),
    RoutingCase("Consigliami un film su un robot che si innamora di un umano", RAG),
    RoutingCase("Di cosa parla Inception?", RAG),
    RoutingCase("Vorrei un film malinconico ambientato in Giappone", RAG),
    RoutingCase("Il film in cui Tom Hanks naufraga su un'isola deserta", RAG),
    RoutingCase("E degli anni '90?", DB, history=_HORROR_80S, standalone_must_contain=("horror", "90")),
)
