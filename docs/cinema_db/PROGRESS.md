# Cinema DB — PROGRESS (punto di ripresa)

Aprire una sessione nuova: leggere `AGENTS.md`, `docs/cinema_db/PLAN.md` (§15 per le decisioni) e questo file.
Ultimo aggiornamento: 2026-11-05. Legenda: **[V]** verificato con il comando indicato · **[S]** stima · **[P]** solo progettato.

## Stato
| Fase | Stato |
|---|---|
| 0 Misura (baseline offline) | **fatta [V]** |
| 1 Sicurezza SQL (solo fixture) | **fatta [V]** — 171 test del nucleo, suite richiesta verde |
| 2 Schema + `schema.html`/`schema.mmd` | da fare |
| 3 Prima build offline | da fare |
| 4 Arricchimento Wikidata (+ IMDb selettivo, D5) | da fare, dopo la verifica della fase 3 |
| 5 Tool `cinema_sql` e routing | da fare; **non registrato** in `app.py` né in `allowed_tools` |

## Vincoli permanenti
Nessuna chiamata OpenAI a pagamento, nessun embedding, MovieLens e RAG film/serie intatti (verificato: `movie_db/data/movielens32m.sqlite3` stesso size e mtime di prima, aperto solo `mode=ro`), nessun input originale modificato, nessun parallelismo del planner.

## Fase 0 — baseline [V per le richieste, S per sequenze e latenze]
`python -m cinema_db.harness.baseline.run_baseline` → `docs/cinema_db/BASELINE.md` e `baseline.json` (offline, gratis).
- **Misurato**: richieste HTTP inviate dal codice reale dei tool contro i transport finti dei test; latenza di query SQL reali su MovieLens (sola lettura).
- **Stimato**: sequenza dei tool per domanda (il planner LLM non è stato eseguito), chiamate del planner, latenze di rete (dalle note live di AGENTS.md), costo delle operazioni senza fixture.
- Risultato sulle 30 domande (18 cambiano sequenza): richieste HTTP **96 → 49**, passi con tool esterno **39 → 22**, chiamate del planner **44 → 42** (stima), latenza **~192 → ~133 s** (stima).
- **Correzione del piano**: passare l'ID risparmia 1 richiesta solo a OMDb (e a TMDb solo col `tmdb_id`), a Wikidata 0. Il guadagno vero è sostituire interi tool con SQL locale e alimentare catene (OMDb per 5 candidati: 10 → 5). Dettaglio in BASELINE §5 e PLAN §8.1.
- SQL locale MovieLens (misurato): top-rated 0,2 ms p50, by_title 0,04 ms, aggregazione per genere 90 ms.

## Fase 1 — nucleo di sicurezza [V]
Codice: `tool/cinema_db/` (`validator.py`, `policy.py`, `connection.py`, `executor.py`, `errors.py`, `settings.py`). Test: `tests/test_cinema_sql_security.py` (171) con `tests/cinema_sql_support.py` (DB fixture con colonne «segrete» non esposte). Dipendenza: `sqlglot==30.24.0` (MIT).
Livelli (ognuno da solo impedisce le scritture, provato da test indipendenti):
1. **Validatore AST**: una sola SELECT (anche tra commenti), niente DDL/DML/PRAGMA/ATTACH/EXPLAIN/VACUUM, niente CTE ricorsive né con il nome di una tabella, niente funzioni tabella, whitelist di viste, colonne (qualificazione sqlglot) e funzioni, join con condizione che lega due tabelle, parametri solo posizionali, LIMIT/OFFSET letterali e forzati. **Si esegue il testo rigenerato**, senza commenti, e viene ricontrollato.
2. **Connessione**: `mode=ro` + `immutable=1`, `query_only`, `trusted_schema=OFF`, estensioni disattivate, limiti SQLite (`setlimit`), `ATTACH` a 0; la policy è verificata contro il DB reale (viste, colonne, colonne base, nessun trigger) prima di usare la connessione.
3. **Authorizer** con negazione predefinita: solo SELECT, lettura delle colonne delle viste dal livello superiore, lettura delle colonne base dichiarate **solo per conto di una vista** (chiude il trucco della CTE col nome di una vista), funzioni in lista. Test: ogni codice azione da 0 a 199 è negato tranne SELECT/READ/FUNCTION.
4. **Executor**: scadenza (progress handler + `interrupt`), tetto di righe (con una riga in più per segnalare il taglio), di byte e di caratteri per cella, controllo del piano (`SCAN` di tabelle grandi con ordinamento/raggruppamento), errori tipizzati senza il testo di SQLite.
Trovato dai test e corretto: (a) sqlglot conserva i commenti nel testo rigenerato (ora `comments=False`); (b) `JOIN` senza `ON` diventa `ON TRUE` (ora rifiutato, condizione obbligatoria su due tavole).
Non coperto/limiti noti: la correttezza *semantica* di una SELECT valida non è verificata dal validatore; i nomi di funzione dipendono dal rendering di sqlglot (test sulle funzioni ammesse e vietate); il controllo del piano usa solo tabelle dichiarate `large_tables` (nessuna ancora: arrivano con lo schema reale in fase 2); `Python 3.11` non ha `Connection.setconfig` (DBCONFIG DEFENSIVE): compensato da authorizer e `trusted_schema=OFF`.

## Prossimo passo
Fase 2: schema relazionale reale (viste approvate con colonne), generatore di `schema.html`/`schema.mmd` dallo schema SQLite e test di allineamento. Poi checkpoint.
