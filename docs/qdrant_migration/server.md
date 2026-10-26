# Avviare il server Qdrant

Verificato il 2026-10-26 su questa macchina (macOS, x86_64).

## Il comando (da eseguire dalla radice del progetto)
```
cd /Users/filippo.milzagmail.com/Desktop/NetflixScout
QDRANT_BIN=/private/tmp/claude-501/-Users-filippo-milzagmail-com-Desktop-NetflixScout/5bfd1d87-098f-47f2-91bf-6c2ea5a37f18/scratchpad/qdrant_server/bin/qdrant ./scripts/start_qdrant.sh
```
- **Directory di partenza**: la radice del progetto (`/Users/filippo.milzagmail.com/Desktop/NetflixScout`), perché lo script cerca lo storage in
  `dbVettoriale/qdrant_openai/storage` relativo a sé stesso (funziona da qualunque directory, ma il comando qui sopra è quello provato).
- **Storage** (reale, esistente): `/Users/filippo.milzagmail.com/Desktop/NetflixScout/dbVettoriale/qdrant_openai/storage` (collezione `netflix_scout`, 42.522 punti).
- **Binario** (reale, versione verificata con `--version`: `qdrant 1.20.0`): il percorso sopra. **Attenzione: si trova nella cartella temporanea di sessione**
  (`/private/tmp/...`), che il sistema può svuotare. Il binario non è stato installato altrove. Se non c'è più, va riscaricato.
- Lo script mette il server in ascolto solo su `127.0.0.1:6333`, disattiva la telemetria e lo esegue da una cartella temporanea fuori dal repository
  (il server scrive un file `.qdrant-initialized` nella cartella da cui parte). Si ferma con Ctrl+C.
- `QDRANT_BIN` non ha un valore predefinito di proposito; `QDRANT_STORAGE` (facoltativo) sostituisce lo storage, ad esempio per l'indice ricostruito
  `dbVettoriale/qdrant_rebuild/storage`.

## Riscaricare il binario
Release ufficiale `qdrant/qdrant` v1.20.0 su GitHub (https://github.com/qdrant/qdrant/releases/tag/v1.20.0), asset `qdrant-x86_64-apple-darwin.tar.gz`
(l'archivio usato aveva SHA-256 che inizia con `94a2e6f6`; l'hash completo non è stato registrato). Scompattare in una cartella a scelta e puntare
`QDRANT_BIN` al file `qdrant`; `qdrant --version` deve dire `1.20.0` (il client Python è fissato a 1.20.0 e un test controlla la coppia).

## Verifica che sia acceso
`curl http://127.0.0.1:6333/collections` deve elencare `netflix_scout`. Se il server è spento `python app.py` stampa
`Error: Cannot reach Qdrant at http://127.0.0.1:6333 ...` (codice 1) e lo stesso fa `uvicorn web_api.main:app`.

## Docker
Non provato: nessun `docker`/`podman` sulla macchina (ricontrollato il 2026-10-26). Procedura per chiudere il criterio: `docker_status.md`.
