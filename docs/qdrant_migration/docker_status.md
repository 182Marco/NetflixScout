# Compatibilità con Docker - stato al 2026-10-26: NON PROVATA (ricontrollato il 2026-10-26: `docker` e `podman` assenti)

Nell'ambiente disponibile non ci sono `docker`, `podman`, `colima` né `nerdctl` (verificato), e per istruzione non si installano.
Provato invece, con esito positivo: il **binario ufficiale** Qdrant 1.20.0 (stessa versione del client fissato), eseguito in locale
(spike `spike_server.py`, migrazione, parità, B1/B2 del catalogo in `catalog/race_report.md`). Il binario e l'immagine usano lo
stesso codice del server; non sono provati: il volume Docker, i permessi sul volume, l'avvio con le variabili `QDRANT__...` nel container.

Il criterio "compatibile con la distribuzione Docker" resta **aperto**. Per chiuderlo, su una macchina con Docker:
```
docker run -d -p 6333:6333 -v $PWD/qdrant_storage:/qdrant/storage qdrant/qdrant:v1.20.0
QDRANT_URL=http://127.0.0.1:6333 python -m pytest tests/test_qdrant_store.py tests/test_qdrant_catalog_server.py -q
python -m tool.rag.EmbeddingProcess.migrate_chroma_to_qdrant --chroma-dir <COPIA> --url http://127.0.0.1:6333 --run-dir <DIR>
python -m tool.rag.EmbeddingProcess.validate_migration --chroma-dir <COPIA> --url http://127.0.0.1:6333 --report <FILE>
```
(usare un volume nuovo, mai `dbVettoriale/qdrant_openai`).
