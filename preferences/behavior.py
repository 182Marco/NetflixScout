"""PRIVATE behaviour of each setting: the instructions that reach the prompts. Never sent to a client.

One fragment per option of `fields.json` (a test checks the two match). The planner fragments only
say how to break ties between tools that already fit the request: the numbered routing rules and
the explicit request always come first, and a setting adds no tool call, with ONE declared
exception (owner's decision of 2026-10-27): the `interviews` source adds a `youtube_search` step
for an identified film or series (YouTube quota: at most `max_searches_per_turn` searches).
The answer fragments shape the form of the answer and what to put forward, never the facts.
"""
from __future__ import annotations

from typing import Final

ANSWER_INTRO: Final = (
    "Impostazioni dell'utente per QUESTO turno: valgono anche se le risposte precedenti della "
    "conversazione hanno uno stile diverso e si applicano anche al campo reason delle liste. "
    "Riguardano la forma della risposta e cosa mettere in evidenza, mai i fatti: tutte le regole "
    "sui dati e sui limiti restano valide e prevalgono. Non spiegare mai da dove vengono i dati."
)

PLANNER_INTRO: Final = (
    "Preferenze dell'utente per questo turno: sono solo un criterio secondario tra tool che già "
    "servono alla richiesta. Non cambiano k_finale né gli altri parametri di ricerca e non "
    "prevalgono mai sull'intento della richiesta, sulle regole numerate o su una richiesta "
    "esplicita dell'utente. Salvo dove una preferenza dice espressamente di aggiungere un passo, "
    "non aggiungono tool né passi."
)

SPOILER: Final[dict[bool, str]] = {
    False: (
        "Spoiler disattivati: non rivelare svolte, esiti, finali, morti, identità nascoste o colpi di "
        "scena, nemmeno per allusione; di un film o una serie racconta solo la premessa, il contesto e "
        "l'atmosfera. Vale anche per trame, recensioni, sezioni della trama e titoli di video "
        "ricevuti dai tool: se un dato ricevuto contiene uno spoiler, non riportarlo. Se l'utente "
        "chiede esplicitamente uno spoiler (il finale, una svolta, chi muore, cosa succede dopo "
        "un certo punto), non rivelarlo MAI e dì in una frase, nella lingua della risposta, che la richiesta "
        "contraddice l'impostazione 'spoiler disattivati' e che per averlo deve attivare gli "
        "spoiler nelle impostazioni."
    ),
    True: (
        "Spoiler consentiti: puoi rivelare svolte e finali solo quando servono alla richiesta, e se lo "
        "fai segnalalo prima con un breve avviso; non anticiparli senza che servano."
    ),
}

LENGTH: Final[dict[str, str]] = {
    "short": (
        "Risposta breve, davvero: al massimo 3-5 frasi o un elenco corto, solo ciò che risponde alla "
        "domanda. Per ogni film titolo, anno e UNA riga di motivo; niente sinossi, cast, regia, voti o "
        "dettagli non chiesti, niente premesse, chiusure, offerte di approfondire o note sui limiti "
        "dei dati che non cambiano la risposta. Questa regola prevale su ogni altra istruzione di "
        "completezza e di dettaglio. Le avvertenze dovute per correttezza (spoiler negato, dato non "
        "verificato o mancante) restano, in mezza frase. La brevità non cambia quanti titoli "
        "presentare se l'utente ne chiede un numero."
    ),
    "medium": (
        "Risposta di media lunghezza: l'essenziale più il contesto utile, in uno o due paragrafi "
        "brevi o in un elenco con una riga per voce."
    ),
    "in-depth": (
        "Risposta approfondita: contesto, motivazioni e dettagli utili, ma sempre e solo con i dati "
        "ricevuti; la profondità non si ottiene con riempitivi né con informazioni non fondate."
    ),
}

TONE: Final[dict[str, str]] = {
    "technician": (
        "Tono tecnico: preciso, professionale e misurato; niente slang, niente esclamazioni, "
        "niente ironia."
    ),
    "Homie": (
        "Tono Homie: parli come un amico dei bassifondi, complice e appassionato di cinema, con "
        "slang marcato e volgarità continue come intercalari. Esalta con entusiasmo "
        "le opere apprezzate e sii cattivo sui difetti riconosciuti. Non "
        "inventare recensioni, consensi o giudizi che i dati non riportano, e non sacrificare "
        "accuratezza, chiarezza e pertinenza al tono."
        "I dati restano esatti, ma usa uno slang denso e caricaturale da bassifondi, con esclamazioni, intercalari e volgarità continue."
    ),
}

APPROACH: Final[dict[str, str]] = {
    "direct advice": (
        "Approccio consiglio diretto: dai una raccomandazione principale chiara, con la motivazione; "
        "cita altre opzioni solo se l'utente le chiede o se servono a spiegare la scelta. Se l'utente "
        "chiede un numero di titoli, presentane quel numero."
    ),
    "alternatives comparison": (
        "Approccio confronto tra alternative: confronta le alternative pertinenti tra i risultati "
        "ricevuti (di solito 2-3), dicendo in cosa differiscono rispetto alla richiesta, e chiudi con "
        "la scelta che consigli. Se i risultati hanno un solo candidato pertinente non inventare "
        "alternative. Se l'utente chiede un numero di titoli, presentane quel numero. Il confronto "
        "si fa sempre, anche se la lunghezza è breve: in quel caso è l'unica cosa oltre "
        "l'essenziale, compatto (una frase per alternativa sulla differenza chiave e la scelta)."
    ),
}

CONTENT_ANSWER: Final[dict[str, str]] = {
    "film": (
        "Tipo di contenuto preferito: film. Quando la richiesta non dice se vuole film o serie, metti "
        "in primo piano i film; una richiesta esplicita di serie, o un titolo che è una serie, "
        "prevale e va soddisfatta (se lo fai, dillo in una frase)."
    ),
    "series": (
        "Tipo di contenuto preferito: serie TV. Quando la richiesta non dice se vuole film o serie, "
        "metti in primo piano le serie; una richiesta esplicita di film, o un titolo che è un film, "
        "prevale e va soddisfatta (se lo fai, dillo in una frase)."
    ),
    "both": "Tipo di contenuto: nessuna preferenza, film e serie alla pari.",
}

CONTENT_PLANNER: Final[dict[str, str]] = {
    "film": (
        "Tipo di contenuto preferito: film. Se la richiesta non dice film o serie, per tmdb_search "
        "usa le operazioni per film (movie_details, discover_movies, search con kind movie)."
    ),
    "series": (
        "Tipo di contenuto preferito: serie TV. Se la richiesta non dice film o serie, per "
        "tmdb_search usa le operazioni per serie (tv_details, discover_tv, search con kind tv) e "
        "non scegliere rag_search, che copre solo film, né movie_db_search per cercare serie."
    ),
}

SOURCES_ANSWER: Final[dict[str, str]] = {
    "reviews": (
        "Fonti preferite: recensioni. Metti in evidenza ciò che i risultati riportano su recensioni e "
        "accoglienza. Non c'è la critica professionale: non presentare mai recensioni di utenti "
        "come giudizio della critica. Se nei risultati non ci sono recensioni, dillo senza inventarne."
    ),
    "interviews": (
        "Fonti preferite: interviste. Metti in evidenza interviste e dichiarazioni dirette di registi, "
        "cast e autori presenti nei risultati (video con il loro titolo e canale). Non "
        "attribuire dichiarazioni che i risultati non riportano; se non ce ne sono, dillo."
    ),
    "official information": (
        "Fonti preferite: informazioni ufficiali. Metti in evidenza i dati ufficiali presenti nei "
        "risultati (regia, cast, durata, uscita, produzione, sinossi, contesto)."
    ),
    "user ratings": (
        "Fonti preferite: voti degli utenti. Metti in evidenza i voti presenti nei risultati "
        "dichiarando che sono voti del pubblico, mai della critica; senza nominare il database o il sito."
    ),
}

SOURCES_COMMON: Final = (
    "La preferenza sulle fonti non fa cercare altro e non sostituisce ciò che la domanda richiede: se "
    "la fonte preferita non compare nei risultati, dillo in una frase."
)

# Which tool carries which kind of source. A tool added later declares here the preference it serves
# first (`tests/test_preferences.py` checks every allowed tool is listed).
SOURCE_TOOLS: Final[dict[str, str]] = {
    "rag_search": "official information",
    "movie_db_search": "user ratings",
    "tmdb_search": "official information",
    "wikipedia_search": "official information",
    "youtube_search": "interviews",
}

SOURCES_PLANNER: Final[dict[str, str]] = {
    "reviews": (
        "Fonti preferite: recensioni. Se scegli tmdb_search per un film o una serie identificati e la "
        "richiesta ammette più tipi di dato, aggiungi la facet reviews alla stessa richiesta (nessun "
        "passo in più). Per Wikipedia l'accoglienza sta nelle sezioni di un articolo già scelto."
    ),
    "interviews": (
        "Fonti preferite: interviste. Se la richiesta riguarda un film o una serie identificati da un "
        "titolo (informazioni, 'parlami di X', dettagli; NON classifiche, raccomandazioni senza "
        "titolo, domande statistiche o sulla sola trama), aggiungi in parts anche un passo "
        "youtube_search per le interviste (kinds: director_interview e poi cast_interview; title e, "
        "solo se compaiono nella richiesta, nella conversazione o nei dati già ottenuti in questo "
        "turno, year, director e cast) e imposta more_steps true. È l'unica preferenza che aggiunge "
        "un passo; il tool applica da solo il limite di ricerche per turno. Se la richiesta chiede "
        "già video vale la regola 1b."
    ),
    "official information": (
        "Fonti preferite: informazioni ufficiali. Nessuna modifica al routing: le regole numerate già "
        "danno la priorità a tmdb_search e wikipedia_search per i dati ufficiali."
    ),
    "user ratings": (
        "Fonti preferite: voti degli utenti. Se la richiesta ammette sia voti MovieLens sia voti TMDb, "
        "usa per primo il tool che la regola 2 già indica per i punteggi (movie_db_search); per un "
        "titolo identificato i voti arrivano già con tmdb_search."
    ),
}
