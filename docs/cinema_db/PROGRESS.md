# Cinema DB — PROGRESS (punto di ripresa)

Aprire una sessione nuova: leggere `AGENTS.md`, `docs/cinema_db/PLAN.md` (§15 per le decisioni) e questo file.
Ultimo aggiornamento: 2026-11-05 (fase 2 completata). Legenda: **[V]** verificato con il comando indicato · **[S]** stima · **[P]** solo progettato.

## Stato
| Fase | Stato |
|---|---|
| 0 Misura (baseline offline) | **fatta [V]** |
| 1 Sicurezza SQL (solo fixture) | **fatta [V]** — 171 test del nucleo, suite richiesta verde |
| 2 Schema + `schema.html`/`schema.mmd` | **fatta [V]** — schema reale, 17 viste approvate, generatore e test (vedi sotto) |
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

## Fase 2 — schema, viste e documentazione generata [V]
- **Schema** `cinema_db/schema.py` (DDL, indici, viste, vocabolari di definizione); `create_database(path)` crea il file e rifiuta di sovrascrivere. Decisioni e correzioni rispetto al piano: PLAN §16.
- **Misure dal file reale**: 30 tabelle STRICT, 64 FK, 17 viste pubbliche, 8 molti-a-molti, 11 schemi di ID, 16 ruoli, 12 tipi di opera, 4 relazioni; DB solo-schema 372 KB; `foreign_key_check` e `integrity_check` vuoti/ok; nessun JSON.
- **Documentazione**: `python -m cinema_db.harness.schema.generate` scrive `docs/cinema_db/schema.html` (autonomo, nessuna libreria, ricerca, filtro per gruppo, relazioni tracciate, pannello con colonne/chiavi/indici/check/DDL/viste), `schema.mmd` e `tool/cinema_db/approved_views.py`; con `--db FILE` mostra conteggi e fonti reali; `--check` esce con 1 se qualcosa è obsoleto. Fallisce se manca la descrizione di una tabella, vista o colonna, o se ne esiste una per qualcosa che non c'è (`cinema_db/schema_notes.py`).
- **Policy generata** `tool/cinema_db/approved_views.py`: viste, colonne e colonne base lette dal file; verificata a ogni apertura (`verify_policy`); un DB manomesso (vista con una colonna in più, trigger, vista mancante) è rifiutato.
- **Test** (tutti offline): `tests/test_cinema_schema.py` (14: integrità, STRICT, niente JSON, fonte su ogni fatto, indici sulle FK, vincoli, sottotipo, unicità, viste su domande vere), `tests/test_cinema_schema_doc.py` (10: note complete, file aggiornati, HTML = struttura reale, JS valido con node, Mermaid = struttura reale, digest), `tests/test_cinema_views_security.py` (87: 17 domande reali, 30 query vietate, authorizer da solo, scritture, DB manomesso, 60.000 crediti, fuzz di 1.200 casi) e i 168 della fase 1. I dati dei test sono invenzioni in cartelle temporanee.
- **Modifica al nucleo di sicurezza**: il controllo del piano ora rifiuta solo **due o più scansioni complete** di tabelle grandi nella stessa istruzione (join o sottoquery senza indice); una scansione lineare con GROUP BY è consentita (prima avrebbe respinto «chi ha più crediti»). SQLite crea da sé un indice automatico per i join di uguaglianza, quindi questi non sono quadratici.
- **Verifica visiva** dell'HTML con Chrome headless (stato iniziale, tabella `work` selezionata con le relazioni tracciate, vista `v_credit`): corretti l'ordine dei gruppi, l'elenco delle tabelle lette dalla vista e la larghezza del pannello. **Non verificato**: Mermaid con la sua libreria (controllo da CDN negato dall'autorizzazione), altri browser.
- **Decisioni aperte**: PLAN §16 (FTS5, generi, date per paese, IMDb, nome/posizione del file DB).

## Prossimo passo
Fase 3 (prima build offline) **solo dopo la tua conferma del checkpoint**: estrazione dagli snapshot Wikidata già locali, dal catalogo film v3, dal catalogo serie s5 e dal dump itwiki; nessuna rete. Prima, quantificare il numero di entità e le richieste della fase 4.
