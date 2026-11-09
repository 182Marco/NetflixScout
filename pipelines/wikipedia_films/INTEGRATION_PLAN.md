# Piano tecnico: sostituire il vecchio RAG con quello Wikipedia (NON implementato)

Obiettivo: **un solo RAG attivo**, quello Wikipedia (`wikipedia_films_it_v2`, poi alias stabile), unico sistema di retrieval cinematografico; strategia d'uso riscritta (`RAG_USAGE_STRATEGY.md`); preferenze positive e negative; distinzione rigorosa film/serie. **Nessun retriever parallelo, nessuna fusione, nessun ripiego al vecchio RAG.** Il vecchio RAG (`netflix_scout`, `tool/rag/`) resta intatto finché l'integrazione non è verificata nell'applicazione, poi si rimuove (sezione 7). Questo piano sostituisce `INTEGRATION_PROPOSAL.md` (eliminata: proponeva due retriever e fusione RRF).

Stato del codice letto per redigerlo: `app.py`, `orchestrator.py` (parti di pianificazione), `preferences/behavior.py`, `tool/rag/FromQueryEmbeddingToRes/{pipeline,retrieval,vectorstore,references,reference_flow,tool_interface}.py`, `data_coverage.py`, elenco dei test che citano il RAG.

## 1. Principio di migrazione: tenere la forma, cambiare la fonte
`RagTool.run` e `RagResult` (chunks, metadata, trace) restano il contratto verso l'orchestratore; cambiano sorgente dati, parser dei segnali, vincoli e arricchimento. Un cambio di nome della collezione e di modello non basta: il vecchio RAG assume trame inglesi, titoli CMU e punti con `source="cmu"|"tmdb"`.

## 2. File e componenti da modificare

| Componente | Cambio |
|---|---|
| `store/settings.py`, `CONFIG["rag"]["vectorstore"]`, `["embedding"]` (`app.py`) | collezione `wikipedia_films_it_v2` (alias), modello `text-embedding-3-large` con `dimensions=1536`; `ensure_collection_ready` controlla i 41.137 punti |
| `embeddings.py` | parametro `dimensions` nelle chiamate; cache della query |
| `store/collection.py`, `vectorstore.py` | lettura dei payload nuovi (`film_id`, `title`, `year`, `director`, `actors`, `genres`, `country`, `duration_minutes`, `imdb_id`, `wikidata_id`, `wikipedia_url`, `synopsis`, `catalog_status`, `unverified`); un punto per film; id deterministici `uuid5(film_id:0)` |
| `models.py` (`RagChunk`) | campi nuovi (regia, cast, durata, paese, ID, `unverified`); sparisce l'assunzione «film CMU» |
| `retrieval.py` (parser dei segnali, `_retrieve`) | la query semantica non si riscrive più in inglese: si embedda il testo dell'utente nella sua lingua (o la sua forma autonoma); il parser produce `like`, `avoid_titles`, `avoid_genres`, `avoid_descriptions`, filtri (anno/decennio, paese, regista, attore, genere, durata); rimozione di `genre_boost` e della mappa generi inglesi |
| `constraints.py` | vincoli su metadati veri dal payload (genere, anno, paese, regista, attore): `verified` quasi sempre; le parole chiave inglesi diventano italiane; nazionalità = `country` (non più «non verificabile») |
| `rerank.py` | documento per il reranker dal payload (titolo, anno, regia, generi, trama); Cohere `rerank-v3.5` è multilingue; l'LLM `avoid_llm` resta opzionale |
| `references.py`, `reference_flow.py` | un film citato si risolve per `title_norm`/anno/`imdb_id` nella collezione; se assente, trama da TMDb **embeddata in memoria e mai scritta nella collezione**; `ReferenceSet` alimenta `negative.py` |
| `store/catalog.py`, `catalog_enricher.py`, `CONFIG["catalog"]`, `app.build_catalog_enricher`, `tool/tmdb/film_record.py` | **rimozione**: scrivevano punti `tmdb:` nella collezione; la v2 è in sola lettura a runtime |
| `hybrid.py` (BM25) | rimosso nella prima versione (ricerca per parole concrete: eventualmente filtro testuale Qdrant); `search_mode` resta solo `semantic` |
| `tool_interface.py` (`RagToolInput`, descrizione) | nuovi argomenti: `like`, `avoid_titles`, `avoid_genres`, `avoid_descriptions`, `filters`; `k_finale`; schema del planner < 3.500 caratteri come gli altri |
| `tool/tmdb/enrich.py` (`TmdbRagEnricher`) | arricchimento **solo** su richiesta (streaming, trailer, voti, immagini) e per `imdb_id` (`/find`), non per titolo; `CONFIG["orchestrator"]["rag_enrichment"]` ridimensionato o spento |
| `negative.py`, `negative_eval.py` (da `pipelines/wikipedia_films/indexing/`) | promossi a modulo del retrieval: pool + penalità λ=0,5, filtri Qdrant, esclusione per id |
| `data_coverage.py`, `tests/test_data_coverage.py` | misura da `films.clean.jsonl`; il RAG non è più «fermo al 2012» |
| `scripts/start_qdrant.sh`, `AGENTS.md`, `README.md`, `mappa.html` | documentare la nuova collezione e il modello |

Fuori da questo elenco, a fine integrazione (sezione 7): `tool/rag/EmbeddingProcess/`, `buildSemanticDb.py`, `movie_metadata.py`, `dataset/MovieSummaries`, `docs/qdrant_migration/`, `tests/test_build_semantic_db.py`, i test del catalogo TMDb→Qdrant, e la collezione `netflix_scout`.

## 3. Istruzioni dell'agente da riscrivere
Testi in `RAG_USAGE_STRATEGY.md`, sezione 6: regola 3 del planner (`CONFIG["orchestrator"]["instructions"]`), richiamo nella regola 1, `data_coverage`, `final_instructions` (tmdb_enrichment, ordine dei film), `CONTENT_PLANNER`, `SOURCE_TOOLS`, `routing_cases.py` (casi RAG e confini con TMDb), e il testo di descrizione del tool. Ogni modifica di prompt cambia il comportamento del prodotto: richiede la tua approvazione esplicita e il routing eval live (a pagamento).

## 4. Ruolo futuro degli strumenti
Tabella in `RAG_USAGE_STRATEGY.md`, sezione 3 (RAG primario per la ricerca semantica; TMDb per dati aggiornati/strutturati/serie; gli altri invariati).

## 5. Preferenze negative
Strategia in `RAG_USAGE_STRATEGY.md`, sezione 5: esclusione per id sempre; penalità semantica λ=0,5 per i film da evitare; filtro `must_not` sui generi del vocabolario; caratteristiche narrative come penalità con descrizione positiva; verifica finale con vincoli e reranker. Implementazione: `negative.py` (già scritto e testato su dati reali locali).

## 6. Film/serie e impostazioni utente
- Il payload ottiene `work_format` e `format_confidence` (derivati dall'audit) e `franchise_id` (da Wikidata P179/P8345, già nello snapshot) con una v3 della collezione, da costruire con `build_clean` esteso e **senza nuovi embedding** (i vettori si riusano); in alternativa aggiornamento del solo payload della v2 (da approvare).
- `preferences/behavior.py`: `content_type = series` → il planner non sceglie `rag_search` anche con descrizione di trama; `film` → operazioni per film; `both` → liste separate (RAG film + TMDb serie). L'intento esplicito dell'utente prevale sulla preferenza, come oggi.
- Nessuna nuova chiamata per effetto delle preferenze (regola dichiarata in `AGENTS.md`).

## 7. Fasi, con criteri di uscita

| Fase | Contenuto | Uscita |
|---|---|---|
| 0 | Alias `wikipedia_films_it` → v2 solo se serve; decisioni aperte (sezione 9) | approvazione |
| 1 | Retriever nuovo dietro un flag di configurazione (`rag.backend = "wikipedia"`), **unica fonte attiva** quando il flag è acceso: non esistono due retriever contemporanei; il vecchio codice resta nel repository ma inattivo; `tests/` adattati offline (mock) | test offline verdi |
| 2 | Parser dei segnali (`like`, `avoid_*`, filtri) e vincoli sul payload; reranker; test dei 7 scenari del punto 2 della Fase 8 | scenari superati |
| 3 | Nuove istruzioni del planner e `RagToolInput`; `routing_cases.py`; `run_routing_eval --live` (a pagamento, con permesso) | routing ≥ della baseline attuale (23/23 + nuovi casi RAG) |
| 4 | Valutazione di qualità nuovo-contro-vecchio su un set fisso di richieste reali (giudice LLM, a pagamento) | criteri della sezione 8 |
| 5 | Spegnere il vecchio RAG (flag), un periodo di verifica nell'applicazione (terminale e web) | nessuna regressione |
| 6 | Rimozione del vecchio RAG: codice, test, dataset CMU, collezione `netflix_scout` (solo dopo backup e tua conferma), pulizia di `AGENTS.md`, `README.md`, `mappa.html` | suite completa verde |

## 8. Test e criteri oggettivi di riuscita

**Regressione (offline):** tutta la suite del progetto (2.067 test) dopo ogni fase; nuovi test per `negative.py`, parser, vincoli sul payload, `ReferenceSet` in memoria, assenza di scritture sulla collezione (test AST/mock: `upsert` mai chiamato a runtime), enricher per `imdb_id`, `content_type` e RAG.

**Qualità (a pagamento, con permesso):**
1. 72 query di Fase 2: Hit@5/@10 e MRR non inferiori a quelli misurati sulla v2 (0,167 / 0,181 / 0,106); giudizi LLM su nuove richieste: precisione@5 della v2 ≥ quella del vecchio RAG sulle stesse richieste.
2. Scenari di preferenze negative (11 locali + varianti con embedding reali): 0 violazioni per titoli ed esclusioni di genere, e rilevanza al positivo non inferiore di più di 0,03 al coseno medio rispetto alla ricerca solo positiva.
3. Routing: tutti i casi esistenti più casi nuovi (film simili con titolo, persona + tema, serie con descrizione di trama → niente RAG) corretti.
4. Serie: 0 serie TV tra le raccomandazioni di film su un set di richieste fissato; 0 chiamate al RAG con `content_type=series`.
5. Chiamate: numero medio di chiamate esterne per turno di raccomandazione non superiore a quello attuale (atteso più basso: niente `tmdb_search` per titolo dopo il RAG).
6. Collezione: dopo la migrazione `netflix_scout` e `wikipedia_films_it` non sono scritte dall'applicazione; `check` della v2 verde.
7. Latenza di una ricerca (embedding + Qdrant + eventuale reranker) entro il valore attuale.

**Dichiarare riuscita l'integrazione** quando i punti 1–7 sono soddisfatti nell'applicazione reale (terminale e web) e nessun percorso del codice attivo importa più il vecchio RAG.

## 9. Decisioni che richiedono la tua approvazione
1. Schede della lista web senza TMDb: arricchimento leggero per `imdb_id` o schede senza poster?
2. v3 del payload (`work_format`, `franchise_id`) o aggiornamento del payload della v2?
3. Rimozione di `hybrid.py` (BM25) nella prima versione.
4. Esclusione del RAG con `content_type=series` anche se l'utente descrive la trama.
5. Budget e permesso per la valutazione di qualità e il routing eval live (stima in `PHASE8_REPORT.md`).

---

# 10. Piano definitivo aggiornato (2026-11-04) — sostituisce le sezioni 7 e 9

Nessuna implementazione eseguita. Decisioni vincolanti in `PROGRESS.md` sezione 0bis.

## 10.1 Architettura
- **Un solo retriever**: Qdrant denso su `wikipedia_films_it_v3`. Niente RRF, fusioni, ripiego al vecchio.
- **v3** (nuova collezione, v2 intatta): payload v2 + `work_format`, `format_confidence` (da `data/audit/classification.jsonl`), `franchise_id` (P179/P8345 dello snapshot; `null` dove manca), `actor_names_norm`; indici `actor_names`, `work_format`, `franchise_id`, full-text su `synopsis`. 41.138 punti: Aftershock incluso con il vettore degli shard di Fase 3. Zero nuovi embedding del catalogo.
- **TMDb**: solo `/find` per `imdb_id` sui `k_finale` film mostrati (poster, id), dentro `tmdb.max_calls_per_turn`; mai per titolo, mai sul pool, nessuna scrittura.
- **Lessicale (BM25 non eliminato)**: titolo = risoluzione su `title_norm`/anno/`imdb_id`; regista e attore = filtri payload normalizzati; parole rare di trama = vincolo full-text nella stessa query densa. A/B da misurare: insieme di candidati BM25 ordinato dal solo vettore (`HasId`). Si adotta il migliore; se nessuno serve, `hybrid.py` esce in Fase F. `search_mode`: `semantic` | `lexical_filter`.

## 10.2 Precedenza delle impostazioni persistenti
**Regola:** una richiesta esplicita in conflitto con un'impostazione non viene eseguita; prevale l'impostazione. La prima frase dichiara il conflitto e quale impostazione prevale; poi si esegue la **lettura compatibile** (stesso tema nella modalità imposta) o ci si ferma. I default sono vincolanti. `content_type=both` non confligge mai. Per `preferred_sources` c'è conflitto solo se la richiesta chiede un'altra fonte.
**Esempi:** series + «consigliami un horror» → serie horror via TMDb, mai RAG; spoiler off + «come finisce X?» → niente finale; medium + «in una riga» → media; technician + «parla da bro» → tecnico; film + «consigliami una serie» → film.
**Applicazione:** (1) il planner (stessa chiamata di `_plan_first`) restituisce `conflicts` ed `effective_content_type`; le istruzioni passano da «criterio secondario» a «vincolo che prevale» (`preferences/behavior.py`); (2) `preferences/guard.py` (pura): con `series` blocca `rag_search`, `movie_db_search` per cercare serie e le operazioni TMDb per film; con `film` blocca `tvmaze_search` e le operazioni TMDb per serie; un passo bloccato è il fallback `blocked_by_setting`, senza chiamata; (3) frase di conflitto fissa it/en/de, passata alla risposta finale come prima frase obbligatoria; prefisso deterministico via `answer_delta` se il live non dà il 100%; (4) terminale: `preferences=None`, invariato. Da riscrivere: `AGENTS.md`, `PLANNER_INTRO`/`CONTENT_ANSWER`/`SPOILER`, `tests/test_preferences_orchestrator.py`, test «intento vince» in `test_tvmaze_app.py`, `test_omdb_app.py`, `test_wikidata_app.py`.

## 10.3 Fasi
| Fase | Contenuto | Uscita |
|---|---|---|
| A | Dati: `reconcile.py`/`plan_overrides.json` (Aftershock), `build_clean.py` esteso, `indexing/v3.py` (crea v3, riusa vettori, `assert_own_collection` esteso), `check` punto per punto, test | v3 verificata, v1/v2/`netflix_scout` intatte |
| B | Retriever standalone in `pipelines/wikipedia_films/retrieval/` (non importato dall'app): filtri, `negative.py` promosso, lessicale A/B; valutazione live del retriever contro il vecchio | criteri 10.4 sul retriever |
| C | Integrazione dietro `rag.backend` (unica fonte attiva); file elencati in sezione 2, più enricher per `imdb_id`; rimozione del flusso catalogo TMDb→Qdrant | suite offline verde |
| D | Precedenza delle impostazioni, istruzioni del planner, `routing_cases.py` | test offline verdi |
| E | Batteria live completa e `run_routing_eval --live`; spegnere il vecchio RAG | criteri 10.4 nell'app (terminale e web) |
| F | Rimozione del vecchio RAG (codice, test, CMU, `netflix_scout` previo backup e conferma), `AGENTS.md`, `README.md`, `mappa.html` | suite completa verde |

## 10.4 Test live e criteri (autonomi, ~80 domande realistiche, stesse domande su vecchio e nuovo, ordine casuale, giudice LLM cieco, ≥2 esecuzioni per i casi instabili)
Gruppi: preferenze positive e negative; esclusione di titoli, franchise e generi; trama, temi, atmosfera; titolo, attori, registi, anno; film e serie (anche trama con `content_type=series`); conflitti per ogni campo; parole rare (A/B lessicale); `run_routing_eval --live` (baseline prima, poi dopo, con casi nuovi).
Criteri: Hit@5/@10/MRR ≥ 0,167/0,181/0,106; precisione@5 nuovo ≥ vecchio; 0 violazioni di titoli e generi esclusi, rilevanza al positivo non peggiore di 0,03 di coseno; 0 serie tra i film e 0 chiamate RAG con `content_type=series`; prima frase di conflitto nel 100% dei conflitti e 0 esecuzioni della richiesta in conflitto; routing ≥ 23/23 più nuovi casi; chiamate esterne per turno ≤ attuali; poster per i film con `imdb_id`; collezioni esistenti mai scritte; latenza ≤ attuale. Risultati grezzi salvati in `pipelines/wikipedia_films/`.

## 10.5 Problemi aperti
Default vincolanti (molte richieste legittime daranno conflitto: misurare l'effetto); rilevamento del conflitto affidato al planner; `franchise_id` parziale; `genres` testo libero; catalogo meno completo dopo il 2019; scelta del lessicale non misurata; spoiler = richiesta al modello; `AGENTS.md` e test esistenti da riscrivere.

## 10.6 Batteria live obbligatoria e confronto A/B (2026-11-04)
**Dati:** `eval/battery.json` (62 domande A–H, con per ciascuna: caratteristiche da mantenere, da evitare, titoli da escludere, franchise da evitare). Non si eliminano casi; si possono aggiungere se emergono lacune. Priorità assoluta: preferenze negative e positive combinate (categorie A–F).
**Regola:** tutte le 62 domande girano sul vecchio RAG (`netflix_scout`) e sul nuovo (v3, che sostituisce v2 appena costruita), entrambi **senza eccezioni di categoria**. Per ogni domanda: retrieval separato, risposte con stesso modello, prompt, parametri e condizioni; giudice LLM cieco con ordine A/B casuale (seme registrato); stessi criteri specifici della domanda; vincitore A/B/pareggio con motivazione; si conservano retrieval, risposte complete, punteggi, tempi.
**Dataset contro algoritmo:** le strategie sono applicate a entrambi i sistemi dove tecnicamente compatibile (griglia 2×N: corpus vecchio/nuovo × strategia), così il vantaggio del dataset si separa da quello dell'algoritmo. Strategie (casi 1–48): (S0) semantico senza esclusioni; (S1) esclusione dei soli id citati; (S2) esclusione per franchise dove disponibile (solo v3: `franchise_id`; nel vecchio per titolo/serie di titoli); (S3) penalità semantica delle descrizioni negative sul pool (λ=0,5, pool 200); (S4) filtri sui metadati di genere e formato; (S5) combinazione positivo+negativo. La sottrazione di vettori non si dà per corretta: si valuta accanto alla penalità sul pool. Incompatibilità note si dichiarano (il vecchio corpus è inglese e finisce al 2012: titoli di riferimento assenti dall'indice si registrano come tali e non si contano a favore dell'algoritmo).
**Metriche separate:** (1) risultati che violano le esclusioni; (2) pertinenza ai tratti positivi; (3) genere richiesto conservato; (4) eliminazione della sola caratteristica negativa contro eliminazione di risultati validi; (5) esclusioni espresse in linguaggio naturale e non come generi o titoli.
**Regola di valutazione (criterio centrale):** non basta che il titolo escluso manchi. «Horror psicologico come Hereditary, ma senza soprannaturale»: un horror soprannaturale è **violazione** anche se non c'entra con Hereditary; un horror psicologico non soprannaturale è **pertinente** anche con trama molto diversa. Il giudice riceve per ogni caso la regola specifica, ricavata da `must_keep`/`must_avoid`.
**Casi H (contraddittori):** il sistema deve riconoscere la contraddizione, chiedere chiarimento quando serve o soddisfare la parte coerente senza inventare una soluzione.
**Output:** risultati A/B per domanda; vittorie/sconfitte/pareggi totali e per categoria; violazioni positive e negative per RAG; confronto delle strategie di esclusione; esempi migliori e peggiori di entrambi; dati grezzi in `eval/results/`. Ogni test live avviene solo quando le Fasi A–C sono pronte.


## 10.7 Esito delle Fasi A–C (2026-11-04) e passi per l'integrazione
Fasi A (v3), B (retriever in `retrieval/`) e C (A/B live su 62+14 domande) **eseguite**; esito in `EVAL_REPORT.md`. Il nuovo RAG supera il vecchio (NEW-S6 4% violazioni / 80% validi contro OLD-NATIVE 10% / 66%; risposte 96/27/1), con le riserve del rapporto. Decisioni di progetto che ne derivano: (1) un solo retriever denso con filtri positivi lato Qdrant, esclusioni per id/franchise-id/genere, penalità sul pool e riordino LLM (S6f; S5f come variante veloce); (2) lessicale = filtro full-text (hit@5 1,00 contro 0,47), BM25 e `hybrid.py` da rimuovere in Fase F; (3) sottrazione di vettori e filtri di genere non adottati per i tratti; (4) pool di riordino 40–50. **Prima dell'integrazione restano**: latenza di S6, categoria D/H, misura degli errori del parser, `franchise_id` parziale, e tutto il lavoro delle Fasi C–D di questo piano (flag `rag.backend`, schema del tool, precedenza delle impostazioni, routing con le nuove istruzioni, enricher TMDb per `imdb_id`), non ancora iniziati.

## 10.8 Esito dell'integrazione (2026-11-05)
Fasi C e D eseguite nell'applicazione: vedi `PROGRESS.md` sezione 15 (cosa è stato implementato, i file, i test, le misure). Decisioni di progetto prese durante l'integrazione: (1) il retriever di produzione vive in `tool/rag/film/retrieval/` e `pipelines/wikipedia_films/retrieval/` resta come strumento di valutazione congelato; (2) il backend si sceglie con `rag.backend` e il rollback è `RAG_BACKEND=legacy` (un solo retriever per volta, nessun ripiego); (3) riordino `gpt-5.6-sol` senza ragionamento, 40 candidati, 1.500 caratteri; (4) arricchimento TMDb solo dei film restituiti, per IMDb id; (5) le impostazioni prevalgono: il planner dichiara i conflitti, la guardia vieta i tool, la frase di conflitto è fissa; (6) il film index richiede il server Qdrant (non la modalità embedded). **Fasi E–F**: spegnere e rimuovere il vecchio RAG solo dopo le verifiche live elencate in `PROGRESS.md` §15 e la conferma del proprietario.
