# AGENTS.md — NetflixScout

Guida operativa per agenti IA. Leggila prima di modificare il codice.

## 1. Contesto del Progetto

**Scopo**: assistente conversazionale da terminale che consiglia film usando RAG sul CMU Movie Summary Corpus. Risponde solo a domande cinematografiche (classificatore anti off-topic e anti jailbreak).

**Stack**
- Python 3.11 (`.venv/` locale), nessun `pyproject.toml`: le dipendenze stanno in `requirements.txt` (versioni pinnate).
- LLM ed embedding: `openai` (Responses API + Chat Completions per il classificatore), `sentence-transformers`/`torch` per gli embedding locali.
- Vector store: `chromadb` persistente in `dbVettoriale/<backend>/` (`openai` | `local`), similarità cosine.
- Retrieval: semantico, BM25 (`rank-bm25`), ibrido con RRF.
- Rerank: `cohere` (`rerank-v3.5`) oppure LLM.
- Modelli dati: `pydantic` v2. Loader: `pypdf`, `python-docx`, `beautifulsoup4`, `markdown-it-py`.
- Test: `pytest`. Nessun linter o formatter configurato.

**Flusso a runtime** (`app.py`)
```
input → classify_query_domain (gpt-4o-mini, JSON) ──non cinema──→ messaggio di blocco it/en
                         │ cinema
                         ▼
LLMOrchestrator (orchestrator.py) → sceglie il tool → RagTool.run → run_rag (retrieve + rerank, nessuna generazione)
                         ▼
l'orchestratore genera la risposta finale → history → compattazione oltre memory_window_size
```

**Mappa del codice**
| Percorso | Ruolo |
|---|---|
| `app.py` | `CONFIG` unico (sezioni `orchestrator` e `rag`), `build_runtime_config` (deep merge degli override), `build_app`, chat da terminale |
| `orchestrator.py` | `Tool` Protocol + `LLMOrchestrator` (selezione del tool, fallback, risposta finale) |
| `rag/EmbeddingProcess/` | pipeline offline: `loaders/` → `clean.py` → `chunk.py` (`chunk_semantic`) → embed → index (`buildSemanticDb.py`) |
| `rag/FromQueryEmbeddingToRes/` | runtime: `pipeline.run_rag`, `retrieval.py`, `rerank.py`, `hybrid.py`, `vectorstore.py`, `embeddings.py`, `models.py`, `tool_interface.py` (`RagTool`, `rag_search`), `runtime.py`, `conversation.py`, `cli.py` |
| `rag/FromQueryEmbeddingToRes/query_classifier/` | classificatore di dominio e lingua **attuale** |
| `buildSemanticDb.py`, `movie_metadata.py` (root) | shim che reindirizzano a `rag/EmbeddingProcess/` |
| `tests/` | `test_query_language.py` (offline, con mock), `test_tool_contract.py` (**integrazione**: chiama API reali e Chroma) |
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

# Avvio della chat interattiva (exit/quit per uscire)
python app.py

# Test
python -m pytest tests/test_query_language.py -q   # offline, veloce, gratis
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
- **Separazione dei ruoli**: `RagTool`/`run_rag` restituiscono solo evidenza strutturata (`chunks` + `metadata`); la risposta finale la genera solo l'orchestratore.
- Enum Pydantic per i valori chiusi (`SearchMode`, `RerankBackend`); nuovi modelli dati in `models.py`.
- Errori espliciti con istruzioni operative (es. collection vuota → "Run `python buildSemanticDb.py ...`").
- Stato della conversazione: lista `history` di `{"role", "content"}` gestita in `app.py`; la compattazione la **sostituisce**, non la estende.

## 4. Regole di Ingaggio per l'IA

**Da fare sempre**
- Aggiungi o aggiorna test `pytest` per ogni modifica di logica. Mocka OpenAI/Cohere con `monkeypatch` (vedi `tests/test_query_language.py`); i nuovi unit test non devono fare chiamate di rete.
- Prima di chiudere un task esegui almeno `python -m pytest tests/test_query_language.py -q` più i test che hai aggiunto.
- Mantieni la retrocompatibilità del contratto `RagTool.run` e della forma di `CONFIG` (`tests/test_tool_contract.py` la verifica).
- Se cambi comandi, struttura o API pubbliche, aggiorna `README.md` e questo file.

**Non fare senza un permesso esplicito**
- Leggere, stampare o modificare `.env` (contiene chiavi API). Aggiorna solo `.env.example`.
- Lanciare `buildSemanticDb.py` (distruttivo, lento, costoso) o cancellare `dbVettoriale/`, `dataset/`.
- Eseguire la suite completa o script che chiamano OpenAI/Cohere (costano crediti).
- Cambiare i nomi dei modelli LLM, le versioni pinnate in `requirements.txt` o i prompt di sistema (classificatore, generazione, compattazione), che sono comportamento di prodotto.
- Indebolire il filtro di dominio e anti jailbreak in `query_classifier/`.
- Aggiungere dipendenze o file di config di tooling (linter, pyproject) senza chiedere.

**Git**
- Messaggi di commit brevi, in inglese, in minuscolo, senza prefissi (stile esistente: `separated concerns`, `migrate db to Qdrant`). Una modifica logica per commit.
- Non fare commit di `.env`, `dataset/`, `dbVettoriale/`, `.venv/`, `__pycache__/`.
- Commit e push solo se richiesti esplicitamente.
