# Ambiente locale integrato (cinema_sql v4 + RAG film + RAG serie)

**Dalla FASE 24 è la configurazione di DEFAULT del codice** (`app.py` `CONFIG`): `cinema_sql` sulla candidata 6 e `series_rag_search` sono accesi senza variabili, `movie_db_search` non è registrato (il suo codice c'è ancora). Si spegne con `CINEMA_DB_ENABLED=0` e/o `SERIES_RAG_ENABLED=0` (ognuno da solo); la variabile esplicita prevale sempre sul default, `CINEMA_DB_PATH` sceglie un altro file.

## Cosa è acceso
| Sistema | Default | Spegnimento / note |
|---|---|---|
| `cinema_sql` su file di schema 4 (strutturato + tutte le liste MovieLens) | **acceso**, `cinema_db/data/cinema.v4.candidate6.sqlite3` (digest dati `27d2d09e…`, `cinema_db/harness/candidate.py`) | `CINEMA_DB_ENABLED=0`: torna `movie_db_search` con le regole di prima. L'avvio apre il file con la sua policy e si ferma con un messaggio se manca |
| RAG film `rag_search` | acceso (`wikipedia_films_it_v3`) | tool separato dal RAG serie; in modalità integrata passa l'`imdb_id` dei film al planner |
| RAG serie `series_rag_search` | **acceso** (`wikipedia_series_it_v1`) | `SERIES_RAG_ENABLED=0`; passa l'`imdb_id` (solo se affidabile). L'avvio si ferma se Qdrant o la collezione mancano |
| Strumenti API (TMDb, OMDb, TVmaze, YouTube, Wikipedia, Wikidata) | invariati | complementari; la regola 1g dice quando |

## Comandi
```bash
# terminale 1 — dalla radice del repository
./scripts/start_qdrant.sh

# terminale 2 — controllo offline (nessuna chiamata a modelli): file, Qdrant, collezioni, strumenti, regole
./scripts/start_integrated.sh --check
# poi il backend (porta 8001 di default; PORT=8000 per la porta consueta, dopo aver fermato il backend che la occupa)
./scripts/start_integrated.sh

# terminale 3 — frontend (repository marco-m-netflix), puntato al backend integrato
cd ~/Desktop/marco-m-netflix
VUE_APP_CHAT_API_URL=http://127.0.0.1:8001 npm run serve      # http://localhost:8080 (CORS già ammesso)
# lint: PATH=$HOME/.nvm/versions/node/v22.23.3/bin:$PATH npm run lint   (con Node 16 fallisce per findLastIndex, non per il codice)

# oppure la chat da terminale con la stessa configurazione
python app.py        # i default sono già quelli integrati
```
Il backend usa un solo worker.

## Riavvio (FASE 24E: ESEGUITO il 2026-11-09 alle 19:13 per il solo backend 8001, nuovo PID 93877; il resto del testo è il piano originale)
Processi al 2026-11-09: Qdrant PID 43664 (6333, **resta acceso**); uvicorn PID 43712 (8000, codice dell'8 nov, `candidate2`); uvicorn PID 65519 (8001, `candidate5`, senza RAG serie); frontend `vue-cli-service` PID 65234 (8080) con `VUE_APP_CHAT_API_URL=http://127.0.0.1:8001`.
**Opzione consigliata (frontend invariato)**: 1) `./scripts/start_integrated.sh --check` (già eseguito il 2026-11-09 con esito OK: legge e non avvia nulla); 2) fermare **solo** il backend 8001 (`kill 65519`, o Ctrl+C nel suo terminale); 3) dalla radice: `./scripts/start_integrated.sh` (porta 8001: il frontend a 8080 già punta lì, nessun riavvio del frontend); 4) il backend 8000 (43712) resta com'è come riferimento vecchio finché non lo decidi. **Opzione 8000**: fermare anche 43712 e avviare `PORT=8000 ./scripts/start_integrated.sh`; poi il frontend va riavviato con `VUE_APP_CHAT_API_URL=http://127.0.0.1:8000 npm run serve` (dal repository `marco-m-netflix`).
**Verifica dopo l'avvio** (nessuna chiamata a modelli): `curl -s http://127.0.0.1:8001/health` → `{"status":"ok"}`; `curl -s http://127.0.0.1:8001/settings` (sei campi, `content_type` default `both`); `ps -p <PID> -o lstart,command` (avvio dopo il commit `e22963c`); l'identità della configurazione che il processo ha letto è quella che stampa `./scripts/start_integrated.sh --check` (strumenti, `movie_db_search registered: False`, database `candidate6` schema 4 digest `27d2d09e…`, `cinema_sql`/`series_rag_search`/`rag_search` on). Il database si apre a ogni interrogazione, quindi non compare tra i file aperti del processo.

## Spegnere un sistema
`CINEMA_DB_ENABLED=0` spegne `cinema_sql` e `SERIES_RAG_ENABLED=0` il RAG serie (riavviare il backend). Dal 2026-11-16 il vecchio tool `movie_db_search` non esiste più: non c'è un ripiego MovieLens separato, e il rollback alle build precedenti (candidata 5, file v3) è stato eliminato insieme ai file.

## Cosa provare (domande tipo, una per sistema)
- MovieLens dentro `cinema_sql`: «i 10 film più votati dagli utenti», «migliori film di fantascienza degli anni Ottanta secondo gli utenti», «film con il tag time travel», «qual è il genere con il voto medio più alto?», «che voto hanno dato gli utenti a Pulp Fiction?».
- Strutturato: «chi ha diretto Parasite e quali premi ha vinto?», «filmografia di Greta Gerwig».
- RAG film: «consigliami un film inquietante ambientato in un faro isolato». RAG serie: «consigliami una serie su detective che indagano su casi irrisolti».
- Combinazioni: «consigliami un film sul lutto e dimmi chi l'ha diretto e se ha vinto premi» (RAG, poi `cinema_sql` con l'`imdb_id`); «consigliami una serie su una pandemia e dimmi quante stagioni ha» (RAG serie, poi TVmaze/`cinema_sql`).
- Complementari: streaming (TMDb), Rotten Tomatoes (OMDb), intervista al regista (YouTube).
Valutazione automatica del planner su queste (e altre) domande: `python -m movie_db.harness.evaluation.run_routing_eval --live --integrated` (28 casi = 56 chiamate; eseguita il 2026-11-09, FASE 23; **a pagamento, solo con autorizzazione**).

## Interfaccia
Il passo `cinema_sql_calls` di una lista MovieLens mostra: operazione («Liste MovieLens»), esito, conteggi, limiti dei dati, le query SQL eseguite e la fonte **«voti e tag degli utenti di MovieLens (GroupLens)»**; nessun link Wikipedia/Wikidata né licenze CC (non sono dati loro). Nessun codice del frontend è cambiato: etichette e note arrivano dal backend (`presenters/cinema_view.py`).

## Verifica del browser
Checklist di 16 domande con l'esito atteso per ciascuna, e degli stati da guardare: `INTEGRATED_FRONTEND_CHECKLIST.md` (non ancora eseguita; chiama modelli a pagamento).
