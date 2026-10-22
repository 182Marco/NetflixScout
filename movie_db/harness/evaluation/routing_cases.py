"""Routing cases: does the orchestrator pick `movie_db_search`, `rag_search` or `tmdb_search`?

Each case runs only the domain classifier and the planning call (`_plan_turn`): no
tool is executed, so no SQL, embedding or rerank call happens.
"""
from __future__ import annotations

from dataclasses import dataclass, field

DB = "movie_db_search"
RAG = "rag_search"
TMDB = "tmdb_search"
# No tool: the planner asks the user for the missing title (orchestrator.CLARIFICATION).
CLARIFY = "clarification"


@dataclass(frozen=True)
class RequestExpectation:
    """A planned `tmdb_search` request that answers the question.

    The arguments must validate as `TmdbToolInput` and at least one request must use
    `operation`, contain each lowercase fragment in its field and ask for every facet.
    """

    operation: str
    fields: tuple[tuple[str, str], ...] = ()
    facets: tuple[str, ...] = ()


@dataclass(frozen=True)
class RoutingCase:
    question: str
    expected_tool: str
    history: tuple[dict[str, str], ...] = ()
    # Lowercase fragments the standalone query must contain (follow-ups only).
    standalone_must_contain: tuple[str, ...] = field(default_factory=tuple)
    # TMDb cases only: the planned arguments must contain a coherent request; a tuple lists
    # acceptable alternatives (e.g. details or a search for an ambiguous title).
    expected_request: RequestExpectation | tuple[RequestExpectation, ...] | None = None


_HORROR_80S = (
    {"role": "user", "content": "Quali sono i film horror più votati degli anni '80?"},
    {"role": "assistant", "content": "I più votati sono The Shining (1980), Alien (1979) e The Thing (1982)."},
)

_EUTHANASIA_TOP = (
    {"role": "user", "content": "Mi dici il film che ha parlato di eutanasia che ha ricevuto i voti più alti nella storia?"},
    {"role": "assistant", "content": "Il film sull'eutanasia con il voto medio più alto è The Sea Inside (Mar adentro, 2004)."},
)

_TOP_RATED = (
    {"role": "user", "content": "Qual è il film con il voto medio più alto su MovieLens?"},
    {"role": "assistant", "content": "Il primo è The Shawshank Redemption (1994), con voto medio 4,4/5."},
)

_INTERSTELLAR = (
    {"role": "user", "content": "Consigliami un film di fantascienza sui viaggi nello spazio"},
    {"role": "assistant", "content": "Ti consiglio Interstellar (2014) di Christopher Nolan."},
)

ROUTING_CASES: tuple[RoutingCase, ...] = (
    RoutingCase("Quali sono i 10 film più votati di sempre?", DB),
    RoutingCase("Che voto medio ha Pulp Fiction?", DB),
    RoutingCase("Classifica dei migliori thriller degli anni 2000", DB),
    RoutingCase("Quali film hanno più spesso il tag 'time travel'?", DB),
    RoutingCase("Qual è il genere con il voto medio più alto?", DB),
    RoutingCase("Consigliami un film su un robot che si innamora di un umano", RAG),
    # Information on a film named by its title starts from TMDb (routing rule 1).
    RoutingCase(
        "Di cosa parla Inception?",
        TMDB,
        expected_request=RequestExpectation("movie_details", fields=(("title", "inception"),)),
    ),
    RoutingCase("Vorrei un film malinconico ambientato in Giappone", RAG),
    RoutingCase("Il film in cui Tom Hanks naufraga su un'isola deserta", RAG),
    RoutingCase("E degli anni '90?", DB, history=_HORROR_80S, standalone_must_contain=("horror", "90")),
    # Follow-up in another language that acts on the film just suggested: once blocked as off-topic.
    RoutingCase(
        "Could you get in english the plot from the movie you just advised?",
        TMDB,
        history=_EUTHANASIA_TOP,
        standalone_must_contain=("sea inside",),
        expected_request=(
            RequestExpectation("movie_details", fields=(("title", "sea inside"),)),
            RequestExpectation("movie_details", fields=(("title", "mar adentro"),)),
        ),
    ),
    RoutingCase(
        "Chi ha diretto Oppenheimer e chi c'è nel cast?",
        TMDB,
        # Director and main cast come with every `movie_details` (credits always appended).
        expected_request=RequestExpectation("movie_details", fields=(("title", "oppenheimer"),)),
    ),
    RoutingCase(
        "Su quale piattaforma posso vedere Dune - Parte Due in Italia?",
        TMDB,
        expected_request=RequestExpectation("movie_details", fields=(("title", "dune"),), facets=("watch_providers",)),
    ),
    RoutingCase(
        "Quali film sono di tendenza questa settimana?",
        TMDB,
        expected_request=RequestExpectation("trending", fields=(("media", "movie"), ("window", "week"))),
    ),
    RoutingCase(
        "Mostrami il trailer di Past Lives",
        TMDB,
        expected_request=RequestExpectation("movie_details", fields=(("title", "past lives"),), facets=("videos",)),
    ),
    RoutingCase(
        "Quante stagioni ha Breaking Bad?",
        TMDB,
        expected_request=RequestExpectation("tv_details", fields=(("title", "breaking bad"),)),
    ),
    RoutingCase(
        "E dove lo posso vedere in streaming?",
        TMDB,
        history=_INTERSTELLAR,
        standalone_must_contain=("interstellar",),
        expected_request=RequestExpectation(
            "movie_details",
            fields=(("title", "interstellar"),),
            facets=("watch_providers",),
        ),
    ),
    # Regressions from the real TMDb run (2026-10-22): both went to rag_search.
    RoutingCase(
        "Parlami del film Arrival",
        TMDB,
        expected_request=RequestExpectation("movie_details", fields=(("title", "arrival"),)),
    ),
    RoutingCase(
        "Dimmi qualcosa su Dune",
        TMDB,
        expected_request=(
            RequestExpectation("movie_details", fields=(("title", "dune"),)),
            RequestExpectation("search", fields=(("kind", "movie"), ("search_query", "dune"))),
        ),
    ),
    # A title used only as a reference for what to look for stays on the RAG.
    RoutingCase("Mi sono piaciuti i temi di Mare dentro: ci sono altri film che toccano le stesse questioni?", RAG),
    RoutingCase("Vorrei un film con l'atmosfera e il dilemma morale del Padrino, ma con un finale meno tragico", RAG),
    # From a MovieLens ranking to the first film's credits.
    RoutingCase(
        "E chi l'ha diretto?",
        TMDB,
        history=_TOP_RATED,
        standalone_must_contain=("shawshank",),
        expected_request=RequestExpectation("movie_details", fields=(("title", "shawshank"),)),
    ),
    # A person, no title and no history: ask instead of searching (went to rag_search before).
    RoutingCase("Oh, ma chi c'era in quel film di Sorrentino…", CLARIFY),
)
