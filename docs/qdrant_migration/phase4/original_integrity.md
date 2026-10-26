# Integrita' di `dbVettoriale/openai` - verifica del 2026-10-26 (prima della Fase 4)

## Processo che teneva aperto il file
- Worker PID 51733 di `uvicorn web_api.main:app --reload` (genitore 90271, avviato il 25/10 alle 01:25 da una shell `zsh -il` aperta il 1/10), in ascolto su `localhost:8000`. **Non** era un processo di test avviato per questa attivita': non e' stato terminato da me. L'utente lo ha fermato.
- Con `--reload`, ogni modifica ai file Python del repo riavvia il worker, che riapre Chroma sull'originale.
- Dopo l'arresto (11:42:52): nessun handle aperto sul file, nessun `uvicorn`, porta 8000 libera.

## Risultato (sola lettura, nessun ripristino)
| Verifica | Esito |
|---|---|
| File HNSW (`data_level0.bin`, `header.bin`, `index_metadata.pickle`, `length.bin`, `link_lists.bin`) | **identici** al manifest iniziale |
| `chroma.sqlite3`, byte per byte | **diverso** dal manifest iniziale (`c202860e...` contro `6319e381...`); hash stabile su due letture consecutive, dimensione invariata (580.067.328 byte) |
| Dati logici (21 tabelle, confronto riga per riga in modalita' `immutable`) | **identici al backup** in 20 tabelle su 21 |
| Tabella diversa | `acquire_write` (`id`, `lock_status`): 296 righe contro 257, cioe' 39 righe in piu' (id 258-296, tutte `lock_status = 1`) |
| Backup | integro (hash = manifest) |

## Interpretazione
La sola differenza e' una tabella di contabilita' dei lock di Chroma, a cui ogni apertura in scrittura aggiunge una riga. Le 39 righe in piu' sono compatibili con i riavvii del worker `--reload` dopo il backup, ma **il numero di aperture non e' stato attribuito riga per riga**: e' un'ipotesi coerente con le evidenze, non una prova.

## Cosa si puo' e non si puo' dichiarare
- Integrita' **dei dati** (embeddings, documenti, metadati, collezioni): verificata come identica al backup.
- Integrita' **byte per byte** dell'originale: **NON valida**. Il file non e' stato ripristinato per far coincidere gli hash. Il riferimento affidabile e' il backup (hash = manifest).
