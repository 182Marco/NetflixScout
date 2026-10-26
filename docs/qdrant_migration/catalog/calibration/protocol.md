# Calibrazione C del catalogo (NON eseguita - richiede autorizzazione)

Costo stimato: ~80 embedding (~25k token, frazioni di centesimo di dollaro) + 20-40 chiamate TMDb (gratuite entro quota); il costo effettivo non viene misurato dal codice. Dettaglio: ~80 embedding `text-embedding-3-small` (~25k token) + 20-40 chiamate TMDb. Solo dopo autorizzazione
esplicita del proprietario, su un CLONE dello storage (mai su `dbVettoriale/qdrant_openai`).

## Indici
- **O** = copia dell'indice CMU originale (42.522 punti).
- **E** = clone arricchito con ~20 film passati dal percorso reale di inserimento: ~10 presenti anche in CMU
  (misura del riconoscimento dei duplicati) e ~10 assenti (post-2012).

## Insiemi di query
20 query-bersaglio in EN (trama senza nominare il film) e le stesse in IT; le 28 query di baseline (vettori già
salvati); ~20 query tematiche generiche non legate ai film inseriti.

## Regole di decisione (fissate PRIMA di misurare, nessuna soglia numerica)
- **R1** nessun caso `cmu_migliore` in cui il documento TMDb entrato ha pertinenza 0.
- **R2** nessun documento TMDb compare in più top-10 del documento CMU più frequente nello stesso insieme di query in O.
- **R3** per ogni film assente da CMU, il documento TMDb compare nel top-10 della propria query-bersaglio in inglese
  almeno quanto il documento CMU corrispondente per i film condivisi (stessa procedura).
Se una regola cade, l'attivazione resta spenta e si decide se cambiare il testo incorporato.

## Registro per query
`id`, `tipo` (`target`/`side`), top-10 in O e in E (id, rango, coseno), id entrati/usciti, rango del bersaglio in O e E,
esito del collegamento per i film condivisi. Classi: `unchanged`, `target_found`, `intrusion`; per ogni `intrusion`
confronto cieco a coppie (`tmdb_migliore`/`pari`/`cmu_migliore`), valutatore dichiarato. Campioni piccoli e un
valutatore: evidenza indicativa, non statistica. Ogni caso `cmu_migliore` è elencato uno per uno.

## Script
`calibrate.py` ha le parti pure (classificazione, indicatore di hub, regole R1-R3), provate offline da
`tests/test_catalog_calibration.py`; il sottocomando `plan` stampa cosa farebbe senza rete; `run` si rifiuta di partire
senza `CATALOG_CALIBRATION_AUTHORIZED=yes`.
