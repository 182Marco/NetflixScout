# Piano della valutazione live dei tre sistemi integrati (DA AUTORIZZARE — nessuna parte è stata eseguita)

Obiettivo: dimostrare, prima di rimuovere `movie_db_search` e il vecchio RAG, che (1) il planner reale sceglie e combina bene `cinema_sql`, `rag_search`, `series_rag_search` e le API complementari, (2) i due RAG restituiscono risultati semanticamente buoni per richieste in testo libero, (3) l'interfaccia mostra tutto correttamente. Le tre cose si misurano **separatamente**, perché hanno costi, strumenti e criteri diversi.

Prerequisiti già soddisfatti offline (FASE 12–13): configurazione integrata avviabile, collezioni leggibili con dimensioni coerenti, filtri dei due retriever verificati con vettori memorizzati, passaggio degli `imdb_id` verificato fino a `cinema_sql`, priorità fissa delle stagioni nel prompt, suite offline verde.

> Aggiornamento FASE 16 (2026-11-09): il package è `tool/rag/{film,series,shared}`, la variabile di avvio del RAG serie è `SERIES_RAG_ENABLED=1` (era `SERIES_INDEX_ENABLED`), il vecchio RAG non esiste più; i comandi sotto sono invariati.

## Parte A — Routing del planner (21 casi, 42 chiamate)
- **Comando**: `python -m movie_db.harness.evaluation.run_routing_eval --live --integrated` (backend integrato non necessario: costruisce l'applicazione da sé con `cinema.v4.candidate5.sqlite3` e la serie accesa; i RAG e gli altri tool **non vengono eseguiti**, si giudica solo il primo passo del planner).
- **Chiamate**: 21 × (1 classificatore `gpt-4o-mini` + 1 planner `gpt-5.6-luna`) = **42**, senza ripetizioni automatiche (`max_retries=0`). Nessun embedding, nessun riordino, nessuna risposta finale.
- **Casi** (`INTEGRATED_ROUTING_CASES`): 8 MovieLens (classifiche, tag, statistiche, voto di un titolo), 3 strutturati (regia+premi, filmografia, collaborazioni), 2 RAG film, 1 RAG serie, 2 combinazioni (RAG film → `cinema_sql`; RAG serie → TVmaze), **1 sulle stagioni (solo TVmaze, nessuna alternativa)**, 4 complementari (streaming TMDb, Rotten Tomatoes OMDb, intervista YouTube, film popolari TMDb).
- **Cosa passa**: tool giusto, argomenti validi come `CinemaSqlInput`/`SeriesRagToolInput`/ecc., `ml_mode`, genere e anni giusti, `parts` che include il secondo tool nelle combinazioni, `source=planner` (nessun ripiego silenzioso).
- **Soglia proposta per procedere**: ≥ 19/21 **e** tutti e tre i casi critici passati: «Quante stagioni ha Breaking Bad?» → TVmaze, la serie+stagioni → `series_rag_search` poi TVmaze, e nessun caso MovieLens finito su `sql` o su `ratings` senza titolo. Un fallimento si corregge nel prompt (non nei test) e si rilancia solo quel caso (`--tool`, 2 chiamate).
- **Costo**: pochi centesimi; il run precedente analogo (23 casi) era di 46 chiamate.
- **Cosa NON misura**: la qualità delle risposte, i RAG, l'interfaccia, i secondi passi delle combinazioni (il run giudica solo il primo passo; i secondi sono coperti da test scriptati).

## Parte B — Qualità semantica reale dei due RAG (richiede embedding veri + LLM)
Perché separata: i vettori memorizzati provano il cablaggio, non cosa succede a un testo scritto da un utente (parser LLM → embedding del testo → ricerca → riordino LLM). Le chiamate per interrogazione del solo RAG (senza planner né risposta finale):
- **RAG film**: parser `gpt-5.6-luna` (1) + embedding `text-embedding-3-large` 1.536 dimensioni (1, più 1 per ogni film citato non presente nell'indice) + riordino `gpt-5.6-sol` di 40 candidati con fino a 1.500 caratteri di trama (1, ~3 s) = **3 chiamate** (la voce più cara è il riordino: ~15–20 k token in ingresso). 
- **RAG serie**: stesso schema (parser + embedding + riordino di 40 candidati a 1.000 caratteri) = **3 chiamate**.
- **Batteria proposta**: **12 richieste film + 12 richieste serie = 24 interrogazioni = 72 chiamate** (più, se si vuole un giudice cieco, 1 chiamata `gpt-5.5` per interrogazione = 24). Richieste film: tema/atmosfera, «come X ma senza Y», filtro per anno, per paese, per regista, per attore, trama da un dettaglio, richiesta contraddittoria, due in inglese. Richieste serie: premessa, «serie come X», puntata da una scena, trama di una stagione, film TV, anime, serie con esclusione, titolo inesistente (deve restituire nulla), due in inglese.
- **Cosa verificare per ogni richiesta**: pertinenza (giudizio umano o cieco), rispetto di filtri ed esclusioni, `imdb_id` ben formato in ogni risultato (film 99,2 %, serie 77,6 %: i mancanti non sono un errore), ordine plausibile, tempi (film riordino ≈ 3 s), nessuna invenzione. In più, per 3 richieste film e 3 serie, il **passaggio a `cinema_sql` per `imdb_id`**.
- **Come eseguirla (harness PRONTO dalla FASE 14, mai eseguito live)**: `movie_db/harness/evaluation/run_rag_semantic_smoke.py`, 24 richieste in `rag_semantic_cases.json`. Prova ridotta (F02, F05, S01, S08 = 2 film + 2 serie, ≤ 12 chiamate): `RAG_SEMANTIC_AUTHORIZED=yes python -m movie_db.harness.evaluation.run_rag_semantic_smoke run --live --set smoke --label trial`; completa: `--set full --label full`. Offline: `plan`, `validate`, `report --label X [--price MODELLO=IN:OUT]`. Dettagli in `PROGRESS.md`, FASE 14. In alternativa le batterie già esistenti, molto più grandi: film `python -m pipelines.wikipedia_films.eval.app_run run --mode new --set main` (62 domande attraverso l'applicazione intera), serie `python -m pipelines.wikipedia_series.eval.run_battery run` (36 domande). **Consiglio di cominciare da 2+2 richieste come prova di costo** (12 chiamate), misurare i token reali e solo dopo estrapolare al resto.
- **Soglia proposta**: ≥ 10/12 film e ≥ 9/12 serie giudicate pertinenti; 0 risultati con filtro violato; la richiesta con titolo inesistente restituisce vuoto.

## Parte C — Interfaccia nel browser (chiama modelli per ogni domanda)
Checklist di 16 domande con l'esito atteso: `INTEGRATED_FRONTEND_CHECKLIST.md`. Ogni domanda comporta classificatore + planner + (RAG: 3) + risposta finale = **4–8 chiamate**, ~16 domande → ~90 chiamate, i RAG pesano di più. Eseguibile solo dopo la Parte A (altrimenti si perde tempo su routing sbagliato).

## Ordine consigliato
1. Parte B prova di costo (2 film + 2 serie, 12 chiamate) → conferma dei costi.
2. Parte A (42 chiamate) → correzioni di prompt solo sui casi falliti.
3. Parte B completa (72 + 24 chiamate).
4. Parte C (browser) a mano.
5. Se tutto supera le soglie: fase di rimozione di `movie_db_search`, del vecchio RAG e delle dipendenze elencate in FASE 13.

## Cosa serve da te
Un via libera esplicito **per ciascuna parte** (A, B-prova, B-completa, C). Le chiavi sono già nell'ambiente di esecuzione (`.env`, che non leggo); nessuna chiave viene stampata.
