"""The benchmark questions of the `cinema_sql` tool: the 30 questions of the phase-0 baseline plus extra ones for operations the baseline does not use.

Each question carries a PLAN: the `cinema_sql` arguments a planner would plausibly write (written by hand, NOT by an LLM: the planner is not
run, so which plan a real planner writes is not measured here). A step may take the id of a candidate that an earlier ambiguous step listed
(`pick`), as a planner would after reading the alternatives. `coverage` is the theoretical classification (what the tool can answer by
construction); the benchmark then measures what it actually answers. `manual` is my own reading of the real result against what I know of
the world: it is written after looking at the output and is NOT an automated check.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Step:
    arguments: dict[str, Any]
    pick: dict[str, Any] | None = None   # choose, among the candidates of the previous step, the one with these fields; pass its work_id/person_id


@dataclass(frozen=True)
class Question:
    key: str
    text: str
    baseline_no: int | None
    coverage: str                         # full | partial | none (theoretical)
    reason: str
    steps: tuple[Step, ...] = ()
    external: tuple[str, ...] = ()        # tools still needed for the part the local database cannot give
    expect: dict[str, Any] = field(default_factory=dict)
    manual: str = ""
    # False when the local answer is verified but does not settle what the user asked (decided by my manual reading): the external fallback stays needed.
    settles_the_question: bool = True


def S(**arguments: Any) -> Step:
    return Step(arguments)


def pick(year: int | None = None, **arguments: Any) -> Step:
    return Step(arguments, pick={"year": year} if year is not None else {})


QUESTIONS: tuple[Question, ...] = (
    Question("B01", "Quali film ha diretto Denis Villeneuve?", 1, "full", "filmography of a person", (S(operation="filmography", person="Denis Villeneuve", role="director", type="film"),),
             expect={"subject_name": "Denis Villeneuve"}),
    Question("B02", "Chi ha scritto la sceneggiatura di Blade Runner?", 2, "full", "crew of a work", (S(operation="crew", title="Blade Runner", role="writer"),),
             expect={"subject_title": "Blade Runner", "subject_year": 1982, "people": {"David Webb Peoples", "Hampton Fancher"}}),
    Question("B03", "Film con Cillian Murphy diretti da Christopher Nolan", 3, "full", "works shared by two people",
             (S(operation="collaborations", person="Christopher Nolan", person_b="Cillian Murphy", role="director", role_b="cast"),), expect={"subject_name": "Christopher Nolan"}),
    Question("B04", "Da quale libro è tratto Blade Runner?", 4, "full", "relations of a work", (S(operation="relations", title="Blade Runner"),),
             expect={"subject_title": "Blade Runner", "subject_year": 1982}),
    Question("B05", "Esiste un remake di The Thing?", 5, "full", "relations of a work, after choosing among homonyms",
             (S(operation="relations", title="The Thing"), pick(1982, operation="relations")), expect={"subject_year": 1982, "first_ambiguous": True}, settles_the_question=False),
    Question("B06", "Quali film fanno parte della saga di Alien?", 6, "full", "franchise by name", (S(operation="franchise", franchise="Alien"),),
             expect={"subject_name": "Alien"}),
    Question("B07", "Quanti Oscar ha vinto Parasite?", 7, "full", "awards of a work, after choosing among homonyms",
             (S(operation="awards", title="Parasite", outcome="won"), pick(2019, operation="awards", outcome="won", limit=50)), expect={"subject_year": 2019, "first_ambiguous": True}),
    Question("B08", "Chi ha vinto l'Oscar come miglior film nel 1995?", 8, "full", "awards by award name and year",
             (S(operation="awards", award="Oscar al miglior film", year_from=1995, year_to=1995, outcome="won"),), expect={"first_result_work": "Forrest Gump"}),
    Question("B09", "Distingui i film intitolati Crash (anno, regista, ID)", 9, "full", "homonym alternatives are the answer", (S(operation="find_work", title="Crash"),),
             expect={"status": "ambiguous", "min_candidates": 3}),
    Question("B10", "Qual è l'ID IMDb di Parasite?", 10, "full", "identifier of a work, after choosing among homonyms",
             (S(operation="find_work", title="Parasite"), pick(2019, operation="find_work")), expect={"imdb_id": "tt6751668", "first_ambiguous": True}),
    Question("B11", "Quanti film ha diretto Federico Fellini?", 11, "full", "count of a filmography", (S(operation="filmography", person="Federico Fellini", role="director"),),
             expect={"subject_name": "Federico Fellini"}),
    Question("B12", "Chi ha composto la colonna sonora di Inception?", 12, "full", "crew of a work", (S(operation="crew", title="Inception", role="composer"),),
             expect={"subject_title": "Inception", "people": {"Hans Zimmer"}}),
    Question("B13", "Punteggi della critica per i film di Villeneuve (preferenza reviews, 5 candidati)", 13, "partial", "the local database gives the films and their imdb ids; scores need OMDb",
             (S(operation="filmography", person="Denis Villeneuve", role="director", type="film", order="desc", limit=5),), ("omdb_search",), expect={"subject_name": "Denis Villeneuve", "ids_for_chain": True}),
    Question("B14", "Che Rotten Tomatoes ha Oppenheimer?", 14, "partial", "the local database only supplies the imdb id; the score is external",
             (S(operation="find_work", title="Oppenheimer"),), ("omdb_search",), expect={"subject_title": "Oppenheimer", "imdb_id": "tt15398776"}),
    Question("B15", "Regista, cast e punteggi della critica di Oppenheimer", 15, "partial", "director, cast and facts are local; scores are external",
             (S(operation="work_card", title="Oppenheimer"), S(operation="cast", title="Oppenheimer", limit=10)), ("omdb_search",), expect={"subject_title": "Oppenheimer"}),
    Question("B16", "Da cosa è tratto Oppenheimer e che punteggi ha?", 16, "partial", "the source is local; scores are external", (S(operation="relations", title="Oppenheimer"),), ("omdb_search",),
             expect={"subject_title": "Oppenheimer"}),
    Question("B17", "Remake di Solaris e relativo punteggio Metascore", 17, "partial", "relations are local (after choosing among homonyms); the score is external",
             (S(operation="relations", title="Solaris"), pick(2002, operation="relations")), ("omdb_search", "wikidata_search"), expect={"subject_year": 2002, "first_ambiguous": True}, settles_the_question=False),
    Question("B18", "Interviste a Villeneuve su Dune e suoi premi", 18, "partial", "awards are local; interviews are external", (S(operation="awards", person="Denis Villeneuve"),),
             ("youtube_search",), expect={"subject_name": "Denis Villeneuve"}),
    Question("B19", "Dove vedo Dune in streaming in Italia?", 19, "none", "streaming availability is not in the local database"),
    Question("B20", "Mostrami il trailer di Aftersun", 20, "none", "videos are not in the local database"),
    Question("B21", "Quali film escono questo mese?", 21, "none", "recent and upcoming releases are not in the local catalogue"),
    Question("B22", "Che voto medio ha Pulp Fiction?", 22, "none", "audience ratings are MovieLens, which the local cinema database does not contain"),
    Question("B23", "Quali sono i 10 film più votati di sempre?", 23, "none", "rankings by votes are MovieLens"),
    Question("B24", "Consigliami un film malinconico ambientato in Giappone", 24, "none", "semantic recommendation is the film index (RAG), not SQL"),
    Question("B25", "Film come Arrival ma senza alieni", 25, "none", "semantic recommendation is the film index (RAG), not SQL"),
    Question("B26", "Quante stagioni ha Breaking Bad?", 26, "full", "seasons of a series", (S(operation="series", title="Breaking Bad"),), expect={"subject_title": "Breaking Bad", "seasons": 5}),
    Question("B27", "Quando esce il prossimo episodio di Severance?", 27, "none", "future episodes are live data (TVmaze)"),
    Question("B28", "Storia della Nouvelle Vague", 28, "none", "encyclopedic prose is Wikipedia"),
    Question("B29", "Interviste al regista di Parasite", 29, "partial", "the director is local (after choosing among homonyms); interviews are external",
             (S(operation="find_work", title="Parasite"), pick(2019, operation="find_work")), ("youtube_search",), expect={"directors": ["Bong Joon-ho"], "first_ambiguous": True}),
    Question("B30", "Cast e episodi della seconda stagione di Dark", 30, "partial", "cast and the episode list are local when present; numbering and dates may need an external source",
             (S(operation="cast", title="Dark", type="series", limit=10), S(operation="series", title="Dark", season=2)), ("tvmaze_search",), expect={"subject_title": "Dark"}),
    # ---- extra questions: operations the baseline does not use ---------------------------------------------------------------------------
    Question("E01", "Con quali attori ha lavorato di più Christopher Nolan?", None, "full", "most frequent collaborators",
             (S(operation="collaborations", person="Christopher Nolan", role="director", role_b="cast", limit=5),), expect={"first_collaborator": "Michael Caine"}),
    Question("E02", "Chi è John Williams?", None, "full", "namesakes are alternatives", (S(operation="find_person", person="John Williams"),), expect={"status": "ambiguous", "min_candidates": 2}),
    Question("E03", "Chi recita ne Il padrino?", None, "full", "cast of a work", (S(operation="cast", title="Il padrino", limit=10),), expect={"subject_year": 1972, "total": 40}),
    Question("E04", "Chi ha prodotto Il padrino?", None, "full", "companies of a work", (S(operation="companies", title="Il padrino"),), expect={"subject_year": 1972}),
    Question("E05", "Dimmi di Inception", None, "partial", "structured facts are local; the plot is not", (S(operation="work_card", title="Inception"),), ("tmdb_search",), expect={"subject_title": "Inception"}),
    Question("E06", "Quali candidature all'Oscar ha avuto Christopher Nolan?", None, "full", "awards of a person", (S(operation="awards", person="Christopher Nolan", limit=50),),
             expect={"subject_name": "Christopher Nolan"}),
    Question("E07", "Elenco degli episodi della seconda stagione di Breaking Bad", None, "full", "episodes of a season", (S(operation="series", title="Breaking Bad", season=2),),
             expect={"subject_title": "Breaking Bad", "episodes": 13}),
    Question("E08", "Parlami del film Zzyzx Qwerty", None, "full", "an unknown title is reported as not found", (S(operation="find_work", title="Zzyzx Qwerty"),), expect={"status": "not_found"}),
    Question("E09", "Quanti film italiani del 1960 ci sono?", None, "full", "an aggregate over the approved views (free SQL)",
             (S(operation="sql", sql="SELECT count(DISTINCT work_id) AS n FROM v_work_country WHERE iso2 = ? AND role = 'origin' AND work_kind = 'film' AND work_year = ? LIMIT 1", params=["IT", 1960]),),
             expect={"sql_count": ("IT", 1960)}),
)


# My own reading of each real answer against what I know of the world, written AFTER looking at the output (not an automated check).
MANUAL: dict[str, str] = {
    "B01": "Corretto rispetto al database (9 film, 2000-2024). Rispetto al mondo reale ne mancano almeno 2 (Un 32 août sur terre, 1998; Polytechnique, 2009): non sono nel catalogo locale.",
    "B02": "Coincide con quanto noto (Hampton Fancher, David Webb Peoples).",
    "B03": "Coincide con quanto noto: i 6 film di Nolan con Cillian Murphy.",
    "B04": "Fonte registrata: «Il cacciatore di androidi» (titolo italiano del romanzo di Dick) e il seguito Blade Runner 2049: coerente; il tipo di legame non è distinto.",
    "B05": "Il database non dice «remake»: La cosa (1982) risulta basata sul film del 1951 e seguita dal film del 2011. Remake o prequel non si può affermare (nota relations): risposta parziale, la conferma richiede Wikipedia o Wikidata.",
    "B06": "9 membri registrati, tra cui un cortometraggio (Prologue: The Crossing) e una serie del 2025; i crossover con Predator non ci sono (non fanno parte della saga su Wikidata). Corretto rispetto al database.",
    "B07": "4 Oscar vinti (film, regista, sceneggiatura originale, film internazionale) più altri premi: coincide con il mondo reale. Senza l'anno il titolo è ambiguo (Mutanti, 1982, ha Parasite come titolo originale).",
    "B08": "Forrest Gump (cerimonia 1995, film del 1994): corretto; compare anche il film in lingua straniera (Sole ingannatore), giusto ma da distinguere per categoria.",
    "B09": "Alternative corrette: Crash 1996 (Cronenberg), Crash 2004 (Haggis), serie del 2008.",
    "B10": "tt6751668 coincide. Il titolo è ambiguo: serve un secondo passo dopo le alternative.",
    "B11": "23 opere come regista nel catalogo (cortometraggi ed episodi di film collettivi inclusi): non confrontato con una filmografia esterna.",
    "B12": "Hans Zimmer: coincide.",
    "B13": "Gli ultimi 5 film con gli id IMDb e TMDb pronti per OMDb coincidono con la filmografia recente reale di Villeneuve (Dune 2, Dune, Blade Runner 2049, Arrival, Sicario).",
    "B14": "L'id IMDb è corretto; il punteggio resta esterno (1 richiesta a OMDb per id invece di 2 per titolo).",
    "B15": "Regia, sceneggiatura, musica, generi, paesi e il cast (59 nomi, parziale) coincidono con quanto noto; i punteggi sono esterni.",
    "B16": "La fonte registrata è il libro «American Prometheus» col titolo italiano («Robert Oppenheimer, il padre della bomba atomica»): corretto.",
    "B17": "Il database registra Solaris (2002) come «basato su» il romanzo Solaris, non sul film del 1972: nessuna relazione di remake, quindi la domanda non è risolta dal solo database (resta Wikidata o Wikipedia).",
    "B18": "Un solo risultato (candidatura all'Oscar per Arrival): nel mondo reale i premi di Villeneuve sono molti di più. I premi registrati solo sul film non sono attribuiti alla persona (nota awards_person_scope): l'assenza non prova nulla.",
    "B26": "5 stagioni: corretto. I conteggi degli episodi NON sono affidabili (S1 8 righe/7 numerate contro 7 reali, S4 13/11 contro 13, S5 18/0 contro 16): lo dice la nota episode_duplicates.",
    "B29": "Bong Joon-ho: corretto (dopo la scelta tra gli omonimi).",
    "B30": "Cast di 15 nomi (parziale) e 8 episodi della seconda stagione di Dark (il numero coincide con la realtà) ma senza numerazione né date: la numerazione resterebbe da TVmaze.",
    "E01": "Michael Caine 8: coincide con i film reali di Nolan con Caine.",
    "E02": "John Williams 1903 e 1932: corretto, due persone distinte (il compositore del 1932 ha 107 crediti).",
    "E03": "40 nomi: il cast è parziale rispetto al film reale e senza ordine di rilievo (nota cast_order).",
    "E04": "Alfran Productions e Paramount: coincide; tra i distributori ci sono servizi di streaming, come registrati.",
    "E05": "Scheda coerente con quanto noto; i generi sono quelli registrati (compaiono anche Heist e Mystery).",
    "E06": "Solo candidature (Memento, Inception, Dunkirk): mancano le vittorie di Oppenheimer (film e regia), che il database ha sul film ma non sul nominato. Caso tipico in cui l'assenza non prova nulla: la nota awards_person_scope lo dice.",
    "E07": "13 episodi: corretto.",
    "E08": "Not found, senza dedurre che non esista.",
    "E09": "99 film italiani del 1960 nel catalogo: il numero reale è maggiore, il catalogo è incompleto.",
}
QUESTIONS = tuple(__import__("dataclasses").replace(q, manual=MANUAL.get(q.key, "")) for q in QUESTIONS)
