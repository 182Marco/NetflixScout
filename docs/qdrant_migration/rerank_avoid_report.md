# "Simili a X, diversi da Y": misura e correzione (2026-10-26)

## Problema
Nelle 20 domande "simile a X, ma lontano da Y" il recupero e il reranker Cohere restituivano pochi film davvero vicini a X: nei log il pool da 10 conteneva
in media 3,3 film pertinenti e il reranker ne perdeva spesso (es. *Tin Toy* scartato per *Hell & Back*). Il testo da incorporare conteneva anche ciò che si voleva
evitare ("avoiding …"), e il reranker vedeva solo una descrizione, non i due film.

## Metodo (fisso prima di misurare)
- 40 domande: le 20 originali (stesse query standalone/planner della prova di riferimento) + 20 nuove coppie (`questions2.json`, in scratchpad).
- Giudice: `gpt-5.6-luna` con rubrica fissa, un film alla volta: vicinanza al primo film 0/1/2 e distanza dal secondo 0/1/2 (2 = stessa esperienza / nulla in comune con Y).
  Il film citato stesso conta come cattivo. Metrica principale: quota di film "buoni" tra i 3 finali (vicinanza 2 e distanza >= 1) e medie di vicinanza/distanza.
- Confronti appaiati per domanda con bootstrap (IC 95 %). Rumore misurato: due esecuzioni dello stesso codice differiscono di ~0,06 sulle medie.
- Limite dichiarato: il giudice è un LLM (della stessa famiglia del reranker nuovo). Controllo manuale su 14 domande: le liste dopo sono visibilmente migliori
  (es. Toy Story: *Parade of the Wooden Soldiers*, *A Town Called Panic*, *The Brave Little Toaster Goes to Mars* al posto di *Hell & Back*, *Madagascar 2*).

## Varianti (40 domande; differenze rispetto al riferimento, IC 95 %)
| Variante | vicinanza | distanza | film buoni | Esito |
|---|---|---|---|---|
| riferimento (codice precedente) | 1,47 | 1,16 | 0,44 | - |
| campo `avoid_query` (embedding solo del voluto) | +0,06 [-0,05; +0,16] | +0,06 [-0,02; +0,14] | +0,05 [-0,05; +0,16] | non significativo |
| pool 30, Cohere | +0,08 [0,00; +0,17] | +0,01 | +0,09 [0,00; +0,18] | borderline |
| fusione Cohere "voluto - da evitare" (λ 0,25-2) su pool identici | 0 | ~0 / peggiora per λ>=1 | 0 / -0,03 | **nessun beneficio: RIMOSSA** |
| `avoid_query` + pool 30 + reranker LLM | +0,20 [+0,10; +0,30] | +0,02 | +0,18 [+0,08; +0,28] | significativo |
| `avoid_query` + pool 50 + reranker LLM | **+0,33 [+0,24; +0,43]** | +0,01 | **+0,34 [+0,24; +0,43]** | **adottata** |
Il reranker Cohere sullo stesso pool batte di poco l'ordine del recupero (film buoni 0,47 contro 0,42, non significativo): il colpevole principale non era Cohere.

## Cosa è stato adottato (`CONFIG["rag"]`)
- `signals.avoid_query = True`: il parser mette in `avoid_query` ciò che l'utente vuole evitare (tono/stile del film Y) e tiene `semantic_query` solo sul voluto.
- `rerank.avoid_llm = True`, `rerank.avoid_pool = 50`: se il parser trova qualcosa da evitare, il pool candidato è di 50 e lo ordina un LLM che conosce i film citati
  (`rerank_llm_request`); ogni errore ricade su Cohere. Le trame senza titolo nei metadati non partecipano. Senza `avoid_query` nulla cambia (Cohere, pool 10).

## Prova finale end-to-end (stesse identiche 20 domande, orchestratore reale, 30 s di pausa)
| | prima | dopo |
|---|---|---|
| completo / parziale / errato (rubrica fissa) | 2 / 17 / 1 | 2 / 18 / 0 |
| vicinanza rispettata / parziale / non rispettata | 45 / 50 / 5 % | 70 / 30 / 0 % |
| distanza rispettata / parziale / non rispettata | 25 / 75 / 0 % | 25 / 75 / 0 % |
| vicinanza media (0-2) | 1,43 | 1,70 (+0,27 [+0,07; +0,48]; 11 meglio, 2 peggio, 7 uguali) |
| distanza media (0-2) | 1,25 | 1,25 (+0,00 [-0,10; +0,10]) |
| film buoni tra i finali | 0,45 | 0,72 (+0,27 [+0,12; +0,42]; 11 meglio, 1 peggio) |
Nella prima ripetizione (prima di escludere le trame senza titolo) 2 finali su 60 erano senza titolo: corretto e rimisurato.

## Regressione sulle richieste ordinarie (20 domande RAG delle due batterie Fase 7, vecchia contro nuova configurazione, aderenza 0-2)
1,50 contro 1,45: -0,05 [-0,20; +0,08], 4 peggio / 4 meglio / 12 uguali. Non significativo; il cambio non è dimostrato dannoso, ma neanche dimostrato utile fuori dal caso "diverso da".

## Limiti strutturali (non risolvibili con modifiche al codice)
- Copertura temporale: 5 dei 20 "primi film" sono usciti dopo il 2012 (Interstellar, Grand Budapest Hotel, Blade Runner 2049, The Conjuring, Parasite) e non esistono nell'indice; per due titoli esiste un film omonimo diverso
  (*Whiplash* 1948, *Arrival* 1996). Per questi il sistema non può usare il film come riferimento; il reranker LLM usa solo la sua conoscenza del titolo.
- L'embedding delle trame raggruppa per temi superficiali: i vicini del vettore del primo film (quando esiste) non sono migliori del pool testuale (close==2: 3,6 su 10 contro 3,3), quindi un recupero guidato dal vettore del film
  non risolve il problema (coerente con la Fase 5).
- Il corpus è fatto di trame Wikipedia di molti film minori: i titoli famosi simili sono pochi (la distanza media resta 1,2/2: spesso il genere di Y è condiviso).
- La "distanza" dipende dalla conoscenza di Y del modello: non è migliorata in modo misurabile.
- Il film citato può ancora comparire (1 finale su 60: *Little Miss Sunshine*) se il parser non lo mette tra le esclusioni.
- Costo: una chiamata LLM in più (~10k token di ingresso) e circa 10-25 s di latenza per le sole richieste "diverso da".
