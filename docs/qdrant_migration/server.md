# Avviare il server Qdrant

## Il comando (dalla radice del progetto)
```
./scripts/start_qdrant.sh
```
- **Directory**: la radice del progetto (quella con `app.py`).
- **Cosa avvia**: il server Qdrant 1.20.0 su `127.0.0.1:6333`, con lo storage `dbVettoriale/qdrant_openai/storage` (collezione `netflix_scout`). `QDRANT_STORAGE` (facoltativo) sostituisce lo storage, ad esempio per un indice ricostruito.
- **Binario**: lo script lo cerca in `$QDRANT_BIN`, poi in `bin/qdrant` (cartella ignorata da git), poi nel PATH. Se manca stampa dove scaricarlo e termina con codice 1.
- Telemetria disattivata; il server parte da una cartella temporanea fuori dal repository (scrive lì il file `.qdrant-initialized`). Si ferma con Ctrl+C.

## Scaricare il binario
Release ufficiale `qdrant/qdrant` v1.20.0 (https://github.com/qdrant/qdrant/releases/tag/v1.20.0), asset per la propria piattaforma
(macOS Intel: `qdrant-x86_64-apple-darwin.tar.gz`). Scompattare e mettere il file `qdrant` in `bin/` (oppure puntare `QDRANT_BIN`);
`qdrant --version` deve dire `1.20.0` (il client Python è fissato a 1.20.0 e un test controlla la coppia).

## Verifica che sia acceso
`curl http://127.0.0.1:6333/collections` deve elencare `netflix_scout`. Se il server è spento `python app.py` stampa
`Error: Cannot reach Qdrant at http://127.0.0.1:6333 ...` (codice 1) e lo stesso fa `uvicorn web_api.main:app`.

## Docker
Non provato: nessun `docker`/`podman` sulla macchina. Procedura per chiudere il criterio: `docker_status.md`.
