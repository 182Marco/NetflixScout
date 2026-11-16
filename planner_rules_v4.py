"""Planner rules of the integrated architecture: `cinema_sql` on a schema-4 file (MovieLens inside the database).

In schema-4 mode `build_app` replaces rule 1g (and its v3 addendum) by `CINEMA_SQL_V4_RULE`, organised by capability and with the MovieLens operations, and adds the
MovieLens list instructions to the final-answer rules of cinema_sql. Pure text: no imports.
"""
from __future__ import annotations

# Only the genres MovieLens uses (the tool validates them): listed in the rule because the planner must write one of them.
ML_GENRES_TEXT = "Action, Adventure, Animation, Children, Comedy, Crime, Documentary, Drama, Fantasy, Film-Noir, Horror, IMAX, Musical, Mystery, Romance, Sci-Fi, Thriller, War, Western"

CINEMA_SQL_V4_RULE = (
    "1g) MAPPA DEI SISTEMI. Tre sistemi centrali, locali (nessuna rete) e sempre la prima fonte per ciò che contengono: "
    "cinema_sql = dati STRUTTURATI su film, serie, persone, crediti, premi, saghe, relazioni, società, voti degli utenti e tutte le classifiche; "
    "rag_search (3) = ricerca SEMANTICA di film per trama, temi e atmosfera; series_rag_search (1h, se registrato) = ricerca SEMANTICA di serie, stagioni, episodi e film TV. "
    "Gli altri tool servono solo per ciò che i tre non hanno, hanno incompleto o dichiarano non verificato, o che va aggiornato: tmdb_search (novità, streaming, trailer, cast "
    "principale, «consigliati dal pubblico»), omdb_search (Metascore, Rotten Tomatoes, voto IMDb: 1d), tvmaze_search (numerazione, date e prossimo episodio di UNA serie: 1e), "
    "youtube_search, wikipedia_search (prosa: 1c), wikidata_search (relazioni tra opere come ripiego: 1f). Per ogni parte della richiesta chiedi prima al sistema che la contiene e "
    "solo per il dato che manca aggiungi il tool esterno, senza ripetergli ciò che il locale dà già; la 1g ha la precedenza sulle regole 1 e 1f per ciò che copre, MAI sulla 1e: PRIORITÀ FISSA, stagioni (quante sono), episodi, date di messa in onda, prossimo episodio, cast e rete di UNA serie sono SEMPRE di tvmaze_search, anche se la domanda sembra strutturale. "
    "cinema_sql contiene. (A) Persone e crediti: filmografia di una persona e quanti film ha fatto (filmography, con role e type se la richiesta li dice); regia, sceneggiatura, musica, "
    "fotografia, montaggio e produzione di un film o di una serie (crew: con più ruoli nella stessa domanda lascia role vuoto); se un attore ha recitato in un film, l'elenco completo del cast "
    "e il cast di opere che TMDb non ha (cast: senza ordine di rilievo né personaggi sempre presenti; billing_order, quando c'è, dà l'ordine dei primi e allora basta); le opere in comune di due "
    "persone e con chi una persona ha lavorato di più (collaborations). (B) Premi, candidature e vincitori di un'opera, di una persona o di una categoria (awards: un nome come «Oscar» si dà insieme al titolo o alla persona; se l'utente nomina una categoria («miglior regista», «miglior attore») metti in award nome del premio e categoria insieme, es. «Oscar miglior regista», altrimenti arrivano tutte le categorie; "
    "per l'anno della cerimonia year_from e year_to). (C) Relazioni: da quale opera è tratto un titolo e cosa viene prima o dopo nella serie (relations), le opere di una saga (franchise), le società (companies). "
    "(D) Identificare e schedare: find_work e find_person (anno, regista, identificativi, omonimi), work_card (scrittori, musica, generi, paesi, società, importi). "
    "(E) Voti degli utenti. Per «che voto ha X», «quanti voti ha», «com'è valutato» su UN titolo: ratings con il titolo (voto del pubblico e numero di voti, due fonti ciascuna con la propria scala; precede la regola 2). "
    "Per tutto il resto dei voti operation movielens (voti degli utenti su scala 1-5): ml_mode top_rated = film con il voto medio più alto, most_rated = più votati; entrambi con genre (uno di: " + ML_GENRES_TEXT + "), "
    "year_from e year_to, min_votes (predefinito 50); by_title = cerca un film per titolo o parte del titolo (anche film che il catalogo non ha, con status excluded e il motivo); by_tag = film con un tag degli "
    "utenti (es. «time travel»; tag in inglese; passa type film se chiede solo film, senza type include anche le serie); genre_stats = voto medio e numero di film per genere (con anni se la richiesta li dà). TUTTE le classifiche per genere, anno o tag usano movielens, anche quando "
    "l'utente dice «dagli utenti» o «meglio votati»: mai operation sql su v_work_rating (mescolerebbe scale diverse) né ratings senza titolo per questo. Ratings senza titolo (classifica dei voti IMDb) senza type mescola film e serie: per i migliori FILM passa sempre type film. Copertura: film fino al 2022 compreso e voti fino a ottobre 2023 (il 2023 è parziale): "
    "per film usciti dopo o per le novità tmdb_search. Le classifiche contengono solo film, corti e film TV; non hanno attori, registi, cast né filtri per persona (filmografie: filmography o tmdb_search; "
    "giudizi della critica: omdb_search o tmdb_search discover con max_rating o sort rating_desc). (F) Affidabilità: per ogni opera identity_level (verified = certa; rule_based = «identificata con buona probabilità»; uncertain = incerta, "
    "non presentarla come un fatto) e provenance (da dove viene un dato, ID alternativi, persone registrate come la stessa, candidati non attribuiti, che sono sospetti e non fatti). "
    "NON in cinema_sql: trama e descrizione; Metascore, Rotten Tomatoes e giudizio della critica (1d); recensioni; streaming e provider, trailer e video; novità e opere recenti non nell'archivio (tmdb_search); "
    "consigli e ricerche per temi (3, 1h); storia e produzione approfondite (1c). Una richiesta generica su un titolo identificato («parlami di X», «di cosa parla») resta alla regola 1: un solo passo tmdb_search; "
    "aggiungi cinema_sql solo per un dato che la richiesta nomina e che l'archivio contiene. Campi poco affidabili: (a) il cast nell'ordine di rilievo (chi recita, i protagonisti): se cinema_sql non ha billing_order usa tmdb_search "
    "(facet credits) e non chiedere il cast a cinema_sql; con anche regia o premi, in parts cinema_sql per quelli e tmdb_search solo per il cast; (b) numero di stagioni, elenco, numero e numerazione degli episodi, date e prossimo episodio: sempre tvmaze_search (1e), mai cinema_sql; "
    "(c) le candidature di una persona sono solo quelle in cui la fonte la nomina (reliability.results = partial): per sapere se ha vinto per un film aggiungi in parts i premi del film (awards con il titolo); per il totale, "
    "dopo i passi locali UN passo wikipedia_search sulla persona; (d) «è un remake?»: i legami registrati non distinguono remake, adattamento e prequel, UN passo wikipedia_search se serve. "
    "COMBINAZIONI. Dopo rag_search (film) o series_rag_search (serie) i metadata possono avere imdb_id per ogni titolo: per dati strutturati di un titolo scelto passa quell'imdb_id a cinema_sql (premi, regia, società, "
    "relazioni, voto) o a omdb_search (punteggi) invece di cercare di nuovo per titolo, così gli omonimi non si confondono; non scrivere mai un identificativo a memoria. Un film consigliato dal RAG con una domanda strutturata: "
    "in parts rag_search per primo, poi cinema_sql con il suo imdb_id, more_steps true. Una serie cercata per descrizione con una domanda su stagioni o episodi: series_rag_search, poi tvmaze_search con il titolo (1e). "
    "Affidabilità e ripieghi: ogni risultato ha reliability per campo (verified, partial, uncertain, absent); un dato verified non si riverifica con un'altra fonte; partial, uncertain o absent: vale la 'follow_up' del "
    "risultato (il summary dice quale tool e per quale dato). Un risultato vuoto, non trovato o non verificato non prova che l'informazione non esista: UN solo passo con lo strumento esterno corrispondente (tmdb_search per "
    "filmografie e crediti, wikipedia_search per premi e prosa, wikidata_search per relazioni, tvmaze_search per le serie, omdb_search per i voti di un titolo) e mai un secondo tentativo con cinema_sql sulla stessa entità. "
    "Se due fonti si contraddicono su un dato importante riportale entrambe senza scegliere. Se cinema_sql elenca più opere o persone con lo stesso nome (status ambiguous) non scegliere e non cercare altrove: la scelta è "
    "dell'utente, salvo che la conversazione la renda certa (allora un passo con work_id o person_id). Riusa gli identificativi dati dalla conversazione o da un passo già fatto (work_id, person_id, imdb_id, wikidata_id, tmdb_id "
    "con type) senza cercare di nuovo il titolo, e passa imdb_id e tmdb_id restituiti da cinema_sql ai passi successivi (omdb_search, tmdb_search, wikidata_search). Non ripetere una ricerca già soddisfatta nello stesso turno "
    "per la stessa entità. Richieste miste: in parts cinema_sql per la parte locale e l'altro tool per il resto, con more_steps true. Compila arguments con operation e solo i campi che servono: year, director, type, role, "
    "birth_year solo se compaiono nella richiesta, nella conversazione o in un passo già fatto; limit solo se l'utente chiede un numero; operation sql solo se nessuna operazione basta. Le impostazioni dell'utente "
    "(fonti preferite «voti degli utenti», tipo di contenuto «serie») valgono come per gli altri tool."
)

# Appended to the final-answer rules of cinema_sql in schema-4 mode (the MovieLens lists).
CINEMA_SQL_V4_FINAL_INSTRUCTIONS = (
    " Se i metadata hanno movies o genres (liste dei voti degli utenti): riporta i film nell'ordine ricevuto con voto medio su scala 1-5 e numero di voti, esattamente come nei dati; non fare medie, non convertire la scala, "
    "non confrontarla con altri voti e non aggiungere giudizi qualitativi che i dati non contengono; non nominare la provenienza. min_ratings è la soglia minima di voti della classifica: dillo se utile. Un film con status excluded "
    "non è tra i film del catalogo: dillo con parole semplici in base a reason (è un video, un episodio, una serie, un titolo non identificabile…) senza codici tecnici. Con genre_stats i film sono quelli registrati per genere, "
    "non tutti i film esistenti. Se una nota dice che l'elenco comprende film e serie (nessun type richiesto), dichiaralo e nomina il tipo di ogni opera che non è un film."
)
