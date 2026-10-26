# Ricostruzione reale dell'indice Qdrant dai dataset (eseguita il 2026-10-26)

Comando: `python buildSemanticDb.py --engine qdrant --qdrant-mode server --qdrant-url http://127.0.0.1:6411 --collection netflix_scout`
Server ufficiale 1.20.0, storage NUOVO e isolato `dbVettoriale/qdrant_rebuild/storage` (468 MB, tenuto). OpenAI `text-embedding-3-small` reale.
Esito: 42.522 chunk indicizzati (stesso numero dell'indice migrato), nessun errore.

## Confronto con l'indice migrato (`compare_indexes.py`, sola lettura; `compare_report.json`)
- Punti: 42.522 contro 42.522; stessi `legacy_id` e stessi id punto (`uuid5`); 0 solo in uno dei due.
- Documenti e **tutti** i metadati/payload: identici su tutti i punti (0 differenze).
- Vettori: dimensione 1536 ovunque, finiti, non nulli, norma 1 (0 anomalie). Embedding rifatti, quindi non identici bit a bit:
  similarità del coseno media 0,999995, 1° percentile 0,99998, minima 0,9940; 160 punti sotto 0,9999, 67 sotto 0,999, nessuno sotto 0,99.
  Non correlata alla lunghezza del testo (i testi più corti sono tra i più simili): deriva ordinaria del modello, non un difetto.
- Recupero (`retrieval_overlap.txt`): 28 query della baseline con i loro embedding salvati, ricerca esatta sui due indici: sovrapposizione top-10 e
  top-50 = 1,000 (minimo 1,00), stesso primo risultato in 28/28.

Conclusione: la ricostruzione dai dataset riproduce l'indice migrato; la procedura (`rebuild.md`) è validata con l'API reale e un server reale.
