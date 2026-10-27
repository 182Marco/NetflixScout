# Catalogo TMDb → Qdrant (Estensione A, rev. 3.2)

Stato al 2026-10-26: **implementato offline, spento** (`CONFIG["catalog"]["enabled"] = False`).
Nessuna calibrazione con embedding reali, nessuna attivazione. Il piano completo e le decisioni
stanno nel piano di migrazione; qui il riassunto operativo di ciò che c'è nel codice.

## Cosa fa
Un film citato dall'utente e assente dall'indice viene letto da TMDb (`movie_details` riuscito e con
identità verificata), la sua trama inglese viene incorporata e salvata come punto `tmdb:movie:<id>`
(`source="tmdb"`). Un film già presente nel corpus CMU non viene duplicato: sul punto CMU si scrive solo
`tmdb_id`, mai documento o vettore.

## Dove
| File | Ruolo |
|---|---|
| `tool/tmdb/film_record.py` | lettura `en-US` per ID (mai `localized()`), stesso budget del turno |
| `tool/rag/FromQueryEmbeddingToRes/store/catalog.py` | `CatalogRecord`, `decide_link`, `CatalogStore.sync`, hash, payload |
| `tool/rag/FromQueryEmbeddingToRes/store/genre_map.py` | 6 generi TMDb → vocabolario del corpus |
| `catalog_enricher.py` | ponte neutro su `tmdb_search`: selezione, tetto di 2 film per turno, nessuna eccezione verso l'alto |
| `app.py` (`build_catalog_enricher`) | collegamento; errore all'avvio con Qdrant `memory` |
| `tool/rag/FromQueryEmbeddingToRes/hybrid.py` | una sola voce BM25 per collezione, `invalidate_bm25` |

## Regole che contano
- Testo incorporato = solo la trama inglese (≥ 100 caratteri), altrimenti il film è scartato con il motivo in trace.
- Ogni scrittura su un punto TMDb è un confronto condizionale sulla `version` (creazione solo se assente;
  testo con `upsert(update_filter=version==letta)`; soli metadati con `overwrite_payload` filtrato).
  Il server non dice se la scrittura è stata applicata: `write_id` + rilettura stabiliscono l'esito e permettono
  di riprovare (max 5 tentativi). **La rilettura non è la garanzia**: la garanzia è l'atomicità del confronto sul
  server, provata a parte (`race_report.md`: 0 anomalie su 1200 giri per configurazione con le guardie, centinaia senza).
- Collegamento CMU: candidato unico con anno uguale → collegamento (salvo veto sul cast); ±1 anno, anno CMU
  ignoto o titolo alternativo richiedono un attore in comune; ogni altro caso con candidati = nessuna scrittura.
- Timeout: embedding 15 s senza retry, Qdrant 10 s per chiamata, 20 s complessivi per turno.

## Che cosa NON è stato fatto
- Calibrazione con embedding reali (`calibration/protocol.md`): richiede ~80 embedding e 20-40 chiamate TMDb.
- Attivazione, test end-to-end con LLM reali, copia verificata dello storage Qdrant reale prima di accendere.

## Copia dello storage prima di accendere (procedura)
I film TMDb non si ricostruiscono dal corpus, quindi prima di qualsiasi attivazione:
1. fermare il server Qdrant (una cartella viva non è una copia coerente);
2. `python docs/qdrant_migration/catalog/backup_storage.py backup --storage dbVettoriale/qdrant_openai/storage --dest <CARTELLA NUOVA> --url <URL del server>`
   (rifiuta se la destinazione esiste o è dentro la sorgente, o se il server risponde; legge soltanto la sorgente; scrive un manifesto SHA-256 e rilegge la copia);
3. in qualunque momento: `... verify --storage <sorgente o copia> --dest <altra copia>` (ricalcola gli hash, non si fida del manifesto);
4. la calibrazione C lavora su un clone della copia, mai sullo storage reale.

Copia verificata già disponibile: `~/Backups/NetflixScout/qdrant_storage-20261026-pre-phase7` (202 file, hash verificati; lo storage reale era ancora identico dopo la Fase 7). Rifarla subito prima di accendere se lo storage è cambiato (`backup_storage.py verify`).
