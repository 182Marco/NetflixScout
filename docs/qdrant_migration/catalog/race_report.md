# Concorrenza delle scritture del catalogo - test B2 sul server reale

Eseguito il 2026-10-26 su Qdrant server 1.20.0 (binario ufficiale, 127.0.0.1:6401, storage temporaneo, collezioni sintetiche
create e cancellate dal test; mai l'indice reale). Client 1.20.0. Harness: `tests/qdrant_catalog_race.py`; processi separati
(spawn), embedding finto deterministico con attese casuali tra lettura e scrittura, osservatore che rilegge il punto in continuo
(~25.000 letture per configurazione).

Scenari (200 giri ciascuno): aggiornamento del testo, creazione in corsa, soli metadati, testo e metadati misti, collegamento CMU
con due `tmdb_id`, timestamp uguali. Controlli: coerenza di ogni stato osservato (hash del testo, vettore del documento, hash dei
metadati, campi derivati), `version` mai decrescente, nessun aggiornamento perso (versione finale >= versione iniziale + scritture
dichiarate applicate), stato finale = scrittore con timestamp più alto (un solo vincitore per timestamp uguali e per i collegamenti),
documento e vettore CMU intatti, nessun duplicato.

| Processi | wait | Con guardie: giri con anomalie / 1200 | Senza guardie (controllo negativo) |
|---|---|---|---|
| 2 | true | 0 | 361 |
| 4 | true | 0 | 396 |
| 2 | false | 0 | non eseguito |
| 4 | false | 0 | non eseguito |

Il controllo negativo discrimina: senza guardie anomalie in tutti gli scenari (anche vettore incoerente con il documento in `mixed`).
Report JSON in `race/`. `tests/test_qdrant_catalog_server.py`: 7 passati sul server (B1 + giro breve con e senza guardie).

## Garanzia effettiva
Nei limiti di questa prova (server 1.20.0, un solo nodo, stesso computer, 2 e 4 scrittori, 1200 giri per configurazione), i confronti
condizionali su `version` e la guardia "`tmdb_id` vuoto" **non hanno mai lasciato passare una scrittura obsoleta né prodotto uno stato
incoerente**. È evidenza sperimentale, non una dimostrazione: la documentazione del server letta non descrive l'atomicità e non è stata
provata con più nodi, più macchine o carichi diversi. Nessun lock è stato aggiunto perché non necessario in questa prova.

## Un'anomalia vista e capita (prima esecuzione, 4 processi, wait=true)
Un giro su 200 riportava `version=5` con 3 scritture dichiarate applicate (seed 1). Non era una perdita: la scrittura di un processo
era applicata ma la sua rilettura vedeva già il `write_id` di un altro scrittore, quindi la dichiarava non applicata (ritenta, poi esce
come `stale`). Stato finale coerente e corretto. La rilettura serve solo a stabilire l'esito: la verifica è stata resa precisa
(l'anomalia vera è `versione < iniziale + dichiarate`) e le riesecuzioni complete non ne hanno mostrate. Limite noto: l'esito riferito
può sottostimare le scritture applicate; i dati no.

## Con wait=false
Solo lo stato memorizzato è giudicato (il read-back del processo può precedere la scrittura): 0 anomalie. In produzione le scritture
del catalogo usano sempre `wait=true`.
