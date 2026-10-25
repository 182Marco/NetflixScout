"""Routing cases: does the orchestrator pick `movie_db_search`, `rag_search`, `tmdb_search` or
`youtube_search`?

Each case runs only the domain classifier and the planning call (`_plan_turn`): no
tool is executed, so no SQL, embedding or rerank call happens.
"""
from __future__ import annotations

from dataclasses import dataclass, field

DB = "movie_db_search"
RAG = "rag_search"
TMDB = "tmdb_search"
YOUTUBE = "youtube_search"
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
class VideoExpectation:
    """Planned `youtube_search` arguments that answer the question.

    The arguments must validate as `YoutubeToolInput`, `title` must contain the lowercase
    fragment and the planned kinds must include every one of `kinds`, plus at most those of
    `extra_kinds`. `year`, `director`, `cast` and `alternative_titles` must stay empty unless
    `allowed` lists them: then each planned value must contain one of the fragments given for
    that field (values copied from the request or the conversation, never invented).
    """

    title: str
    kinds: tuple[str, ...]
    extra_kinds: tuple[str, ...] = ()
    allowed: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class RagExpectation:
    """The `k_finale` the planner should set for a `rag_search` call.

    None means "must be left null" (the configured default); a tuple lists acceptable values.
    """

    k_finale: int | None | tuple[int | None, ...] = None


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
    # YouTube cases only: the planned arguments; a tuple lists acceptable alternatives.
    expected_video: VideoExpectation | tuple[VideoExpectation, ...] | None = None
    # RAG cases only: the retrieval parameters in the planned arguments.
    expected_rag: RagExpectation | None = None


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

_AFTERSUN_NO_TRAILER = (
    {"role": "user", "content": "Mostrami il trailer di Aftersun"},
    {
        "role": "assistant",
        "content": "TMDb non riporta trailer per Aftersun (2022). Vuoi che lo cerchi su YouTube?",
    },
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
    # Trailers stay on TMDb (official links) unless the user asks for YouTube (rule 1b).
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
    # Videos about an identified film start from YouTube (rule 1b). The director is not named:
    # `director` stays empty, even if the planner knows who directed the film.
    RoutingCase(
        "Trovami un'intervista al regista di Past Lives",
        YOUTUBE,
        expected_video=VideoExpectation("past lives", kinds=("director_interview",)),
    ),
    RoutingCase(
        "Ci sono interviste a Cillian Murphy su Oppenheimer?",
        YOUTUBE,
        expected_video=VideoExpectation(
            "oppenheimer",
            kinds=("cast_interview",),
            allowed=(("cast", "cillian murphy"),),
        ),
    ),
    RoutingCase(
        "Ci sono video del dietro le quinte di Barbie?",
        YOUTUBE,
        expected_video=(
            VideoExpectation("barbie", kinds=("behind_the_scenes",), extra_kinds=("making_of",)),
            VideoExpectation("barbie", kinds=("making_of",), extra_kinds=("behind_the_scenes",)),
        ),
    ),
    RoutingCase(
        "Cercami su YouTube il trailer di Past Lives",
        YOUTUBE,
        expected_video=VideoExpectation("past lives", kinds=("trailer",)),
    ),
    # TMDb had no trailer and the answer offered YouTube: accepting the offer searches there.
    RoutingCase(
        "Sì, cercalo pure",
        YOUTUBE,
        history=_AFTERSUN_NO_TRAILER,
        standalone_must_contain=("aftersun",),
        expected_video=VideoExpectation("aftersun", kinds=("trailer",), allowed=(("year", "2022"),)),
    ),
    # Only the Italian title is given: no original or English title, year, director or cast
    # may be added from the planner's own knowledge.
    RoutingCase(
        "Ci sono interviste al cast di Il ragazzo e l'airone?",
        YOUTUBE,
        expected_video=VideoExpectation("airone", kinds=("cast_interview",)),
    ),
    # A title written in parentheses by the user may be copied, nothing else.
    RoutingCase(
        "Vorrei un'intervista al regista di La zona d'interesse (The Zone of Interest)",
        YOUTUBE,
        expected_video=(
            VideoExpectation(
                "zona d", kinds=("director_interview",), allowed=(("alternative_titles", "zone of interest"),),
            ),
            VideoExpectation(
                "zone of interest", kinds=("director_interview",), allowed=(("alternative_titles", "zona d"),),
            ),
        ),
    ),
    # Real failure (2026-10-24): a film by actor judged by critics went to movie_db_search, which
    # has no people nor critics, and the interview was never looked for. The first step is TMDb
    # (discover by person); the interview is a later step of the same turn.
    RoutingCase(
        "Voglio un film con Leonardo Di Caprio accolto male dalla critica. "
        "Trovami anche un'intervista all'attore che parla di quel film",
        TMDB,
        expected_request=RequestExpectation("discover_movies"),
    ),
    RoutingCase(
        "Quali sono i film di Leonardo DiCaprio con i voti più bassi?",
        TMDB,
        expected_request=RequestExpectation("discover_movies"),
    ),
    # `k_finale` chosen by the planner (RagToolInput): the count asked for, nothing otherwise.
    RoutingCase(
        "Dammi 5 film sul rapporto tra un padre e un figlio, malinconici e lenti",
        RAG,
        expected_rag=RagExpectation(k_finale=5),
    ),
    RoutingCase(
        "Consigliami un film sulla solitudine nello spazio",
        RAG,
        expected_rag=RagExpectation(k_finale=(None, 1)),
    ),
    RoutingCase(
        "Qual è quel film in cui il protagonista si chiama Truman Burbank e vive in uno show televisivo?",
        RAG,
        expected_rag=RagExpectation(k_finale=(None, 1)),
    ),
    # Data coverage (`CONFIG["orchestrator"]["data_coverage"]`): films after the last year a local
    # source covers must not start from RAG (to 2012) or MovieLens (to 2022).
    RoutingCase(
        "Quali sono i film più votati usciti nel 2024?",
        TMDB,
        expected_request=RequestExpectation("discover_movies"),
    ),
    RoutingCase(
        "Consigliami un film horror uscito nel 2020 con atmosfera claustrofobica",
        TMDB,
        expected_request=RequestExpectation("discover_movies"),
    ),
    RoutingCase(
        "Qual è il film con il voto medio più alto del 2023?",
        TMDB,
        expected_request=RequestExpectation("discover_movies"),
    ),
    RoutingCase(
        "Dammi 3 film di fantascienza cupi usciti dopo il 2018",
        TMDB,
        expected_request=RequestExpectation("discover_movies"),
    ),
    RoutingCase(
        "Quali sono le migliori commedie degli ultimi due anni?",
        TMDB,
        expected_request=RequestExpectation("discover_movies"),
    ),
    # Controls: inside the covered years the local sources stay the start.
    RoutingCase("Qual è il film con il voto medio più alto del 2005?", DB),
    RoutingCase("Quali sono i film più votati usciti nel 2021?", DB),
    RoutingCase("Consigliami un film del 2008 su un robot che si innamora di un umano", RAG),
)
