# NEXT_SESSION — punto di ingresso per riprendere il lavoro (aggiornato 2026-11-09, fine FASE 23)

Leggi nell'ordine: questo file, le sezioni «FASE 23» e «FASE 22» in cima a `docs/cinema_db/PROGRESS.md`, `docs/cinema_db/PHASE24_ACTIVATION_PLAN.md` (piano da rivedere), poi `AGENTS.md`. Questo file non duplica i dettagli: rimanda.

## 1. Obiettivo e roadmap vincolante
Assistente cinematografico (terminale + web) con tre sistemi di ricerca: `cinema_sql` (database relazionale, MovieLens incluso), `rag_search` (film), `series_rag_search` (serie e film TV), più API esterne. Roadmap, da non anticipare:
1. Validare i due RAG — **CONCLUSO** (limiti residui in PROGRESS FASE 20).
2. **Validare `cinema_sql` e MovieLens — CONCLUSO: offline (FASE 22) e valutazione LIVE del planner (FASE 23: integrata 25/28 prima delle correzioni, preferenze 50/52 poi 17/17 sulle celle corrette).**
3. **Attivare `cinema_sql` nel runtime ed eliminare `movie_db_search` — PIANO PRONTO, NON ESEGUITO (`PHASE24_ACTIVATION_PLAN.md`).**
4. Test integrati di database, RAG, planner e tool esterni.
5. Solo alla fine, pulizia di cartelle e codice residuo.

## 2. Stato preciso (verificato il 2026-11-09)
- **Candidata 6**: `cinema_db/data/cinema.v4.candidate6.sqlite3`, 1.118.142.464 byte, schema 4, digest dei dati `27d2d09e1c0764b85b5734fc5a5ca7c7001e817f0e240c62775440a89b8147ea` (ricalcolato dalle righe: uguale). È il file in `cinema_db/harness/candidate.py` (`EXPECTED`). Seconda build indipendente `cinema.v4.candidate6.verify.sqlite3`: stesso digest, stessi contatori (duplicato esatto, cancellabile solo su tua decisione). `verify_movielens` `ok: true` (`PHASE22_VERIFY.json`).
- **Candidata 5 INTATTA** (1.116.782.592 byte, 09:36:41, digest `298abfe3…`): rollback.
- Runtime invariato: `CONFIG["cinema_db"]["enabled"] = False`, `db_path` = file v2, `movie_db_search` registrato e attivo. Processi non toccati: Qdrant (PID 43664), uvicorn 8000 (43712, codice dell'8 nov con `candidate2`), uvicorn 8001 (65519, codice precedente alle fasi 16–19).
- Suite offline: `python -m pytest tests pipelines/wikipedia_series/tests -q -m "not integration and not qdrant_server"` → **3.126 passati, 1 saltato, 0 fallimenti** (FASE 23). `generate --check` → 0. **Nessun commit** in tutta la sessione.

## 3. Cosa è cambiato in FASE 22–23
FASE 22: popolazioni approvate, candidata 6, doppioni MovieLens non sommati. **FASE 23** (valutazione live, ~159 chiamate): le 7 celle nuove su `type`/`tag` passano; correzioni: la guardia `content_type` ammette `movielens by_tag` (con `type`) anche sotto «serie» e riempie `type` per `ratings` senza titolo, un nuovo tentativo del planner se la risposta non è JSON valido, attesa di `k_finale` per «un film». **Non corretto**: «I 10 film più votati dagli utenti» → `top_rated` (riproducibile 4/4). Dettagli: PROGRESS FASE 23.

## 4. Verificato / non verificato
**Verificato offline**: integrità, chiavi esterne, digest, riproducibilità, coerenza MovieLens, parità, determinismo, prestazioni (mediane 12–54 ms, `provenance` 16 ms), `genre_stats` = calcolo dalla sorgente sui film collegati.
**Verificato dal vivo (FASE 23)**: routing verso i tre sistemi e gli strumenti complementari (28 casi), `type` di `ratings` e `by_tag`, preferenze film/serie/entrambi (52 celle). **NON verificato**: una seconda esecuzione completa dopo le correzioni (solo le celle toccate sono state rieseguite); il recupero dal vivo del nuovo tentativo sul JSON non valido; il frontend (fuori dal repository) per `kind` e le note nuove; l'esatto campione dei 395 casi della FASE 20.
**Limiti noti**: gli altri modi movielens ignorano `type`; copertura Wikidata/paese ~34 %; 27 doppioni MovieLens documentati; ordinamenti non-MovieLens senza spareggio unico (rischio teorico).

## 5. DECISIONI che spettano all'utente
1. **Approvare il piano di attivazione** (`PHASE24_ACTIVATION_PLAN.md`): passo A (default accesi, codice legacy ancora presente, riavvio dei servizi) e, solo dopo i tuoi test manuali, passo B (rimozione di `movie_db_search`). Prima serve un commit o un branch (nessun commit è stato fatto in tutte le fasi 21–23).
2. «I 10 film più votati dagli utenti»: accettare `top_rated` e `most_rated`, oppure precisare la semantica nel prompt.
3. Pulizia dei file (6 `*.verify.sqlite3` da ~1 GB e candidate superate, inventario nel piano §7): solo dopo i test manuali.

## 6. Operazioni
**Autorizzate**: ispezioni, query in sola lettura, test offline, rigenerazione dei documenti.
**NON autorizzate senza permesso**: modificare qualunque `.sqlite3` esistente (la 5 e la 6 mai); nuove build; chiamate a modelli, embedding, API esterne; valutazioni live; attivare `cinema_sql` o cambiare i default; eliminare `movie_db_search`; riavviare o fermare processi; commit; toccare `.env`, `dataset/`, `dbVettoriale/`, `movie_db/data/`, `pipelines/*/data/`.

## 7. Sequenza dopo l'approvazione
1. Commit/branch (tuo ok). 2. Passo A + riavvio dei servizi (tuo ok). 3. I tuoi test manuali (`INTEGRATED_FRONTEND_CHECKLIST.md`). 4. Passo B in commit separati, suite dopo ciascuno. 5. Pulizia finale di file, dati e documenti di progress.
