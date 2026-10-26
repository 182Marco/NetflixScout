> **Aggiornamento 2026-10-26:** questo rapporto descrive la Fase 6. Da allora Qdrant è il motore PREDEFINITO e l'avvio con server irraggiungibile dà un messaggio di una riga (`build_ready_app_or_exit`); il test di integrazione, la Fase 7 e la ricostruzione sono eseguiti. Stato attuale: `README.md` di questa cartella.

# Fase 6 - Qdrant nell'applicazione e nella Web API (2026-10-26)

Ricerca normale attiva; `average_vector`/`best_score` NON attivati (`CONFIG["rag"]["reference"]["enabled"] = False`); orchestratore invariato; nessuna chiamata a pagamento; Chroma (codice, dati, backup, test) non rimosso. Il default dell'applicazione resta **Chroma**: Qdrant si sceglie con l'ambiente.

## Cosa e' cambiato
- `app.py`: `vector_store_overrides()` legge `VECTORSTORE_ENGINE` (chroma|qdrant) e `VECTORSTORE_QDRANT_MODE/URL/PATH`; `build_ready_app()` (unico punto d'ingresso comune di `python app.py` e della Web API) li applica e gli `overrides` espliciti prevalgono; messaggio operativo per collezione Qdrant vuota.
- `store/collection.py`: `QdrantUnavailable` (server irraggiungibile -> messaggio con cosa fare, senza traceback concatenato ne' chiave); `QDRANT_API_KEY` letta solo qui, mai nella config.
- `vectorstore.py`: `import chromadb` reso pigro (solo nei rami Chroma): importare `app` non carica piu' Chroma.
- `.env.example`: le cinque nuove variabili, vuote (= default).
- `web_api/harness/qdrant_live_check.py`: controllo manuale di un turno web completo sull'indice reale (come `live_stream_check.py`, senza chiamate a pagamento).
- Test: `tests/test_qdrant_app_integration.py` (12) e whitelist di `tests/test_tool_package.py`.

## Verifiche eseguite (server Qdrant 1.20.0 su 127.0.0.1, indice reale da 42.522 punti)
| Verifica | Esito |
|---|---|
| `python app.py` con `VECTORSTORE_ENGINE=qdrant`, input `exit` | banner e chiusura puliti, exit code 0, ~2,6 s |
| stessa esecuzione con `chromadb` bloccato a livello di import | exit code 0, `chromadb` mai importato |
| prova inversa: indirizzo Qdrant sbagliato | exit code 1 con `QdrantUnavailable` e istruzioni (dimostra che il percorso Qdrant e' davvero usato) |
| `uvicorn web_api.main:app` (porta 8001) con motore Qdrant | avvio completo; `/health` 200, `POST /conversations` 201, `GET` 200, messaggio vuoto 422, conversazione ignota 404, `DELETE` 204 |
| turno web completo su indice reale (HTTP -> SSE -> `handle_query` -> `RagTool` -> Qdrant), 4 query | HTTP 200, step `retrieval`+`rerank`, tool `rag_search`, pool = baseline Chroma in 3/4 (q21: differenza gia' documentata in Fase 4, Qdrant piu' vicino all'esatta) |
| suite offline completa | 1677 passati, 15 saltati (varianti server senza `QDRANT_URL`) |
| validazione integrale dei dati Qdrant dopo i riavvii | tutti i controlli OK |
| originale `dbVettoriale/openai`, backup, `dataset/` | originale identico allo stato pre-Fase 4 (nessun handle), backup e dataset integri |

## Non eseguibile / non eseguito (da non considerare verificato)
- **Un turno reale con modelli veri** (classificatore, planner, embedding, parser dei segnali, Cohere, risposta finale in streaming): richiede chiamate a pagamento. Il flusso SSE e' provato con quelle quattro chiamate sostituite da dati salvati e con un orchestratore che riproduce gli step del vero; il comportamento di `LLMOrchestrator` con Qdrant e' coperto solo dai test esistenti (che usano finti).
- Il reranker Cohere con i risultati di Qdrant (stub che conserva l'ordine).
- `python app.py` con motore **Chroma** non e' stato avviato (avrebbe riaperto l'originale): coperto dai test, non da un avvio.
- Immagine Docker; piu' processi della Web API; persistenza della configurazione di produzione (chiave API, TLS).
- `tests/test_tool_contract.py` (integrazione, chiama API reali e Chroma): non eseguito.
- Aggiornamento di README, AGENTS.md, mappa.html: Fase 8.

## Aperto
- La Web API e il terminale falliscono all'avvio con un traceback il cui ultimo rigo e' il messaggio operativo (comportamento preesistente per gli altri errori di avvio, non modificato).
- L'avvio del terminale con il motore Qdrant richiede il server gia' acceso (nessun avvio automatico).
- Nessun errore del server durante una query (a turno gia' avviato) e' convertito in messaggio operativo: oltre l'ambito di questa fase.
