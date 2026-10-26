# Tornare a Chroma (e come NON alterare gli storage)

Il ramo Chroma è mantenuto. Per usarlo: `VECTORSTORE_ENGINE=chroma python app.py` (o l'API web con la stessa variabile).
Apre `dbVettoriale/openai/` (database Chroma originale) senza toccare gli storage Qdrant.

Attenzione: Chroma, aprendo il database, può scrivere piccole tabelle di servizio (lock) nel suo `chroma.sqlite3`: i dati restano gli stessi,
ma l'hash del file cambia. Per provare il ritorno **senza alterare nulla**, ripristina una COPIA e puntala:
```
python docs/qdrant_migration/restore_chroma.py --backup ~/Backups/NetflixScout/pre-qdrant-20261026/openai --dest NUOVA_CARTELLA
VECTORSTORE_ENGINE=chroma python app.py     # con rag.vectorstore.db_dir = NUOVA_CARTELLA (override in build_runtime_config)
```
Qdrant non va fermato né toccato per questo: sono storage separati (`dbVettoriale/qdrant_openai/`, `dbVettoriale/qdrant_rebuild/`).

## Verificato il 2026-10-26
`build_ready_app` con `VECTORSTORE_ENGINE=chroma` su una copia ripristinata: motore Chroma, collezione `chromadb`, 42.522 punti; l'originale non è stato aperto.
Test: `tests/test_qdrant_app_integration.py` (selezione del motore da ambiente, predefinito e ritorno), `tests/test_legacy_chat_engine.py`.
