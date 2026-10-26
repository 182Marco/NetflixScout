# Fase 8 - pulizia, documenti, commit (stato al 2026-10-26)

## Fatto (non distruttivo)
- AGENTS.md, README.md, mappa.html aggiornati per: motore Qdrant, `store/`, `references.py`, catalogo TMDb (spento), comandi.
- `docs/qdrant_migration/` contiene protocolli, registri e report di tutte le fasi.

## Richiede una decisione del proprietario (non eseguito)
1. Fase 7: ESEGUITA il 2026-10-26 (`phase7/phase7_report.md`: 20 domande su Qdrant, nessun errato, 2 difetti trovati e corretti).
2. Rimozione del codice Chroma: `chromadb` da `requirements.txt`/`imports.txt`, `vectorstore.py` (ramo Chroma), `buildSemanticDb.py`,
   `.gitignore`; solo dopo avvii ripetuti (`python app.py` e web API su Qdrant) e conferma esplicita. I dati Chroma, `diag_*`, `test_*` e i backup NON si cancellano.
3. Togliere la nota "migrate db to Qdrant" da `mappa.html` (l.~648 e ~2660) solo a migrazione chiusa (punti 1-2).
4. Compatibilità Docker: NON provata (nessun runtime di container nell'ambiente, non installato per scelta); provato solo il binario ufficiale 1.20.0. Procedura per chiuderla: `docker_status.md`.
5. Calibrazione C e attivazione del catalogo (`catalog/calibration/protocol.md`), poi copia verificata dello storage reale.
6. Commit: solo su richiesta; messaggio in inglese, minuscolo, che elenchi test eseguiti e non eseguiti.

## Inventario Chroma (per la rimozione, quando deciderete)
File con riferimenti a Chroma fuori da tests/docs: `requirements.txt` (chromadb), `imports.txt`, `.gitignore`, `README.md`, `.env.example`, `AGENTS.md`, `mappa.html`, `app.py` (valore predefinito `engine: chroma`), `vectorstore.py` (ramo Chroma, import pigro),
`hybrid.py` (commento), `buildSemanticDb.py` (costruzione dell'indice: va portato a Qdrant prima di toglierlo), migrazione/validatore (leggono Chroma per costruzione), `store/*`. Test che aprono Chroma: solo `tests/test_tool_contract.py` (integrazione) e i test della migrazione.

## Stato del codice Chroma (2026-10-26)
- FATTO: ricostruzione reale su Qdrant e confronto con l'indice migrato (`rebuild/rebuild_report.md`): identica per id, documenti, metadati; recupero identico sulle 28 query.
- FATTO: Qdrant è il motore PREDEFINITO (`CONFIG["rag"]["vectorstore"]["engine"] = "qdrant"`, server `http://127.0.0.1:6333`). Terminale (`python app.py`), API web (`build_ready_app`), chat legacy (`store_config`) e builder (`--engine`, stesse variabili d'ambiente) partono dalla stessa configurazione; `VECTORSTORE_ENGINE=chroma` è il ritorno indietro. Verificato: `python app.py` esce pulito, `create_app` si costruisce, `tests/test_tool_contract.py` (integrazione) 3/3.
- MANTENUTO di proposito (NON rimosso): il ramo Chroma di `vectorstore.py`, `ChromaTarget`, `chromadb` in `requirements.txt`, `imports.txt`. Motivo: servono ancora a (a) `migrate_chroma_to_qdrant`/`validate_migration`/`restore_chroma` (leggono Chroma per costruzione), (b) al rollback con `VECTORSTORE_ENGINE=chroma` sul database Chroma, che resta, (c) ai test della migrazione. Rimuoverli non è dimostrato non necessario; si toglie quando il proprietario decide di abbandonare la possibilità di ritorno e la migrazione dei dati: in quel caso vanno rimossi insieme `chromadb`, il ramo Chroma, `ChromaTarget`, gli script di migrazione/validazione/ripristino e i loro test. I dati Chroma, i backup e `diag_*`/`test_*` non si cancellano.

## Stabilizzazione finale (2026-10-26)
- Suite: i test che richiedono un server sono marcati (`qdrant_server`, `integration`) e saltano SOLO se il server non risponde, con il motivo scritto (`tests/test_tool_contract.py::test_rag_tool_returns_structured_results` sonda l'URL configurato; se risponde, qualunque errore è un fallimento). Con un server temporaneo isolato (`QDRANT_URL=http://127.0.0.1:6401`, storage temporaneo): 22/22 test `qdrant_server` passati; con il server dell'indice reale: i 3 test di `test_tool_contract.py` passati.
- Avvio con Qdrant su: `python app.py` esce pulito, chat legacy parte e si chiude, API web risponde a `/health` e crea una conversazione. Server irraggiungibile: il terminale stampa `Error: Cannot reach Qdrant at ... Start the server (or set VECTORSTORE_QDRANT_URL ...), or use VECTORSTORE_ENGINE=chroma.` con codice di uscita 1 (senza traceback); l'API web fallisce all'avvio con la stessa `QdrantUnavailable`.
- Ritorno a Chroma: `rollback.md`, provato su una copia.

## Ultimo giro (2026-10-26)
- API web con Qdrant spento: `uvicorn web_api.main:app` costruisce il bot all'import (`build_ready_app_or_exit`) e si ferma con UNA riga (`Error: Cannot reach Qdrant ...`), senza traceback; altri errori di avvio mantengono il traceback. Test: `tests/test_web_api_startup.py` (sottoprocesso, server spento e acceso), `tests/test_qdrant_app_integration.py`.
- Seconda batteria di 20 domande reali: 13 complete, 5 parziali, 2 errate, 0 problemi infrastrutturali (`phase7/phase7_report_v2.md`).
- Docker: ricontrollato, assente. Script di avvio server `scripts/start_qdrant.sh` (3 test) e documento `server.md` con percorsi reali.

## Stato complessivo
Migrazione OPERATIVAMENTE COMPLETA su Qdrant (dati migrati e validati, ricostruzione riproducibile e validata, Fase 7 su servizi reali, predefinito cambiato). Aperti: il criterio Docker (immagine non provata), la rimozione del codice Chroma (decisione), il catalogo TMDb (spento, non calibrato), il commit.
