# Ambiente locale integrato (cinema_sql v4 + RAG film + RAG serie)

Per provare insieme i tre sistemi in locale. **Nessun default del codice cambia**: tutto si accende con variabili d'ambiente di UN processo; il rollback è avviare il backend senza di esse.

## Cosa si accende
| Sistema | Come | Note |
|---|---|---|
| `cinema_sql` su file di schema 4 (strutturato + tutte le liste MovieLens) | `CINEMA_DB_ENABLED=1` + `CINEMA_DB_PATH=cinema_db/data/cinema.v4.candidate5.sqlite3` | l'avvio apre il file con la sua policy e si ferma se non va; con un file di schema 4 `movie_db_search` **non viene registrato** e il planner legge le regole integrate (`planner_rules_v4.py`) |
| RAG film `rag_search` | già attivo (`rag.backend = "wikipedia"`, collezione `wikipedia_films_it_v3`) | in modalità integrata passa l'`imdb_id` dei film al planner |
| RAG serie `series_rag_search` | `SERIES_RAG_ENABLED=1` | collezione `wikipedia_series_it_v1`; passa l'`imdb_id` (solo se affidabile) |
| Strumenti API (TMDb, OMDb, TVmaze, YouTube, Wikipedia, Wikidata) | invariati | complementari; la regola 1g dice quando |

## Comandi
```bash
# terminale 1 — dalla radice del repository
./scripts/start_qdrant.sh

# terminale 2 — controllo offline (nessuna chiamata a modelli): file, Qdrant, collezioni, strumenti, regole
./scripts/start_integrated.sh --check
# poi il backend (porta 8001 per non toccare il backend già acceso su 8000; PORT=8000 solo dopo averlo fermato tu)
./scripts/start_integrated.sh

# terminale 3 — frontend (repository marco-m-netflix), puntato al backend integrato
cd ~/Desktop/marco-m-netflix
VUE_APP_CHAT_API_URL=http://127.0.0.1:8001 npm run serve      # http://localhost:8080 (CORS già ammesso)
# lint: PATH=$HOME/.nvm/versions/node/v22.23.3/bin:$PATH npm run lint   (con Node 16 fallisce per findLastIndex, non per il codice)

# oppure la chat da terminale con la stessa configurazione
CINEMA_DB_ENABLED=1 CINEMA_DB_PATH=cinema_db/data/cinema.v4.candidate5.sqlite3 SERIES_RAG_ENABLED=1 python app.py
```
Il backend usa un solo worker. Il processo `uvicorn` PID 43712 (porta 8000, `candidate2`) non viene toccato da nulla di tutto questo.

## Rollback
Fermare il processo integrato (Ctrl+C) e riavviare come prima, senza le tre variabili: `uvicorn web_api.main:app --host 127.0.0.1 --port 8000`. Il runtime torna al file v2, `cinema_sql` non è registrato, `movie_db_search` torna attivo e il prompt del planner è identico a prima (test). Per tornare al solo schema 3: `CINEMA_DB_PATH=cinema_db/data/cinema.v3.candidate2.sqlite3`.

## Cosa provare (domande tipo, una per sistema)
- MovieLens dentro `cinema_sql`: «i 10 film più votati dagli utenti», «migliori film di fantascienza degli anni Ottanta secondo gli utenti», «film con il tag time travel», «qual è il genere con il voto medio più alto?», «che voto hanno dato gli utenti a Pulp Fiction?».
- Strutturato: «chi ha diretto Parasite e quali premi ha vinto?», «filmografia di Greta Gerwig».
- RAG film: «consigliami un film inquietante ambientato in un faro isolato». RAG serie: «consigliami una serie su detective che indagano su casi irrisolti».
- Combinazioni: «consigliami un film sul lutto e dimmi chi l'ha diretto e se ha vinto premi» (RAG, poi `cinema_sql` con l'`imdb_id`); «consigliami una serie su una pandemia e dimmi quante stagioni ha» (RAG serie, poi TVmaze/`cinema_sql`).
- Complementari: streaming (TMDb), Rotten Tomatoes (OMDb), intervista al regista (YouTube).
Valutazione automatica del planner su queste (e altre) domande: `python -m movie_db.harness.evaluation.run_routing_eval --live --integrated` (21 casi = 42 chiamate; **a pagamento, solo con autorizzazione**).

## Interfaccia
Il passo `cinema_sql_calls` di una lista MovieLens mostra: operazione («Liste MovieLens»), esito, conteggi, limiti dei dati, le query SQL eseguite e la fonte **«voti e tag degli utenti di MovieLens (GroupLens)»**; nessun link Wikipedia/Wikidata né licenze CC (non sono dati loro). Nessun codice del frontend è cambiato: etichette e note arrivano dal backend (`presenters/cinema_view.py`).

## Verifica del browser
Checklist di 16 domande con l'esito atteso per ciascuna, e degli stati da guardare: `INTEGRATED_FRONTEND_CHECKLIST.md` (non ancora eseguita; chiama modelli a pagamento).
