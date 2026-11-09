# Matrice per la valutazione live del planner con la preferenza Film / Serie / Entrambi (DA AUTORIZZARE — non eseguita)

Impostazione reale: `content_type` ∈ `film | series | both` (default `both`), campo `preferences` del messaggio → `resolve_preferences` → `handle_query(preferences=)` → blocco `planner` (solo `film` e `series` aggiungono testo vincolante) + guardia deterministica `SettingsPolicy.check_step`. Atteso = ciò che il codice impone (guardia) più ciò che il planner dovrebbe scegliere (da misurare). Ogni riga = 1 classificatore + 1 planner (solo primo passo, nessun tool eseguito); i casi a più passi si giudicano sul primo passo e su `parts`.

| # | Domanda | film | series | both | Note |
|---|---|---|---|---|---|
| 1 | «Consigliami qualcosa su un professore di chimica che produce droga» | `rag_search`? (la guardia lascia solo film) | `series_rag_search` | il planner sceglie; atteso `series_rag_search` (Breaking Bad è una serie) o entrambi | stessa domanda, tre valori |
| 2 | «Consigliami un thriller psicologico lento e malinconico» | `rag_search` | `series_rag_search` | `rag_search`, eventualmente anche `series_rag_search` | ambigua: non devono partire entrambi per default |
| 3 | «Film come Matrix ma senza i seguiti» | `rag_search` | conflitto dichiarato, nessun tool (la richiesta è di film) | `rag_search` | `series_rag_search` mai |
| 4 | «Serie come Dark ma senza viaggi nel tempo» | conflitto dichiarato (richiesta di serie) | `series_rag_search` | `series_rag_search` | `rag_search` mai |
| 5 | «Quante stagioni ha Breaking Bad?» | conflitto (serie) | `tvmaze_search` | `tvmaze_search` | mai i RAG |
| 6 | «Quando esce il prossimo episodio di House of the Dragon?» | conflitto | `tvmaze_search` | `tvmaze_search` | |
| 7 | «Elencami gli episodi della seconda stagione di Lost» | conflitto | `tvmaze_search` | `tvmaze_search` | numerazione di Wikipedia incompleta |
| 8 | «Trova una serie su X e dimmi quante stagioni ha» | conflitto | `series_rag_search` poi `tvmaze_search` (`parts`) | idem | combinazione RAG → TVmaze |
| 9 | «Un film di Nolan con trama sul tempo, e chi sono gli attori» | `rag_search` poi `cinema_sql` (imdb_id) | conflitto | `rag_search` poi `cinema_sql` | passaggio degli `imdb_id` |
| 10 | «I 10 film più votati dagli utenti» | `cinema_sql` (movielens) | conflitto o `cinema_sql` senza `movielens` (guardia: vietato) | `cinema_sql` movielens | mai i RAG |
| 11 | «Genere con il voto medio più alto» | `cinema_sql` genre_stats | guardia blocca `movielens` | `cinema_sql` | statistiche MovieLens solo SQL |
| 12 | «Chi ha diretto Parasite e quali premi ha vinto?» | `cinema_sql` | `cinema_sql` con `type` coerente o conflitto | `cinema_sql` | |
| 13 | «Un film e una serie sul tema della memoria perduta» | `rag_search` + nota sul conflitto per la serie | `series_rag_search` + nota per il film | entrambi i RAG (`parts`) | unico caso in cui «entrambi» è atteso |
| 14 | «Punteggi Rotten Tomatoes di Dune» | `omdb_search` | `omdb_search` | `omdb_search` | fuori dai RAG |
| 15 | «Intervista al regista di Parasite» | `youtube_search` | idem | idem | |
| 16 | «Titolo che non esiste: serie Zorblax Quest» | conflitto | `series_rag_search` (vuoto) poi al massimo un passo TMDb/TVmaze | idem | `series_not_in_index` |
| 17 | «Serie con trama simile a Dark» (follow-up dopo «Film come Matrix») | conflitto | `series_rag_search` | `series_rag_search` | contesto della history |
| 18 | «Come Inception ma in formato serie» | `rag_search` | `series_rag_search` | `series_rag_search` (la richiesta dice serie) | conflitto reale di intenti |

Metriche: primo tool corretto, `series_rag_search`/`rag_search` non chiamato quando vietato dalla preferenza o dalla domanda, conflitto dichiarato quando previsto, `parts` con il secondo tool nelle combinazioni, nessun ripiego silenzioso. Costo stimato: 18 casi × 3 valori = fino a 54 coppie classificatore+planner (~108 chiamate); si può ridurre ai casi 1–5, 8, 9, 10, 13, 18 (10 casi × 3 = 60 chiamate). Comando di partenza: estendere `run_routing_eval --live --integrated` con il campo `preferences` per caso (non esiste ancora: oggi `INTEGRATED_ROUTING_CASES` gira senza preferenze).
