# Ricostruire l'indice Qdrant dai dataset (procedura ripetibile)

**Costo reale**: ~42.000 embedding `text-embedding-3-small` (a pagamento) e ~minuti di calcolo. Eseguita il 2026-10-26 (`rebuild/rebuild_report.md`): 42.522 punti, identica per id, documenti e metadati all'indice migrato. L'indice in uso resta quello migrato (`dbVettoriale/qdrant_openai`); la copia ricostruita è in `dbVettoriale/qdrant_rebuild`.

## Prerequisiti
- `dataset/MovieSummaries/` (CMU Movie Summary Corpus: `plot_summaries.txt`, `movie.metadata.tsv`, `character.metadata.tsv`).
- `OPENAI_API_KEY` in `.env` (non letto né modificato da questi comandi se non dal builder stesso).
- Una cartella nuova (embedded) o una collezione che non esiste (server). La build non sostituisce mai nulla.

## Comandi
```
# embedded (una cartella NUOVA o vuota)
python buildSemanticDb.py --qdrant-mode embedded --qdrant-path dbVettoriale/qdrant_rebuild
# server (collezione NUOVA)
python buildSemanticDb.py --qdrant-mode server --qdrant-url http://127.0.0.1:6333 --collection netflix_scout_rebuild
```
Il builder controlla cartella/collezione **prima** di chiamare gli embedding, valida id univoci, metadati stringa, dimensione costante,
vettori finiti e non nulli, e a fine corsa che il numero di punti sia quello dei chunk. Gli id punto sono gli stessi `uuid5` dell'indice migrato.

## Verifica
Con gli indici nuovo e migrato sullo stesso server: stesso conteggio e stessi `legacy_id`; i testi uguali (`docs/qdrant_migration/phase3/`
ha gli script di manifest); i vettori ricalcolati possono differire di poco da quelli storici (embedding rifatti): confrontare con
`catalog/compare_indexes.py` prima di usarlo. Per usarlo: `VECTORSTORE_QDRANT_PATH`/`URL` e `rag.vectorstore.collection` (nome della collezione).

## Confronto
`python docs/qdrant_migration/rebuild/compare_indexes.py --a URL_MIGRATO --b URL_RICOSTRUITO --report FILE` (sola lettura).

## Cosa NON è verificato
La modalità `embedded` con il dataset completo (RAM ~4 GB); l'immagine Docker.
