"""Routing cases: does the orchestrator pick `movie_db_search`, `rag_search`, `tmdb_search`,
`youtube_search` or `wikipedia_search`?

Each case runs only the domain classifier and the planning call (`_plan_turn`): no
tool is executed, so no SQL, embedding or rerank call happens.
"""
from __future__ import annotations

from dataclasses import dataclass, field

DB = "movie_db_search"
RAG = "rag_search"
TMDB = "tmdb_search"
YOUTUBE = "youtube_search"
WIKIPEDIA = "wikipedia_search"
TVMAZE = "tvmaze_search"
WIKIDATA = "wikidata_search"
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
class WikipediaExpectation:
    """Planned `wikipedia_search` arguments that answer the question.

    The arguments must validate as `WikipediaToolInput`, `topic` must contain the lowercase
    fragment, `kind`, `depth` and `language` must be among those listed (searches start in English
    whatever the language of the question, so by default only null or `en` pass). `year`, `page` and
    `sections` must stay empty unless `allowed` lists them: then each planned value must contain
    one of the fragments given for that field (values copied from the request or the
    conversation, never invented).
    """

    topic: str
    kinds: tuple[str, ...]
    depths: tuple[str, ...] = ("intro", "sections", "full")
    languages: tuple[str | None, ...] = (None, "en")
    allowed: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class TvmazeExpectation:
    """Planned `tvmaze_search` arguments that answer the question.

    The arguments must validate as `TvmazeToolInput`, `title` must contain the lowercase fragment and
    the planned facets must include every one of `facets`, plus at most those of `extra_facets`.
    `year` must stay empty unless `allowed` lists it: then the planned value must contain one of the
    fragments given for that field (copied from the request or the conversation, never invented).
    """

    title: str
    facets: tuple[str, ...]
    extra_facets: tuple[str, ...] = ()
    allowed: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class WikidataExpectation:
    """Planned `wikidata_search` arguments that answer the question.

    The arguments must validate as `WikidataToolInput`, `operation` must be the one expected and `title` must
    contain the lowercase fragment. `year`, `director`, `type`, `imdb_id` and `tmdb_id` must stay empty unless
    `allowed` lists the field: then the planned value must contain one of the fragments given for it (copied
    from the request or the conversation, never invented).
    """

    title: str
    operation: str
    allowed: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class RagExpectation:
    """The `k_finale` and `search_mode` the planner should set for a `rag_search` call.

    None means "must be left null" (the configured default); a tuple lists acceptable values.
    """

    k_finale: int | None | tuple[int | None, ...] = None
    search_mode: str | None | tuple[str | None, ...] = None


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
    # Wikipedia cases only: the planned arguments; a tuple lists acceptable alternatives.
    expected_wikipedia: WikipediaExpectation | tuple[WikipediaExpectation, ...] | None = None
    # TVmaze cases only: the planned arguments; a tuple lists acceptable alternatives.
    expected_tvmaze: TvmazeExpectation | tuple[TvmazeExpectation, ...] | None = None
    # Wikidata cases only: the planned arguments; a tuple lists acceptable alternatives.
    expected_wikidata: WikidataExpectation | tuple[WikidataExpectation, ...] | None = None
    # RAG cases only: the retrieval parameters in the planned arguments.
    expected_rag: RagExpectation | None = None
    # Other tools accepted as the FIRST step (the case is still judged on `expected_tool`'s arguments only
    # when that tool is the one chosen).
    alternative_first_tools: tuple[str, ...] = ()
    # TMDb requests accepted when TMDb (an alternative first tool) is chosen instead of `expected_tool`:
    # the planner must still name the film (`RequestExpectation`; a tuple lists alternatives).
    expected_alternative_request: RequestExpectation | tuple[RequestExpectation, ...] | None = None
    # Tools the plan must use in the turn: the first one or any `parts` entry of the planner's answer.
    also_uses: tuple[str, ...] = ()


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

_PARK_CHAN_WOOK = (
    {"role": "user", "content": "Chi è Park Chan-wook?"},
    {"role": "assistant", "content": "Park Chan-wook è un regista sudcoreano, autore di Oldboy (2003)."},
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
    # An actor named: never the RAG.
    RoutingCase(
        "Il film in cui Tom Hanks naufraga su un'isola deserta",
        TMDB,
        # The planner may also name the film itself (Cast Away): `movie_details` is accepted then.
        expected_request=(
            RequestExpectation("discover_movies"),
            RequestExpectation("search", fields=(("kind", "movie"), ("search_query", "tom hanks"))),
            RequestExpectation("movie_details", fields=(("title", "cast away"),)),
        ),
    ),
    RoutingCase("Vorrei un film su un ex killer che cerca la redenzione in un paesino di montagna", RAG),
    RoutingCase("E degli anni '90?", DB, history=_HORROR_80S, standalone_must_contain=("horror", "90")),
    # Follow-up in another language that acts on the film just suggested: once blocked as off-topic.
    # A detailed plot is encyclopedic (rule 1c, added after this case): Wikipedia; a short synopsis stays on TMDb.
    RoutingCase(
        "Could you get in english the plot from the movie you just advised?",
        WIKIPEDIA,
        history=_EUTHANASIA_TOP,
        standalone_must_contain=("sea inside",),
        expected_wikipedia=WikipediaExpectation(
            "sea inside", kinds=("film",), depths=("sections", "full"), allowed=(("year", "2004"),)
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
    # Seasons of an identified series are structured data: TVmaze (rule 1e), not TMDb (it was a TMDb case before 1e).
    RoutingCase(
        "Quante stagioni ha Breaking Bad?",
        TVMAZE,
        expected_tvmaze=TvmazeExpectation("breaking bad", facets=("seasons",), extra_facets=("info",)),
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
    # A title used only as a reference never goes to the RAG: TMDb similar/recommendations.
    RoutingCase(
        "Mi sono piaciuti i temi di Mare dentro: ci sono altri film che toccano le stesse questioni?",
        TMDB,
        expected_request=(
            RequestExpectation("movie_details", fields=(("title", "mare dentro"),), facets=("similar",)),
            RequestExpectation("movie_details", fields=(("title", "mare dentro"),), facets=("recommendations",)),
        ),
    ),
    RoutingCase(
        "Vorrei un film con l'atmosfera e il dilemma morale del Padrino, ma con un finale meno tragico",
        TMDB,
        expected_request=(
            RequestExpectation("movie_details", fields=(("title", "padrino"),), facets=("similar",)),
            RequestExpectation("movie_details", fields=(("title", "padrino"),), facets=("recommendations",)),
            RequestExpectation("movie_details", fields=(("title", "godfather"),), facets=("recommendations",)),
            RequestExpectation("movie_details", fields=(("title", "godfather"),), facets=("similar",)),
        ),
    ),
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
        expected_rag=RagExpectation(k_finale=(None, 1), search_mode=(None, "hybrid")),
        # The planner may recognise the film (The Truman Show, 1998): TMDb is accepted when it names it.
        alternative_first_tools=(TMDB,),
        expected_alternative_request=(
            RequestExpectation("movie_details", fields=(("title", "truman show"),)),
            RequestExpectation("search", fields=(("kind", "movie"), ("search_query", "truman"))),
        ),
    ),
    # `search_mode`: hybrid only when concrete words must appear in the plot.
    RoutingCase(
        "Trovami i film dove c'è un personaggio che si chiama Hannibal Lecter",
        RAG,
        expected_rag=RagExpectation(k_finale=(None,), search_mode="hybrid"),
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
    # Encyclopedic information TMDb does not have (rule 1c): depth is the planner's first guess.
    RoutingCase(
        "Raccontami la vita e la carriera di Park Chan-wook",
        WIKIPEDIA,
        expected_wikipedia=WikipediaExpectation("park chan-wook", kinds=("person",), depths=("sections", "full")),
    ),
    RoutingCase(
        "Com'è nata la Nouvelle Vague e quali sono state le sue influenze?",
        WIKIPEDIA,
        # The default edition is English: the planner writes the English title of the page.
        expected_wikipedia=tuple(
            WikipediaExpectation(fragment, kinds=("topic",)) for fragment in ("nouvelle vague", "new wave")
        ),
    ),
    RoutingCase(
        "Come è stato prodotto Blade Runner? Voglio la storia della lavorazione",
        WIKIPEDIA,
        expected_wikipedia=WikipediaExpectation("blade runner", kinds=("film",), depths=("sections", "full")),
    ),
    # A follow-up on a person named in the conversation: the title may come from the history.
    RoutingCase(
        "Parlami meglio della sua formazione",
        WIKIPEDIA,
        history=_PARK_CHAN_WOOK,
        standalone_must_contain=("park chan-wook",),
        expected_wikipedia=WikipediaExpectation(
            "park chan-wook", kinds=("person",), depths=("sections", "full"), allowed=(("page", "park chan-wook"),)
        ),
    ),
    # A local topic: the Italian edition may be asked straight away, English is fine too.
    RoutingCase(
        "Raccontami la storia del doppiaggio italiano nel cinema degli anni Trenta",
        WIKIPEDIA,
        expected_wikipedia=(
            WikipediaExpectation("dubbing", kinds=("topic",), languages=(None, "en", "it")),
            WikipediaExpectation("doppiaggio", kinds=("topic",), languages=(None, "en", "it")),
        ),
    ),
    # Regressions of the live run (2026-10-25): TMDb alone cannot say which director made which segment
    # of an anthology, nor how live action and animation alternate; these stopped at `tmdb_search`.
    RoutingCase(
        "Quali cortometraggi compongono Three Extremes (2004) e chi ha diretto ciascun segmento?",
        WIKIPEDIA,
        expected_wikipedia=WikipediaExpectation(
            "three extremes", kinds=("film",), depths=("sections", "full"), allowed=(("year", "2004"),)
        ),
    ),
    RoutingCase(
        "Chi ha diretto i singoli segmenti di Paris, je t'aime (2006) e quanti sono complessivamente?",
        WIKIPEDIA,
        expected_wikipedia=WikipediaExpectation(
            "paris", kinds=("film",), depths=("sections", "full"), allowed=(("year", "2006"),)
        ),
    ),
    RoutingCase(
        "In The Congress (2013), come si alternano la parte in live action e quella animata, e quale "
        "ruolo ha il personaggio interpretato da Robin Wright?",
        WIKIPEDIA,
        # Who plays the character is TMDb data (rule 1c): either tool may come first.
        alternative_first_tools=(TMDB,),
        also_uses=(WIKIPEDIA, TMDB),
        expected_wikipedia=WikipediaExpectation(
            "congress", kinds=("film",), depths=("sections", "full"), allowed=(("year", "2013"),)
        ),
    ),
    # A comparison with the work a film comes from.
    RoutingCase(
        "Quali sono i principali cambiamenti narrativi tra il romanzo Solaris di Stanisław Lem e il "
        "film di Tarkovskij del 1972?",
        WIKIPEDIA,
        expected_wikipedia=WikipediaExpectation(
            "solaris", kinds=("film", "topic"), depths=("sections", "full"), allowed=(("year", "1972"),)
        ),
    ),
    # Controls: structured data TMDb gives well stays on TMDb, also for the same films.
    RoutingCase(
        "Quanto dura Paris, je t'aime?",
        TMDB,
        expected_request=RequestExpectation("movie_details", fields=(("title", "paris"),)),
    ),
    RoutingCase(
        "Chi recita in The Congress?",
        TMDB,
        expected_request=RequestExpectation("movie_details", fields=(("title", "congress"),)),
    ),
    RoutingCase(
        "Chi ha diretto Solaris, quello del 1972?",
        TMDB,
        expected_request=RequestExpectation("movie_details", fields=(("title", "solaris"),)),
    ),
    # Needs both tools: who plays whom is structured data (TMDb credits), the episodes are not.
    RoutingCase(
        "Quali episodi compongono The Ballad of Buster Scruggs (2018) e quali attori interpretano i "
        "protagonisti di ciascun episodio?",
        WIKIPEDIA,
        alternative_first_tools=(TMDB,),
        also_uses=(WIKIPEDIA, TMDB),
        expected_wikipedia=WikipediaExpectation(
            "buster scruggs", kinds=("film",), depths=("sections", "full"), allowed=(("year", "2018"),)
        ),
    ),
    # A trilogy that is not a TMDb collection: it starts from Wikipedia (TMDb answered not_found).
    RoutingCase(
        "Quali film compongono la trilogia della vendetta di Park Chan-wook e in quale ordine sono usciti?",
        WIKIPEDIA,
        expected_wikipedia=tuple(
            WikipediaExpectation(fragment, kinds=("topic", "film", "person"))
            for fragment in ("vengeance", "vendetta", "park chan")
        ),
    ),
    # Boundary: a filmography is a TMDb search by person, not an encyclopedic reading.
    RoutingCase(
        "Dammi la filmografia di Park Chan-wook",
        TMDB,
        expected_request=(
            RequestExpectation("person_details", fields=(("name", "park chan-wook"),)),
            RequestExpectation("discover_movies"),
        ),
    ),
    # TVmaze (rule 1e): structured data of one identified series.
    RoutingCase(
        "Quanti episodi ha la stagione 2 di Severance e quando sono usciti?",
        TVMAZE,
        expected_tvmaze=TvmazeExpectation("severance", facets=("episodes",), extra_facets=("seasons", "info")),
    ),
    RoutingCase(
        "Chi recita in Killing Eve e quali personaggi interpretano?",
        TVMAZE,
        expected_tvmaze=TvmazeExpectation("killing eve", facets=("cast",), extra_facets=("info",)),
    ),
    RoutingCase(
        "Quando esce il prossimo episodio di The Bear?",
        TVMAZE,
        expected_tvmaze=TvmazeExpectation("the bear", facets=("next",), extra_facets=("info",)),
    ),
    # Mixed: the cast is structured series data, where to watch it is streaming (TMDb).
    RoutingCase(
        "Chi c'è nel cast di Dark e dove posso vederla in streaming?",
        TVMAZE,
        alternative_first_tools=(TMDB,),
        also_uses=(TVMAZE, TMDB),
        expected_tvmaze=TvmazeExpectation("dark", facets=("cast",), extra_facets=("info",)),
        expected_alternative_request=RequestExpectation("tv_details", fields=(("title", "dark"),), facets=("watch_providers",)),
    ),
    # Boundaries: the series is named but the request is not structured data: TMDb keeps it (rule 1).
    RoutingCase(
        "Consigliami serie simili a Dark",
        TMDB,
        expected_request=(
            RequestExpectation("tv_details", fields=(("title", "dark"),), facets=("similar",)),
            RequestExpectation("tv_details", fields=(("title", "dark"),), facets=("recommendations",)),
        ),
    ),
    RoutingCase(
        "Dove posso vedere The Bear in Italia?",
        TMDB,
        expected_request=RequestExpectation("tv_details", fields=(("title", "the bear"),), facets=("watch_providers",)),
    ),
    RoutingCase(
        "Mostrami il trailer della serie Severance",
        TMDB,
        expected_request=RequestExpectation("tv_details", fields=(("title", "severance"),), facets=("videos",)),
    ),
    # Wikidata (rule 1f): declared relations between works, and homonyms told apart.
    RoutingCase(
        "Da quale libro è tratto Blade Runner?",
        WIKIDATA,
        expected_wikidata=WikidataExpectation("blade runner", "relations"),
    ),
    RoutingCase(
        "Quali remake ha The Departed?",
        WIKIDATA,
        expected_wikidata=WikidataExpectation("the departed", "relations"),
    ),
    RoutingCase(
        "Cosa viene dopo La cosa di John Carpenter del 1982 nella sua serie e a quale franchise appartiene?",
        WIKIDATA,
        expected_wikidata=WikidataExpectation("thing", "relations", allowed=(("year", "1982"),)),
    ),
    RoutingCase(
        "Esistono più film che si chiamano Crash? Come li distinguo?",
        WIKIDATA,
        expected_wikidata=WikidataExpectation("crash", "resolve"),
    ),
    # Boundary: the film is named but the request is not about relations between works: TMDb keeps it (rule 1).
    RoutingCase(
        "Quanto dura Blade Runner 2049 e chi l'ha diretto?",
        TMDB,
        expected_request=RequestExpectation("movie_details", fields=(("title", "blade runner 2049"),)),
    ),
)
