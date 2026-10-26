# Fase 7 - end-to-end reali su Qdrant (eseguita il 2026-10-26)

Servizi reali: OpenAI (classificatore, planner, parser dei segnali, risposta, embedding), Cohere (rerank), TMDb. Motore `qdrant`, server
ufficiale 1.20.0 sull'indice reale migrato (42.522 punti, intatto a fine corsa), catalogo spento, 20 domande da `questions.json`,
pause di 30 s. Stima costi prima dell'avvio: l'ultimo E2E reale da 20 domande (60 chiamate OpenAI) era costato ~0,04 $; qui ~5-6 chiamate a
turno, ordine di 0,1-0,3 $, con i tetti per turno di `CONFIG` (200.000 token, 12 iterazioni, 180 s). Il costo effettivo non è stato misurato
(il runner non registra l'uso dei token). Prima dell'apertura dello storage: copia verificata per hash in
`~/Backups/NetflixScout/qdrant_storage-20261026-pre-phase7`; a fine corsa lo storage reale è identico alla copia (202 file, stessi hash).

Risultati grezzi: `results/` (una risposta per domanda + `summary.json`). Pre-classificazione meccanica: 20 completed, 0 partial, 0 missed, 0 error
(nessun errore di turno, nessun fallback silenzioso, nessun esito di tool vuoto o errato).

## Giudizio (un solo valutatore, il modello; letto sulle risposte e sulle tracce - evidenza indicativa, non statistica)
| Esito | Domande |
|---|---|
| Pieno | r01, r02, r04 (hybrid scelto dal planner: personaggio nominato), r05, r07, r08, r09, d01, d02, d03, t01, t02, t03, x01 (bloccata) |
| Parziale | r03, r06, r10 (retrieval debole: il vincolo di paese/tema non è verificabile e i titoli sono solo plausibili; le risposte lo dichiarano e non inventano), m01 (consiglia un film e ne dà la regia; il film è debolmente legato a *Mare dentro*), f01 (il follow-up passa a TMDb `discover` con parola chiave "time travel" e dichiara che viaggio nel tempo e finale triste non sono verificabili) |
| Errato | nessuno |
| Corretto durante la fase | t04 (vedi sotto) |

Nessun riferimento a Chroma: tutte le risposte RAG vengono da Qdrant. Nessuna violazione dei vincoli di metadati verificabili.

## Difetti trovati e corretti (con test)
1. **t04 "Cosa esce al cinema questo mese?"**: le schede delle liste TMDb (chart/discover) non portavano la data di uscita, quindi il modello non poteva rispondere.
   Fix: `uscita <data>` nelle schede di lista (`tool/tmdb/prompt_budget.py:card_text`; le schede di dettaglio non cambiano). Test in `tests/test_tmdb_facets_videos.py`.
2. Dopo il fix 1 il modello dichiarava di non conoscere la data odierna. Fix: `metadata.tmdb.today` per `chart`, `discover_movies`, `discover_tv`
   (dato del tool, nessun prompt di sistema modificato). Riesecuzione di t04: risposta corretta, raggruppata in "già usciti"/"in arrivo" con date (`results_rerun_t04_b/`).
La prima riesecuzione (`results_rerun_t04/`) documenta il passo intermedio.

## Limiti
Un solo run, un solo valutatore; nessun confronto cieco con Chroma (la Fase 5 ha già lasciato spenta la ricerca guidata); le domande 'parziali' sono
limiti di recupero semantico/vincoli non verificabili già noti, non regressioni dimostrate del motore (la parità del retrieval è in `phase4/`).
Non provato: ricostruzione reale dell'indice, immagine Docker.
