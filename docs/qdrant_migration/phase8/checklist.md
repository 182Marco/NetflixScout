# Fase 8 - chiusura (stato finale)

## Fatto
- ChromaDB rimosso: codice (`vectorstore.py`, `buildSemanticDb.py`, `runtime.py`, `app.py`), `requirements.txt`, `imports.txt`, `.gitignore`, `.env.example`, test dedicati e strumenti di migrazione/ritorno. Qdrant è l'unico motore; un test statico (`tests/test_no_chroma.py`) impedisce che rientri.
- Ricerca guidata dai film di riferimento attiva (`CONFIG["rag"]["reference"]`, strategia `best_score`), solo se almeno un riferimento positivo è risolto.
- Avvio dei servizi: due comandi (`./scripts/start_qdrant.sh` e `source .venv/bin/activate && uvicorn web_api.main:app --host 127.0.0.1 --port 8000`), documentati in `README.md`, `AGENTS.md`, `server.md` e nella tab «Avvio servizi» di `mappa.html`.
- Documenti aggiornati: `README.md`, `AGENTS.md`, `mappa.html`.

## Aperto
1. Compatibilità Docker: NON provata (nessun runtime di container); provato solo il binario ufficiale 1.20.0 (`docker_status.md`).
2. Catalogo TMDb completo: implementato, spento e non calibrato (`catalog/`).
3. Dati Chroma su disco (`dbVettoriale/openai`, `local`, `diag_*`, `test_*`): inutilizzati, non cancellati; li può eliminare il proprietario.
4. Commit: solo su richiesta.
