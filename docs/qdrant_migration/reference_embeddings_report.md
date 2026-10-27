# Embedding persistenti dei film di riferimento ("simile a X, diverso da Y") - misura (2026-10-27)

## Cosa fa (implementato, ATTIVO di default)
Un film citato come riferimento ha un vettore reale: dall'indice se c'è, altrimenti dalla sua trama TMDb inglese (embedding creato una volta e salvato in Qdrant come `tmdb:movie:<id>`,
oppure collegato al punto del corpus della stessa opera). I vettori entrano nella ricerca Qdrant come esempi positivi (X) e negativi (Y) insieme al vettore della query. Codice:
`reference_flow.py` (flusso), `film_record.read_film` (TMDb, identità verificata), `references.py`/`vectorstore.search(references=)`, `store/catalog.py` (persistenza, collegamento,
spareggio fra omonimi per titolo scritto e attore). Stato finale: `rag.signals.reference_titles = True` e `rag.reference.enabled = True`, strategia predefinita `best_score` (`rag.reference.strategy`). La ricerca è guidata dai riferimenti solo se almeno un riferimento POSITIVO è risolto; altrimenti si esegue la ricerca normale e la traccia lo dice (`no_positive_reference_resolved`). ChromaDB è stato rimosso: Qdrant è l'unico motore.

## Test automatici (offline, nessuna rete) - NON provano il miglioramento
`tests/test_reference_flow.py` (30), `test_reference_pipeline.py` (4), `test_tmdb_film_record.py` (+5), `test_catalog_app.py` (+2), `test_qdrant_catalog.py` (+1): film presente, assente, positivo,
positivo+negativo, omonimo, trama assente/corta, ripetizioni senza duplicati, errori e limiti, vettore passato a Qdrant = vettore persistito. Ultima esecuzione completa della cartella `tests` (prima della rimozione di Chroma): 1939 passati, 23 saltati (richiedono un server). Dopo la rimozione sono stati rieseguiti solo test mirati, non la suite completa.

## Prove end-to-end reali (clone pulito dello storage, orchestratore + OpenAI + TMDb + Qdrant)
| Scenario | Tracce |
|---|---|
| A. Dark Knight (presente) / Deadpool (assente) | X dall'indice (0 chiamate TMDb, 0 embedding); Y: 2 chiamate TMDb, 1 embedding della trama, punto `tmdb:movie:293660`; punti 42.522 → 42.523 |
| B. Interstellar (assente) / Star Wars (1977) | X inserito (`tmdb:movie:157336`, +1); Y collegato al punto CMU (nessun duplicato, nessun embedding) |
| C. ripetizione di B | 0 chiamate TMDb, 0 embedding, punti invariati (42.524), X ora risolto dall'indice (origine `catalog`) |
| D. Whiplash (2014) / La La Land | `tmdb:movie:244786` inserito (non il *Whiplash* 1948 dell'indice), +2 punti |
Punti letti da Qdrant: dimensione 1536, norma 1,0, `source=tmdb`, `version=1`, `fetched_ts`. Uso nella ricerca: la ricerca `RecommendQuery` rifatta in modo indipendente con i vettori PERSISTITI contiene tutto il pool
candidato (49/49, 50/50, 50/50). Indice reale: identico alla copia di backup dopo tutte le prove (le scritture sono andate solo sui cloni).

## Confronto su 40 domande (stesse domande, stesso giudice a rubrica fissa, controllo = riferimenti spenti sul clone pulito)
| Variante | film buoni | film cattivi | vicinanza media (R/P/N %) | distanza media (R/P/N %) | film citato restituito | completo/parziale/errato |
|---|---|---|---|---|---|---|
| R0 controllo | 72 % | 9/120 | 1,71 (82/18/0) | 1,16 (18/80/2) | 5 film in 5 domande | 2/37/1 |
| R1 average_vector (prima della correzione Contact) | 72 % | 4/120 | 1,75 (75/25/0) | 1,21 (20/78/2) | 0 | 5/34/1 |
| R1b average_vector | 74 % | 3/120 | 1,74 (80/20/0) | 1,17 (12/88/0) | 0 | 3/37/0 |
| R2 best_score | 75 % | 1/120 | 1,76 (82/18/0) | 1,20 (18/82/0) | 0 | 5/35/0 |
| R3 average_vector, query x2 | 72 % | 1/120 | 1,73 (75/25/0) | 1,21 (20/80/0) | 0 | 4/36/0 |
Differenze appaiate rispetto al controllo (IC 95 %): film buoni R1b +0,02 [-0,08; +0,12], R2 +0,03 [-0,08; +0,13], R3 -0,01 [-0,11; +0,09]; vicinanza +0,03/+0,05/+0,02 (tutte comprese fra -0,10 e +0,16); distanza
+0,01/+0,04/+0,05 (comprese fra -0,07 e +0,12); film cattivi per domanda -0,15 [-0,30; -0,03], -0,20 [-0,38; -0,05], -0,20 [-0,33; -0,07] (significativo); film citato restituito -0,12 [-0,23; -0,03] (significativo).
Le tre strategie fra loro: nessuna differenza distinguibile (R2 contro R1b: buoni +0,01 [-0,07; +0,09]).

### Per presenza nell'indice originale (R0 → R1b / R2 / R3, film buoni)
- primo film presente (32): 73 % → 79 / 80 / 77 %; vicinanza 1,71 → 1,80 / 1,81 / 1,78.
- primo film assente (6): 72 % → 67 / 72 / 61 %; vicinanza 1,72 → 1,61 / 1,72 / 1,61 (nessun vantaggio dalla trama TMDb rispetto alla parafrasi; campione minuscolo).
- primo film non risolto (2): 67 % → 17 / 0 / 17 % (vedi sotto).
- secondo film presente (31): 77 % → 74 / 76 / 74 %; secondo assente (7): 52 % → 71 / 71 / 57 %.

## Domande RAG generali (20 richieste senza "diverso da", riferimenti spenti contro accesi con best_score, aderenza 0-2)
1,533 contro 1,550: +0,017 [-0,117; +0,133], 3 meglio / 1 peggio / 16 uguali: nessuna regressione.

## Conclusione
Misurato: i riferimenti con vettore reale NON migliorano in modo dimostrabile la qualità né la somiglianza né la distanza (intervalli che includono lo zero, 40 domande, un giudice LLM). Eliminano però una classe di errori
(il film citato che torna fra i consigliati: 5 su 40 → 0) e riducono i film cattivi. Il passaggio che limita il risultato non è il vettore di X: il vicinato di un vettore di trama resta fatto di film minori simili per temi superficiali
(già visto in Fase 5 e nella prova dei vicini), e la distanza da Y dipende dalla conoscenza di Y del reranker.
Difetto emerso e CORRETTO: se il riferimento positivo non si risolveva ma c'era un negativo, la ricerca era "guidata" solo da testo meno Y e peggiorava (2 domande: 67 % → 17 %). Ora la guida richiede almeno un riferimento positivo risolto; con un solo negativo si torna alla ricerca normale. La correzione è coperta da test offline; **dopo la correzione non è stata rifatta la misura sulle 40 domande**, quindi nessun miglioramento di punteggio è dimostrato (una stima precedente di circa 76 % per R1b era solo una stima).
Strategia: `best_score` è predefinita perché nominalmente la migliore nel confronto (75 % contro 74 % di `average_vector`), ma la differenza NON è statisticamente distinguibile; la riduzione dei film cattivi e dei film citati restituiti è invece netta nelle misure.
Secondo limite: omonimi con stesso titolo e stesso anno su TMDb (*Arrival* 2016) restano `ambiguous` per la regola di identità rigorosa.
Limiti statistici: 40 domande (32/6/2 e 31/7/2 nelle partizioni), un solo giudice LLM della stessa famiglia del reranker, un solo run per variante (rumore ~0,06 sulle medie), classi di presenza ricavate dalle tracce.
