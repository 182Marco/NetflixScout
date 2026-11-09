"""The matrix of docs/cinema_db/PLANNER_PREFERENCE_MATRIX.md as data: a question, the `content_type` it is asked under and what the REAL planner must do.

`Expect`: `conflict` = the setting prevails over an explicit request of the other kind (a conflict is declared, no tool of the excluded kind runs, nothing is looked up
in the other domain); `require` = tools that must be EXECUTED; `forbid` = tools that must NOT be executed; `one_rag` = exactly one of the two RAGs (an ambiguous
recommendation must not query both); `cinema_op` = operation of `cinema_sql` when it is required. A step the guard had to block counts against the planner
(`blocked_attempts` must be 0): the planner has to produce a coherent plan by itself."""
from __future__ import annotations

from dataclasses import dataclass, field

FILM, SERIES, BOTH = "film", "series", "both"
RAGS = ("rag_search", "series_rag_search")


@dataclass(frozen=True)
class Expect:
    conflict: bool = False
    require: tuple[str, ...] = ()
    forbid: tuple[str, ...] = ()
    one_rag: bool = False
    cinema_op: str | None = None
    # FASE 23: arguments the executed `cinema_sql` call of `cinema_op` must carry (exact values), e.g. {"type": "film"}; the value "absent" = the argument must not be set
    cinema_args: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class PrefCase:
    id: str
    question: str
    cells: dict[str, Expect]
    critical: bool = False
    history: tuple[dict[str, str], ...] = field(default_factory=tuple)


C = Expect(conflict=True)
RAG_ONLY = Expect(require=("rag_search",), forbid=("series_rag_search", "tvmaze_search"))
SERIES_ONLY = Expect(require=("series_rag_search",), forbid=("rag_search",))
TVMAZE = Expect(require=("tvmaze_search",), forbid=RAGS)
MOVIELENS = Expect(require=("cinema_sql",), forbid=RAGS, cinema_op="movielens")

CASES: tuple[PrefCase, ...] = (
    PrefCase("Q01", "Consigliami qualcosa su un professore di chimica che produce droga",
             {FILM: Expect(require=("rag_search",), forbid=("series_rag_search", "tvmaze_search")), SERIES: SERIES_ONLY, BOTH: Expect(one_rag=True)}),
    PrefCase("Q02", "Consigliami un thriller psicologico lento e malinconico",
             {FILM: RAG_ONLY, SERIES: SERIES_ONLY, BOTH: Expect(one_rag=True)}),
    PrefCase("Q03", "Film come Matrix ma senza i seguiti", {FILM: RAG_ONLY, SERIES: C, BOTH: RAG_ONLY}, critical=True),
    PrefCase("Q04", "Serie come Dark ma senza viaggi nel tempo", {FILM: C, SERIES: SERIES_ONLY, BOTH: SERIES_ONLY}, critical=True),
    PrefCase("Q05", "Quante stagioni ha Breaking Bad?", {FILM: C, SERIES: TVMAZE, BOTH: TVMAZE}, critical=True),
    PrefCase("Q06", "Quando esce il prossimo episodio di House of the Dragon?", {FILM: C, BOTH: TVMAZE}, critical=True),
    PrefCase("Q07", "Elencami gli episodi della seconda stagione di Lost", {SERIES: TVMAZE}, critical=True),
    PrefCase("Q08", "Trovami una serie su un detective in Islanda e dimmi quante stagioni ha",
             {FILM: C, SERIES: Expect(require=("series_rag_search", "tvmaze_search"), forbid=("rag_search",)),
              BOTH: Expect(require=("series_rag_search", "tvmaze_search"), forbid=("rag_search",))}, critical=True),
    PrefCase("Q09", "Un film di Christopher Nolan con una trama intricata sul tempo, e chi sono gli attori",
             {FILM: Expect(require=("rag_search",), forbid=("series_rag_search", "tvmaze_search")), SERIES: C,
              BOTH: Expect(require=("rag_search",), forbid=("series_rag_search", "tvmaze_search"))}),
    PrefCase("Q10", "I 10 film più votati dagli utenti", {FILM: MOVIELENS, SERIES: C, BOTH: MOVIELENS}, critical=True),
    PrefCase("Q11", "Qual è il genere con il voto medio più alto secondo gli utenti?",
             {SERIES: C, BOTH: Expect(require=("cinema_sql",), forbid=RAGS, cinema_op="movielens")}, critical=True),
    PrefCase("Q12", "Chi ha diretto Parasite e quali premi ha vinto?", {BOTH: Expect(require=("cinema_sql",), forbid=RAGS)}),
    PrefCase("Q13", "Voglio un film e una serie sul tema della memoria perduta",
             {FILM: Expect(require=("rag_search",), forbid=("series_rag_search",)), SERIES: Expect(require=("series_rag_search",), forbid=("rag_search",)),
              BOTH: Expect(require=RAGS)}, critical=True),
    PrefCase("Q14", "Punteggi Rotten Tomatoes di Dune", {BOTH: Expect(require=("omdb_search",), forbid=RAGS)}),
    PrefCase("Q15", "Intervista al regista di Parasite", {BOTH: Expect(require=("youtube_search",), forbid=RAGS)}),
    PrefCase("Q16", "Elencami gli episodi della serie Zorblax Quest", {SERIES: Expect(forbid=("rag_search",), require=())}),
    # FASE 23: the population of `ratings` (no title) and `by_tag` follows the content type; an explicit request of the other kind is a conflict
    PrefCase("Q19", "Qual è la classifica dei titoli meglio votati dal pubblico su IMDb?",
             {FILM: Expect(require=("cinema_sql",), forbid=RAGS, cinema_op="ratings", cinema_args=(("type", "film"),)),
              SERIES: Expect(require=("cinema_sql",), forbid=RAGS, cinema_op="ratings", cinema_args=(("type", "series"),)),
              BOTH: Expect(require=("cinema_sql",), forbid=RAGS, cinema_op="ratings")}, critical=True),
    PrefCase("Q20", "Quali opere hanno ricevuto il tag 'time travel' dagli utenti?",
             {FILM: Expect(require=("cinema_sql",), forbid=RAGS, cinema_op="movielens", cinema_args=(("ml_mode", "by_tag"), ("type", "film"))),
              SERIES: Expect(require=("cinema_sql",), forbid=RAGS, cinema_op="movielens", cinema_args=(("ml_mode", "by_tag"), ("type", "series"))),
              BOTH: Expect(require=("cinema_sql",), forbid=RAGS, cinema_op="movielens", cinema_args=(("ml_mode", "by_tag"), ("type", "absent")))}, critical=True),
    PrefCase("Q21", "Quali serie TV hanno ricevuto il tag 'time travel' dagli utenti?",
             {FILM: C, SERIES: Expect(require=("cinema_sql",), forbid=RAGS, cinema_op="movielens", cinema_args=(("ml_mode", "by_tag"), ("type", "series"))),
              BOTH: Expect(require=("cinema_sql",), forbid=RAGS, cinema_op="movielens", cinema_args=(("ml_mode", "by_tag"), ("type", "series")))}, critical=True),
    PrefCase("Q22", "Quali film hanno ricevuto il tag 'time travel' dagli utenti?",
             {FILM: Expect(require=("cinema_sql",), forbid=RAGS, cinema_op="movielens", cinema_args=(("ml_mode", "by_tag"), ("type", "film"))), SERIES: C,
              BOTH: Expect(require=("cinema_sql",), forbid=RAGS, cinema_op="movielens", cinema_args=(("ml_mode", "by_tag"), ("type", "film")))}, critical=True),
    PrefCase("Q17", "E una serie con una trama simile a Dark?", {SERIES: SERIES_ONLY},
             history=({"role": "user", "content": "Film come Matrix ma senza i seguiti"}, {"role": "assistant", "content": "Ti propongo Dark City e eXistenZ."})),
    PrefCase("Q18", "Come Inception ma in formato serie", {FILM: C, SERIES: SERIES_ONLY, BOTH: SERIES_ONLY}),
)


def cells() -> list[tuple[PrefCase, str, Expect]]:
    """Critical cases first, then the rest; the order is the order of execution (the run is capped, so the important ones come first)."""
    flat = [(case, value, expect) for case in CASES for value, expect in case.cells.items()]
    return sorted(flat, key=lambda cell: (not cell[0].critical, cell[0].id))
