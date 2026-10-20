# AGENTS.md — NetflixScout

Guida operativa per agenti IA. Leggila prima di modificare il codice.

## 1. Contesto del Progetto

**Scopo**: assistente conversazionale da terminale che consiglia film usando RAG sul CMU Movie Summary Corpus e un DB SQL locale read-only di MovieLens 32M (voti, classifiche, generi per anno, tag). Risponde solo a domande cinematografiche (classificatore anti off-topic e anti jailbreak).

**Stack**
- Python 3.11 (`.venv/` locale), nessun `pyproject.toml`: le dipendenze stanno in `requirements.txt` (versioni pinnate).
- LLM ed embedding: `openai` (Responses API + Chat Completions per il classificatore), `sentence-transformers`/`torch` per gli embedding locali.
- Vector store: `chromadb` persistente in `dbVettoriale/<backend>/` (`openai` | `local`), similarità cosine.
- Retrieval: semantico, BM25 (`rank-bm25`), ibrido con RRF.
- DB MovieLens: `sqlite3` della stdlib; CSV e DB in `movie_db/data/` (ignorata da git, read-only a runtime).
- Rerank: `cohere` (`rerank-v3.5`) oppure LLM.
- Modelli dati: `pydantic` v2. Loader: `pypdf`, `python-docx`, `beautifulsoup4`, `markdown-it-py`.
- Test: `pytest`. Nessun linter o formatter configurato.

**Flusso a runtime** (`app.py`)
```
input + ultimi classifier_context_messages della history → classify_query_domain (gpt-4o-mini, JSON) ──non cinema──→ messaggio di blocco it/en
                         │ cinema
                         ▼
LLMOrchestrator (orchestrator.py) → sceglie il tool → RagTool.run → run_rag (retrieve + rerank, nessuna generazione)
                                                   oppure MovieDbTool.run → parser LLM → MovieDbQuery → SQL whitelistato read-only
                         ▼
l'orchestratore genera la risposta finale → history → compattazione oltre memory_window_size
```

**Mappa del codice**
| Percorso | Ruolo |
|---|---|
| `app.py` | `CONFIG` unico (sezioni `orchestrator` e `rag`), `build_runtime_config` (deep merge degli override), `build_app`, `handle_query` (nucleo senza print → `TurnResult`), loop da terminale |
| `turn.py` | `TraceStep` e `TurnResult`: risultato di un turno neutro rispetto al canale |
| `presenters/` | output per canale: `present(turn, channel)` è l'unico `if`; `terminal/` stampa il resoconto, `web/` è predisposto (`NotImplementedError`) |
| `orchestrator.py` | `Tool` Protocol + `LLMOrchestrator` (selezione del tool, fallback, risposta finale) |
| `rag/EmbeddingProcess/` | pipeline offline: `loaders/` → `clean.py` → `chunk.py` (`chunk_semantic`) → embed → index (`buildSemanticDb.py`) |
| `rag/FromQueryEmbeddingToRes/` | runtime: `pipeline.run_rag`, `retrieval.py`, `rerank.py`, `hybrid.py`, `vectorstore.py`, `embeddings.py`, `models.py`, `tool_interface.py` (`RagTool`, `rag_search`), `runtime.py`, `conversation.py` |
| `rag/FromQueryEmbeddingToRes/query_classifier/` | classificatore di dominio e lingua **attuale** |
| `buildSemanticDb.py`, `movie_metadata.py` (root) | shim che reindirizzano a `rag/EmbeddingProcess/` |
| `movie_db/config.py`, `movie_db/schema.py` | `MovieDbConfig` (vista validata di `CONFIG["movie_db"]`, senza default) e tabelle/DDL condivise |
| `movie_db/tool/` | **runtime**: `MovieDbTool`, `parser.py`, `models.py` (`MovieDbOperation`, `MovieDbQuery`), `trace.py`, `results.py`; `sql/` = `connection.py` (read-only), `guard.py` (authorizer + timeout), `queries.py` (SQL whitelistato), `repository.py` |
| `movie_db/harness/` | **offline, mai importato a runtime**: `ingestion/` (unico scrittore del DB), `fixtures/` (mini MovieLens), `evaluation/` (`cases.py` + `run_eval.py` per il parser, `routing_cases.py` + `run_routing_eval.py` per il routing) |
| `movie_db/data/` | dati, non codice: `raw/ml-32m/*.csv` (zip di GroupLens scompattato) e `movielens32m.sqlite3` (~1,3 GB); versionato solo `.gitkeep` |
| `buildMovieDb.py` (root) | shim verso `movie_db/harness/ingestion/build.py` |
| `presenters/movie_db_view.py`, `presenters/{terminal,web}/movie_db/` | vista condivisa dello step `db_query`, stampa da terminale, serializzazione web |
| `tests/` | `test_query_language.py`, `test_presenters.py`, `test_orchestrator.py` e `test_retrieval.py` (offline, con mock), `test_movie_db_*.py` (offline, DB fixture costruito in `conftest.py`), `test_tool_contract.py` (**integrazione**: chiama API reali e Chroma) |
| `dataset/`, `dbVettoriale/` | artefatti locali, ignorati da git |

Nota: il README è in parte obsoleto (cita `run_rag`/`execute_tool` esposti da `app.py`). In caso di conflitto conta il codice.

## 2. Comandi Utili

```bash
# Setup (macOS/Linux)
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest
cp .env.example .env   # inserisci OPENAI_API_KEY e COHERE_API_KEY

# Dataset: CMU Movie Summary Corpus → dataset/MovieSummaries/
#   https://www.cs.cmu.edu/~ark/personas/

# Build del DB vettoriale (CANCELLA e ricrea dbVettoriale/<backend>/)
python buildSemanticDb.py --embedding-backend openai     # oppure: local
#   opzioni: --dataset-dir dataset --db-dir PATH --collection netflix_scout
#            --semantic-threshold 0.78 --embedding-model text-embedding-3-small --batch-size 128

# Dataset MovieLens: ml-32m.zip da https://grouplens.org/datasets/movielens/32m/
#   unzip ml-32m.zip -d movie_db/data/raw   → movie_db/data/raw/ml-32m/*.csv
# Build del DB MovieLens (~3-4 min, ~1,3 GB; non sovrascrive senza --force)
python buildMovieDb.py            # opzioni: --source-dir DIR --db-path FILE --force

# Valutazione offline del tool DB sul mini dataset: gratis, parser scriptato
python -m movie_db.harness.evaluation.run_eval
# Stessi 6 casi con il parser LLM reale: 6 chiamate gpt-5.6-luna (consuma crediti)
python -m movie_db.harness.evaluation.run_eval --live-parser
# Routing DB/RAG su 11 domande: 11 classificatore (gpt-4o-mini) + 11 planner (gpt-5.6-luna), nessun tool eseguito
python -m movie_db.harness.evaluation.run_routing_eval --live

# Avvio della chat interattiva (exit/quit per uscire)
python app.py

# Test
python -m pytest tests/test_query_language.py tests/test_presenters.py tests/test_orchestrator.py tests/test_retrieval.py tests/test_movie_db_*.py -q   # offline, veloce, gratis
python -m pytest -q                                # include l'integrazione: servono .env e un DB popolato, consuma crediti API
```

Non c'è uno step di build o packaging: il progetto si esegue da sorgente, dalla root del repo (i path `dbVettoriale/` sono relativi alla CWD).

## 3. Linee Guida di Stile e Architettura

**Formattazione**
- PEP 8, indentazione di 4 spazi, righe di circa 100 caratteri, virgole finali nelle chiamate su più righe.
- `from __future__ import annotations` in testa ai moduli nuovi; type hint moderni (`list[dict]`, `str | None`).
- Import relativi dentro `rag/FromQueryEmbeddingToRes/` (`from .models import ...`), assoluti dalla root (`from rag.FromQueryEmbeddingToRes... import ...`).
- Le funzioni private del modulo hanno il prefisso `_`; argomenti keyword-only (`*`) per le API pubbliche (`run_rag`, `Tool.run`).
- Naming misto italiano/inglese **già esistente** (`recupera`, `genera`, `apri_collection`, `indicizza`, `testo`, `k_largo`, `k_finale`): rispetta il nome già usato nel modulo che tocchi, non rinominare.
- Prompt e messaggi per l'utente finale in italiano, docstring ed errori tecnici in inglese.

**Pattern architetturali**
- **Config-driven**: tutti i parametri (modelli, k, backend, prompt) vivono in `CONFIG` in `app.py`. Niente valori hardcoded nei moduli: passa `config` come dict. Gli override passano da `build_runtime_config(overrides)`.
- `_resolve_runtime_config` normalizza la config RAG (backend effettivo, `db_dir`, default della conversazione): chiamala prima di accedere a vectorstore ed embedding.
- **Contratto dei tool**: ogni tool rispetta il `Tool` Protocol (`name`, `description`, `input_schema`, `run(*, query, params, conversation_history) -> dict`). `input_schema` deriva da un modello Pydantic (`model_json_schema()`). Un nuovo tool si registra in `build_app` e in `CONFIG["orchestrator"]["allowed_tools"]`, senza toccare il core.
- **Separazione dei ruoli**: `RagTool`/`run_rag` restituiscono solo evidenza strutturata (`chunks` + `metadata` + `trace`); la risposta finale la genera solo l'orchestratore.
- **Il nucleo non stampa**: `handle_query` produce un `TurnResult` con gli step (`trace` dei tool inclusa). L'output sta solo in `presenters/<canale>/`. Il canale (`OutputChannel`) lo dichiara l'entry point: `python app.py` → `terminal`, la futura route FastAPI → `web`. Niente `print` fuori da `presenters/terminal/` (eccezioni: builder offline, loop legacy in `chat.py`).
- **Query autonoma per i follow-up**: nella stessa chiamata LLM con cui sceglie il tool, l'orchestratore (`_plan_turn`) riscrive la domanda in modo autonomo usando la history (`standalone_query`) e la passa a **qualunque** tool, anche con `required_tools` o fallback. Senza history o se l'LLM fallisce si usa la domanda originale. La history va passata **intera e invariata** (niente finestre scorrevoli): un prefisso stabile permette al prompt caching del provider di riusarla.
- **Contesto del classificatore**: `handle_query` passa a `classify_query_domain(query, history)` gli ultimi `CONFIG["orchestrator"]["classifier_context_messages"]` messaggi della history. Il guardrail gira prima della riscrittura `standalone_query`: senza contesto un follow-up come "ne puoi trovare 3 più recenti?" verrebbe bloccato. La history serve solo a risolvere riferimenti impliciti; si classifica sempre l'ultima query. Il prompt considera cinematografiche anche le richieste su un film già citato (trama, dettagli, traduzione) in qualsiasi lingua: chiedere la risposta in un'altra lingua non è un jailbreak (prima "Could you get in english the plot from the movie you just advised?" veniva bloccata). Lo step `classification` viene stampato a terminale, così un blocco mostra `is_cinema`/`is_italian`.
- **Trace dei tool**: ogni tool restituisce `"trace": [{kind, title, data}]` fuori da `metadata` (che finisce nel prompt). Un `kind` nuovo va aggiunto in `presenters/terminal/renderer.py:STEP_RENDERERS`, altrimenti viene stampato col fallback generico.
- **Testo dell'embedding**: il corpus è composto da trame in inglese. Il parser `_extract_query_signals` (`retrieval.py`) produce `QuerySignals` in inglese con `semantic_query` (la frase su cui si fa l'embedding) e `genres` (vocabolario del corpus). `vectorstore.search` fa l'embedding di `semantic_query`, altrimenti della query originale, **mai** del join dei `positive_signals`: un insieme di keyword italiane faceva finire il retrieval su film italiani o storici. Il genere non viene indicizzato nel testo: entra nel ranking con il boost `retrieval.genre_boost` sul pool di `retrieval.fetch_k` e nel documento passato al reranker (`rerank._documento_per_rerank`). Lo step `retrieval` del trace riporta `embedded_text` e `signals`.
- **DB MovieLens read-only**: il modello non scrive mai SQL. Il parser riempie un `MovieDbQuery` (enum `MovieDbOperation`, `extra="forbid"`); `sql/queries.py` compone solo frammenti costanti con parametri bind; la connessione è `mode=ro` + `PRAGMA query_only` + authorizer (`guard.py`). Una nuova operazione = valore dell'enum + builder in `QUERY_BUILDERS` + caso in `harness/evaluation/cases.py`. Solo `harness/ingestion/` scrive il DB; `app.py` e `movie_db/tool/` non importano `movie_db/harness/` (verificato da `tests/test_movie_db_app.py`).
- **Trace del tool DB**: un solo step `db_query` con `{"queries": [{"sql", "params"}]}`: niente righe, limiti o path. Terminale e web leggono lo step solo tramite `presenters/movie_db_view.py`, così i due canali mostrano le stesse query.
- **Valutazioni live**: `run_eval --live-parser` e `run_routing_eval --live` sono gli unici controlli che consumano crediti; non sono test pytest (le loro parti offline sono in `tests/test_movie_db_eval.py` e `tests/test_movie_db_routing_eval.py`). Il routing eval chiama solo `classify_query_domain` e `_plan_turn` con un client che registra l'output grezzo, senza modificare l'orchestratore: un fallback silenzioso a `rag_search` è un fallimento. Tra `top_rated` e `by_genre_year` l'equivalenza vale solo con genere e senza anni e con SQL e parametri identici. Ultimo esito: parser 6/6; routing 11/11 (run completo dopo la correzione del prompt del classificatore per i follow-up in altra lingua); end-to-end `python app.py` 5/5 (3 domande DB con follow-up, 1 RAG, 1 fuori tema bloccata).
- **Classificatore e domande statistiche**: il prompt del classificatore considera cinematografiche anche le domande su voti, classifiche, generi e tag senza la parola "film" (prima "Qual è il genere con il voto medio più alto?" veniva bloccata); coperto da `tests/test_query_language.py`.
- **Avvio e DB MovieLens**: con `CONFIG["movie_db"]["enabled"] = True`, `run_terminal_chat` chiama `ensure_db_ready` e si ferma se il DB manca; `enabled=False` non registra il tool. Gli override (es. `min_ratings` per le fixture) passano da `build_runtime_config`, come in `tests/conftest.py` e `harness/evaluation/cases.py:EVAL_OVERRIDES`.
- **Limiti noti dei dati MovieLens**: l'articolo finale viene spostato solo se il titolo non ha un titolo alternativo tra parentesi (`"Kingdom II, The (Riget II)"` resta così); il catalogo include anche serie TV (es. Firefly). Correggere `load_csv.split_title_year` richiede una nuova build con `--force`.
- Enum Pydantic per i valori chiusi (`SearchMode`, `RerankBackend`); nuovi modelli dati in `models.py`.
- Errori espliciti con istruzioni operative (es. collection vuota → "Run `python buildSemanticDb.py ...`").
- Stato della conversazione: lista `history` di `{"role", "content"}` gestita in `app.py`; la compattazione la **sostituisce**, non la estende.

## 4. Regole di Ingaggio per l'IA

**Da fare sempre**
- Aggiungi o aggiorna test `pytest` per ogni modifica di logica. Mocka OpenAI/Cohere con `monkeypatch` (vedi `tests/test_query_language.py`); i nuovi unit test non devono fare chiamate di rete.
- Prima di chiudere un task esegui almeno `python -m pytest tests/test_query_language.py tests/test_presenters.py tests/test_orchestrator.py tests/test_retrieval.py tests/test_movie_db_*.py -q` più i test che hai aggiunto.
- Mantieni la retrocompatibilità del contratto `RagTool.run` e della forma di `CONFIG` (`tests/test_tool_contract.py` la verifica).
- Se cambi comandi, struttura o API pubbliche, aggiorna `README.md` e questo file.

**Non fare senza un permesso esplicito**
- Leggere, stampare o modificare `.env` (contiene chiavi API). Aggiorna solo `.env.example`.
- Lanciare `buildSemanticDb.py` (distruttivo, lento, costoso) o `buildMovieDb.py --force`, o cancellare `dbVettoriale/`, `dataset/`, `movie_db/data/`.
- Eseguire la suite completa o script che chiamano OpenAI/Cohere (costano crediti).
- Cambiare i nomi dei modelli LLM, le versioni pinnate in `requirements.txt` o i prompt di sistema (classificatore, generazione, compattazione), che sono comportamento di prodotto.
- Indebolire il filtro di dominio e anti jailbreak in `query_classifier/`.
- Aggiungere dipendenze o file di config di tooling (linter, pyproject) senza chiedere.

**Git**
- Messaggi di commit brevi, in inglese, in minuscolo, senza prefissi (stile esistente: `separated concerns`, `migrate db to Qdrant`). Una modifica logica per commit.
- Non fare commit di `.env`, `dataset/`, `dbVettoriale/`, `movie_db/data/` (tranne `.gitkeep`; licenza MovieLens: niente redistribuzione), `.venv/`, `__pycache__/`.
- Commit e push solo se richiesti esplicitamente.
