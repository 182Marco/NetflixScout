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
    "Impostazioni dell'utente per QUESTO turno: sono VINCOLANTI e prevalgono su qualunque richiesta esplicita che le contraddica, "
    "anche se le risposte precedenti della conversazione hanno uno stile diverso; valgono anche per il campo reason delle liste. "
    "Se la risposta comincia con una frase che dichiara un conflitto tra la richiesta e un'impostazione, quella frase è già scritta: "
    "non ripeterla, continua dalla parte compatibile della richiesta e non eseguire mai la parte in conflitto. Riguardano la forma "
    "della risposta e cosa mettere in evidenza, mai i fatti: tutte le regole sui dati e sui limiti restano valide e prevalgono. "
    "Non spiegare mai da dove vengono i dati."
)

PLANNER_INTRO: Final = (
    "Impostazioni dell'utente per questo turno (valori scelti o predefiniti): sono VINCOLANTI e prevalgono su qualunque richiesta "
    "esplicita dell'utente che le contraddica, anche sulle regole di routing e sulle preferenze di fonte. Non cambiano k_finale e, salvo "
    "dove una impostazione dice espressamente di aggiungere un passo, non aggiungono tool né passi. Valori: {values}. "
    "CONFLITTI: se la richiesta chiede esplicitamente qualcosa che contraddice una impostazione (spoiler_plot disattivato e richiesta di "
    "finale, svolte, chi muore o cosa succede dopo; response_length diversa da quella impostata, es. «in breve», «una riga», «nel dettaglio», "
    "«approfondisci»; response_tone diverso, es. «parla come…»; approach opposto, es. «dimmene uno solo» con il confronto tra alternative; "
    "content_type diverso, es. un film richiesto con content_type serie; preferred_sources: richiesta esplicita di una fonte diversa), "
    "aggiungi al JSON il campo conflicts: [{{\"setting\": <id dell'impostazione>, \"requested\": <in poche parole cosa chiede>}}] e "
    "pianifica SOLO la parte compatibile (lo stesso tema nel tipo di contenuto impostato), mai la parte in conflitto. Con spoiler_plot "
    "disattivato e una richiesta di finale o svolte la parte compatibile esiste sempre: pianifica la ricerca del film identificato (la risposta "
    "darà solo premessa e contesto). Se davvero nulla è compatibile ritorna tool_name null e conflicts. Senza conflitti conflicts è [] o assente: una richiesta che non tocca le impostazioni "
    "non è un conflitto."
)

SPOILER: Final[dict[bool, str]] = {
    False: (
        "Spoiler disattivati: non rivelare svolte, esiti, finali, morti, identità nascoste o colpi di "
        "scena, nemmeno per allusione; di un film o una serie racconta solo la premessa, il contesto e "
        "l'atmosfera. Vale anche per trame, recensioni, sezioni della trama e titoli di video "
        "ricevuti dai tool: se un dato ricevuto contiene uno spoiler, non riportarlo. Se l'utente "
        "chiede esplicitamente uno spoiler (il finale, una svolta, chi muore, cosa succede dopo "
        "un certo punto), non rivelarlo MAI: la frase che dichiara il conflitto è già all'inizio della risposta, non ripeterla; "
        "rispondi con premessa, contesto e atmosfera."
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
        "Tono Homie: parli come un bro dei bassifondi pieno di intercalari slang fino alla caricatura. "
        "Usa volgarità continue come intercalari. Esalta con toni da ghetto ciò che va bene"
        "<Esempio> 'Fidati che spacca zio' </Esempio> e sminuisci con toni sgarbati e da buzzurro ciò che va male <Esempio> 'Fa cagare, bro' </Esempio>."
        "Con questi modi esalta ciò che si allinea alle richieste utente e dileggia ciò che si allontana."
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
        "Tipo di contenuto: film (vincolante). Presenta solo film; non presentare serie TV nemmeno se la richiesta le chiede."
    ),
    "series": (
        "Tipo di contenuto: serie TV (vincolante). Presenta solo serie TV; non presentare film nemmeno se la richiesta li chiede."
    ),
    "both": "Tipo di contenuto: nessuna preferenza, film e serie alla pari.",
}

CONTENT_PLANNER: Final[dict[str, str]] = {
    "film": (
        "Tipo di contenuto: film (vincolante). Non pianificare tool né operazioni su serie TV (tv_details, tv_season, tv_episode, discover_tv, "
        "search con kind tv): per tmdb_search usa le operazioni per film (movie_details, discover_movies, search con kind movie)."
    ),
    "series": (
        "Tipo di contenuto: serie TV (vincolante). Tratta ogni richiesta come una richiesta su serie, anche se descrive trama, genere, "
        "atmosfera o temi: per tmdb_search usa le operazioni per serie (tv_details, discover_tv, search con kind tv); non scegliere mai "
        "rag_search (copre solo film) né movie_db_search per cercare serie: il sistema li blocca. I dati strutturati di una serie identificata "
        "seguono la regola 1e; la preferenza non obbliga a usare tvmaze_search per ogni domanda sulle serie."
    ),
}

SOURCES_ANSWER: Final[dict[str, str]] = {
    "reviews": (
        "Fonti preferite: recensioni. Metti in evidenza ciò che i risultati riportano su recensioni e "
        "accoglienza e, se i risultati hanno i punteggi della critica (Metascore, Rotten Tomatoes), "
        "presentali come tali: sono solo punteggi, il testo delle recensioni della critica non c'è. "
        "Non presentare mai recensioni o voti di utenti (compreso il voto IMDb) come giudizio della "
        "critica. Se nei risultati non ci sono recensioni né punteggi della critica, dillo senza inventarne."
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
    # OMDb carries scores only: IMDb (audience), Metascore and Rotten Tomatoes (aggregates of
    # critics). Two of the three are the critics' judgement, the only one the app has, so it serves
    # `reviews`; the IMDb score is an audience score and overlaps MovieLens/TMDb ratings, which stay
    # first for `user ratings`. No review text (TMDb `reviews` has user reviews), no spoilers (the plot
    # field is never read), films and series.
    "omdb_search": "reviews",
    # TVmaze carries structured data of series (status, network, dates, seasons, episodes, cast): the
    # closest of the four preferences is `official information`, but the data is edited by a community,
    # not issued by the producers: to be reconsidered on real records (open question, AGENTS.md). No
    # reviews, ratings or interviews (its rating field is not read), no episode summaries (spoilers),
    # series only, so overlap is with tmdb_search on series details, where the routing rule 1e decides.
    "tvmaze_search": "official information",
    # Wikidata carries declared relations between works (based on, derived works, order in a series,
    # franchise) and the identity of a work (year, director, ids): structured encyclopedic data edited
    # by a community, so `official information` is the closest of the four, like wikipedia_search, with
    # which it overlaps on adaptations and remakes (prose there, structure here; rule 1f decides, rule 1c
    # keeps the prose). It carries no reviews, ratings or interviews, no plot (so no spoilers; the
    # relations name other works, never how a story ends), films and series. No preference adds a call to it.
    "wikidata_search": "official information",
    # cinema_sql reads the local cinema database: structured encyclopedic facts (credits, relations, companies, awards, series structure) from Wikipedia
    # and Wikidata, like wikipedia_search and tmdb_search, so `official information`. Verified on the real data (docs/cinema_db/PHASE5_REPORT.md §2): no
    # audience rating (not `user ratings`), no critic score or review text (not `reviews`: awards are industry recognitions, not reviews), no interview, no
    # plot (so no spoilers), films and series. No preference adds a call to it; the routing rule 1g decides when it is the first tool.
    "cinema_sql": "official information",
}

SOURCES_PLANNER: Final[dict[str, str]] = {
    "reviews": (
        "Fonti preferite: recensioni. Se la richiesta chiede esplicitamente il giudizio o i punteggi della "
        "critica su un film o una serie identificati, vale la regola 1d: omdb_search come primo tool, "
        "prima di tmdb_search. Per film o serie consigliati «con ottime recensioni» (nessun titolo "
        "dato) vale l'eccezione della regola 1d: candidati da tmdb_search, poi un passo omdb_search per "
        "ciascuno dei primi cinque. Se scegli tmdb_search per un film o una serie identificati e la "
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
