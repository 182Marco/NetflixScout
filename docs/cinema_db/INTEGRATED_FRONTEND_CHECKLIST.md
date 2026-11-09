# Checklist di verifica manuale dell'interfaccia (backend integrato su 8001 + frontend su 8080)

**Stato: NON eseguita.** Nell'ambiente non c'è uno strumento browser, quindi nessuna parte di questa lista è dichiarata superata. Il frontend compila e serve (`http://localhost:8080`, indirizzo del backend `127.0.0.1:8001` incorporato nel bundle) e il rendering dello step MovieLens è provato in Node su dati reali del backend (`tests/test_cinema_frontend_render.py`), ma l'aspetto nel browser no.

**Costo**: ogni domanda qui sotto **chiama modelli a pagamento** (classificatore, planner, risposta finale; in più parser, embedding e riordino per i RAG). Sono poche chiamate per domanda, ma è comunque una prova con costi: serve il tuo via libera, come per la valutazione live.

## Prima di cominciare
```bash
./scripts/start_qdrant.sh                       # se non è già acceso (lo è, PID 43664)
./scripts/start_integrated.sh --check           # offline
./scripts/start_integrated.sh                   # backend integrato su 8001 (già avviato in questa sessione, PID nel report)
cd ~/Desktop/marco-m-netflix && VUE_APP_CHAT_API_URL=http://127.0.0.1:8001 npm run serve   # già avviato, http://localhost:8080
```
Apri http://localhost:8080 e il chat dell'assistente. Tieni aperta la console del browser (errori rossi = problema).

## Per ogni domanda controlla (colonna «Cosa deve comparire»)
Il flusso: stato «sto cercando…» → storia del turno (poche frasi) → riquadri degli step → testo della risposta che arriva a pezzi → eventuali schede/lista. Nessuna riga deve mostrare: id interni (`work_id`, `person_id`), nomi di viste (`v_ml_movie`…) fuori dall'elenco delle query SQL eseguite, `score`, chiavi, la parola «MovieLens» nel TESTO della risposta (compare solo come fonte nel riquadro), né codici come `outside_entry_rule`.

| # | Domanda | Sistema atteso | Cosa deve comparire |
|---|---|---|---|
| 1 | «i 10 film più votati dagli utenti» | `cinema_sql` movielens most_rated | riquadro ARCHIVIO LOCALE «Liste MovieLens», fonte «voti e tag degli utenti di MovieLens (GroupLens)», **nessun link Wikipedia/Wikidata né licenze**, query SQL eseguite; risposta con 10 film in ordine, voto su scala 1-5 e numero di voti |
| 2 | «migliori film di fantascienza degli anni Ottanta secondo gli utenti» | movielens top_rated, genere Sci-Fi, 1980-1989 | primi: L'Impero colpisce ancora, Blade Runner… (dai dati reali), tutti del periodo |
| 3 | «film con il tag time travel» | movielens by_tag | Interstellar, Donnie Darko… con il numero di utenti |
| 4 | «qual è il genere con il voto medio più alto?» | movielens genre_stats | Film-Noir in testa; nota sui generi propri di MovieLens |
| 5 | «che voto hanno dato gli utenti a Inception?» | `cinema_sql` ratings (una riga per fonte, scale 10 e 5) | due fonti con scala, voti e data; nessuna media |
| 6 | «chi ha diretto Parasite e quali premi ha vinto?» | `cinema_sql` crew/awards | riquadro con fonte Wikipedia/Wikidata, link alle pagine pubbliche, licenze CC |
| 7 | «filmografia di Christopher Nolan» | `cinema_sql` filmography | elenco con «Mostrati X di Y» se tagliato |
| 8 | «consigliami un film inquietante ambientato in un faro isolato» | `rag_search` | riquadro del RAG film (K largo, riordino, selezione), film con locandina |
| 9 | «consigliami un film sul lutto e dimmi chi l'ha diretto e se ha vinto premi» | `rag_search` poi `cinema_sql` | **due riquadri nell'ordine RAG → ARCHIVIO LOCALE**; nel secondo la query SQL cerca per identificativo (nessuna ricerca per titolo): niente alternative «ambiguo» |
| 10 | «consigliami una serie su detective che indagano su casi irrisolti» | `series_rag_search` | riquadro «catalogo serie» con risultati numerati e fonte Wikipedia CC BY-SA |
| 11 | «consigliami una serie su una pandemia e dimmi quante stagioni ha» | `series_rag_search` poi `tvmaze_search` | due riquadri; stagioni da TVmaze con link TVmaze; **mai** `cinema_sql` per le stagioni |
| 12 | «quante stagioni ha Breaking Bad?» | `tvmaze_search` (priorità fissa) | un solo riquadro TVmaze con le sue chiamate HTTP |
| 13 | «dove posso vedere Dune in streaming?» | `tmdb_search` | riquadro TMDb con le chiamate; attribuzione JustWatch |
| 14 | «punteggio di Oppenheimer su Rotten Tomatoes» | `omdb_search` | punteggi con scala, «non disponibile» dove manca |
| 15 | «i film con il tag zzz-inesistente» | `cinema_sql` movielens by_tag, risultato vuoto | riquadro «Nessun dato nell'archivio locale»; la risposta lo dice senza inventare; al massimo UN passo di ripiego |
| 16 | «ricetta della carbonara» | bloccata dal classificatore | solo il messaggio di rifiuto, nessuno step |

## Stati da guardare
- **Caricamento**: il segnale di stato compare subito e sparisce con la risposta; durante gli step lunghi (RAG ~3–10 s) l'interfaccia non si blocca.
- **Errore**: spegni Qdrant per 10 secondi e rifai la domanda 8 → messaggio d'errore leggibile, nessuna pagina rotta; riaccendi.
- **Risposta vuota**: domanda 15.
- **Più turni**: dopo la 9 scrivi «e di quel film chi era l'attore principale?» (riferimento implicito alla conversazione).
- **Lingua**: la domanda 1 in inglese («the 10 most rated films») → testi fissi e risposta in inglese.
- **Impostazioni**: con «tipo di contenuto = serie» la domanda 1 non deve usare `cinema_sql` movielens (frase di conflitto fissa all'inizio della risposta).

## Esito da annotare
Per ogni riga: ok / non ok + cosa si vede. Un «non ok» sul routing (tool sbagliato) va confrontato con `docs/cinema_db/PROGRESS.md` (FASE 12) prima di toccare il codice.
