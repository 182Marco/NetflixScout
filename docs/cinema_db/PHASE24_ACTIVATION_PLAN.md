# FASE 24 — Piano tecnico di attivazione del runtime integrato (2026-11-09) — NIENTE È STATO ESEGUITO

Piano da rivedere. **Nulla è stato attivato, cancellato o spostato.** File di riferimento: `cinema_db/data/cinema.v4.candidate6.sqlite3` (digest `27d2d09e…`). Rollback: la candidata 5 e il codice attuale (commit non fatti: il rollback del codice è la copia di lavoro, quindi **serve un commit o un branch prima di iniziare**).

## 1. Stato attuale del runtime (verificato)
- `CONFIG["cinema_db"]`: `enabled False`, `db_path` = file v2 (`cinema.sqlite3`). `CONFIG["series_rag"]["enabled"]` False. `CONFIG["movie_db"]["enabled"]` True: `movie_db_search` registrato (`MovieDbTool` + `TmdbWorkTypeChecker`).
- `app._apply_schema_4_mode` (app.py:747) già fa l'architettura integrata quando `cinema_db.enabled` e il file è di schema 4: toglie `movie_db_search` da `allowed_tools` e da `data_coverage`, mette `movie_db.enabled False`, sostituisce le regole 2/1g con `planner_rules_v4.py`, passa gli `imdb_id` dei RAG. **Quindi l'attivazione funzionale è già codificata**: si tratta di cambiare i default e poi togliere il codice morto.
- Avvio: `scripts/start_integrated.sh` (variabili `CINEMA_DB_ENABLED=1 CINEMA_DB_PATH=…candidate6… SERIES_RAG_ENABLED=1`, ora già su candidate6).

## 2. Attivazione (due passi reversibili, il secondo solo dopo i test manuali)
**Passo A — default accesi, codice legacy ancora presente (rollback = un file)**
1. In `CONFIG` (app.py): `cinema_db.enabled True`, `cinema_db.db_path` = `cinema_db/data/cinema.v4.candidate6.sqlite3`; `series_rag.enabled True`. Variabile d'ambiente per spegnere: lasciare `CINEMA_DB_ENABLED=0` come interruttore documentato (oggi la logica è solo «accendi»: va aggiunta la lettura del valore falso, con test).
2. `ensure_cinema_db_ready` e `ensure_series_rag_ready` già fermano l'avvio se il file o Qdrant mancano: invariato. Il file della candidata 6 resta fuori da git (`cinema_db/data/` è ignorato), quindi il percorso va documentato in README/AGENTS.
3. Test: `tests/test_integrated_v4.py` (matrice dei flag) va aggiornata: il «default» ora è integrato; i test che assumono il prompt «di sempre» con i flag spenti diventano test del flag spento esplicito.
4. Riavvio dei due uvicorn (8000 e 8001, ancora su codice vecchio) e del terminale: **solo con il tuo permesso** (oggi girano senza essere toccati).
5. Verifica: `run_routing_eval --live --integrated` e `run_preference_routing_eval` (già eseguiti in FASE 23) + checklist del browser (`INTEGRATED_FRONTEND_CHECKLIST.md`) + i tuoi test manuali.

**Passo B — rimozione del vecchio tool (solo dopo approvazione dei test manuali)**
1. `app.py`: togliere gli import `MovieDbTool`, `load_movie_db_config`, `ensure_db_ready`, `TmdbWorkTypeChecker`; la registrazione (righe ~775-781); `movie_db_search` da `allowed_tools`, `data_coverage` e dalle regole di testo (righe 70, 322, 348, 416: la regola 2 e le citazioni nelle regole 1/3); `_apply_schema_4_mode` diventa il comportamento unico (niente più doppio prompt); il blocco `CONFIG["movie_db"]` si riduce a ciò che serve alla build (percorsi del file MovieLens).
2. `preferences/behavior.py`, `preferences/policy.py` (`SOURCE_TOOLS`, `FILM_ONLY_TOOLS`, ecc.), `presenters/story_view.py`, `tool/cinema_db/constants.py` e `queries.py` (commenti), `planner_rules_v4.py`: togliere i riferimenti a `movie_db_search`.
3. Step `db_query`: `presenters/db_view.py`, `presenters/terminal/db/`, `presenters/web/db/`, `STEP_RENDERERS`/`STEP_SERIALIZERS` e il contratto `web_api/contracts/chat_stream.md` — **il frontend esterno potrebbe ancora gestire `db_query`**: il kind sparirebbe solo dai nuovi turni (nessuna rottura), ma va confermato.
4. Codice del tool: `tool/movie_db/` (35 file: `movie_db_tool.py`, parser, `sql/`, `work_type.py`, `results.py`, `trace.py`, `titles.py`), `tool/tmdb/work_type.py` (usato solo da `MovieDbTool`), `data_coverage.py` + `tests/test_data_coverage.py`. `tests/test_tool_package.py` (cartelle di `tool/` = tool registrati) va aggiornato.
5. **Da conservare** (build e verifica di MovieLens dentro `cinema_sql`): `movie_db/schema.py` (generi e `normalize_tag`, importati dai test), `movie_db/data/` (CSV e `movielens32m.sqlite3`: input della build e di `verify_movielens`/parità), `movie_db/harness/ingestion/` + `buildMovieDb.py` (costruiscono il file MovieLens che `imdb_layer --movielens` legge), `movie_db/config.py` (`QueryConfig` è importato da `run_movielens_parity` per eseguire il vecchio SQL: se si toglie `tool/movie_db/sql/` la parità storica non è più eseguibile → decidere se archiviare `PHASE22_MOVIELENS_PARITY.*` come ultimo risultato e congelare lo script).
6. Test legacy da rimuovere/adeguare: `tests/test_movie_db_{app,tool,parser,repository,readonly,presenters,titles_series,routing_eval,eval,config}.py`; da mantenere: `test_movie_db_ingestion.py` (build). Casi `ROUTING_CASES` con `expected_tool` DB e `harness/evaluation/{cases,run_eval,routing_cases}.py`: spostare quelli utili in `INTEGRATED_ROUTING_CASES`.
7. Cinema: `cinema_db/harness/tool_eval/{run_live,run_v3_eval}.py` e `cinema_db/harness/baseline/run_baseline.py` citano `movie_db_search` come termine di confronto storico.

## 3. Che cosa deve restare identico (verifiche a ogni passo)
- I due RAG restano tool separati (`rag_search` con `tool/rag/film`, `series_rag_search` con `tool/rag/series`): `tests/test_tool_package.py`, `tests/test_rag_infrastructure_real.py` (Qdrant acceso), `run_rag_infra_check` (22 controlli).
- Routing verso TMDb, OMDb, TVmaze, YouTube, Wikipedia, Wikidata: nella valutazione integrata di FASE 23 i casi complementari passano (TMDb ×2, OMDb, YouTube, TVmaze stagioni, combinazioni con `parts`).
- Priorità fissa: stagioni/episodi/date di UNA serie sono sempre di `tvmaze_search`.
- Guardia `content_type`: `movielens` solo `by_tag` sotto «serie» (corretto in FASE 23).

## 4. Dipendenze che diventerebbero inutili (da confermare con un grep prima di cancellare)
`tool/tmdb/work_type.py` e la chiamata `/find` per il tipo di opera (12 chiamate TMDb per turno MovieLens) — con `cinema_sql` il tipo è un dato del database; `data_coverage` (copertura 2022 di MovieLens: oggi detta nel testo dell'operazione); la regola 2 del prompt e la nota «fermo al 2012» del backend legacy; `buildSemanticDb.py`-simili sono già stati rimossi. Nessuna dipendenza Python in `requirements.txt` risulta dedicata al solo tool (sqlite3 è stdlib): **nessuna riga da togliere**.

## 5. Ordine consigliato e punti di arresto
1) commit/branch del lavoro attuale (tuo ok); 2) Passo A + riavvio (tuo ok); 3) **i tuoi test manuali**; 4) approvazione; 5) Passo B in commit separati (app/prompt, preferenze/presenter, tool e test legacy), suite dopo ciascuno; 6) pulizia finale (sezione 7 di `NEXT_SESSION.md`). Dopo il passo A non c'è nulla di irreversibile; dopo il B il rollback è il commit precedente.

## 6. Rischi noti
Planner: «I 10 film più votati dagli utenti» → `top_rated` (riproducibile, non corretto); JSON non valido del modello (ora un nuovo tentativo, 1 di 28 + 2 di 4 sullo stesso caso); schema di `cinema_sql` 4.097 caratteri contro il limite di test 4.100 (margine 3 caratteri: ogni nuovo campo richiede di accorciare altro); frontend esterno non verificato (`kind`, note nuove, kind `db_query`); copertura Wikidata e paese ~34 %.

## 7. Inventario di ciò che andrà valutato dopo (nessuna cancellazione fatta)
- **File SQLite in `cinema_db/data/` (22 GB totali)**: `*.verify.sqlite3` ×6 (≈1,0–1,1 GB ciascuno: candidate6, candidate4, v3.candidate, v3.candidate2, v3.reconciled2, v3 — duplicati di verifica); candidate superate: `candidate3`, `candidate4`, `candidate5` (rollback, **da tenere finché la 6 non è approvata**), `v3.candidate`, `v3.candidate2` (base di `verify_movielens`: **tenere**), `v3.reconciled`, `v3.reconciled2`, `v3.first_build` (superata), `v3.sqlite3`; storici `cinema.sqlite3` (v2, ancora il default del runtime fino al passo A), `phase3`, `phase4`, `phase6`. Cartelle `*.separate/` e `*.layer_report.json` accanto a ciascuna.
- Altri dati: `movie_db/data` 2,1 GB (input build: tenere), `dbVettoriale` 5,5 GB (collezioni Qdrant: v1/v2 e `netflix_scout` non usate, vedi AGENTS), `dataset/` 128 MB (CMU, non usato).
- Documenti di progress da consolidare: `PROGRESS.md` (oltre 1.400 righe), `pipelines/*/PROGRESS.md`, `docs/qdrant_migration/`, report di fase superati.
