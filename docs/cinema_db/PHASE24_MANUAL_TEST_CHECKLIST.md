# FASE 24 — Checklist dei test manuali (runtime integrato)

Prima: backend riavviato come in `INTEGRATED_LOCAL.md` (§ Riavvio), frontend su `http://localhost:8080`. Le domande chiamano modelli a pagamento (circa 3–8 chiamate ciascuna). In ogni riga: **atteso** → **errore se**. Nel pannello dei passi cerca `cinema_sql_calls`, `series_index`, `retrieval/selection`, `tmdb_calls`, ecc.

## 1. Ricerca strutturata (`cinema_sql`)
1. «Chi ha diretto Parasite e quali premi ha vinto?» → un solo passo `cinema_sql` (regia + premi), nessun altro tool → **errore se** parte anche TMDb/Wikipedia, o se compaiono id interni nel testo.
2. «Elencami la filmografia di Greta Gerwig» → elenco dichiarato come parziale («tra quelli registrati») → **errore se** presentato come completo.
3. «Quali film hanno fatto insieme Scorsese e De Niro?» → `collaborations`, titoli coerenti → **errore se** inventa titoli non in elenco.
4. Titolo ambiguo («Crash») → chiede quale (anno/regista) senza scegliere → **errore se** risponde su uno solo.

## 2. Ricerca semantica film (`rag_search`)
5. «Consigliami un film inquietante ambientato in un faro isolato» → un solo `rag_search`, film con locandina (TMDb per IMDb id) → **errore se** parte `series_rag_search` o `cinema_sql` senza motivo.
6. «Film come Her ma senza storie d'amore» → esclusioni rispettate → **errore se** compare *Her* o un film d'amore dichiarato.

## 3. Ricerca semantica serie (`series_rag_search`)
7. «Consigliami una serie su detective che indagano su casi irrisolti» → passo `series_index`, fonte con licenza → **errore se** usa `rag_search`.
8. «Una puntata in cui un personaggio scopre di essere in una simulazione» → livello episodio → **errore se** restituisce solo serie.

## 4. Richieste miste e routing
9. «Consigliami un film drammatico sul lutto e dimmi chi l'ha diretto e se ha vinto premi» → `rag_search`, poi `cinema_sql` con l'`imdb_id` del film (senza ricerca per titolo) → **errore se** cerca di nuovo per titolo.
10. «Consigliami una serie su una pandemia e dimmi quante stagioni ha» → `series_rag_search`, poi `tvmaze_search` → **errore se** le stagioni vengono da `cinema_sql`.
11. «Voglio un film e una serie sul tema della memoria perduta» → entrambi i RAG, un passo ciascuno.

## 5. Preferenze Film / Serie / Entrambi (impostazione «tipo di contenuto»)
12. **Solo film** + «Serie come Dark» → frase di conflitto per prima, nessuna ricerca → **errore se** cerca film simili o serie.
13. **Solo serie** + «Film come Matrix» → conflitto, nessuna ricerca → **errore se** usa `series_rag_search` come ripiego.
14. **Solo serie** + «Quali serie hanno il tag time travel?» → `cinema_sql` movielens `by_tag` con `type series` → **errore se** dichiara un conflitto (corretto in FASE 23).
15. **Entrambi** + consiglio generico → UN solo RAG (il più probabile) → **errore se** interroga entrambi senza che la domanda lo chieda.

## 6. Tag, classifiche e statistiche MovieLens
16. «Quali opere hanno il tag time travel secondo gli utenti?» → opere con il tipo accanto a ciascuna (film e serie) → **errore se** una serie è presentata come film.
17. «Quali film hanno il tag time travel?» → solo film; «…serie TV…» → solo serie/miniserie.
18. «Quali sono i 10 film meglio votati dal pubblico su IMDb?» → classifica di soli film, scala 10 con numero di voti → **errore se** compaiono serie.
19. «Qual è la classifica dei titoli meglio votati su IMDb?» (senza «film») → la risposta DICHIARA che comprende film e serie.
20. «Qual è il genere con il voto medio più alto secondo gli utenti?» → statistica sui soli film, scala 1–5 → **errore se** mescola scale o nomina una fonte.
21. «I 10 film più votati dagli utenti» → **noto**: può rispondere con i film dal voto medio più alto invece che con più voti (frase ambigua, caso aperto): segnalalo ma non è una regressione.

## 7. Dettagli, cast, registi e filmografie
22. «Cast di Oppenheimer» → TMDb; «regia e durata» → TMDb o `cinema_sql` coerente → **errore se** dati contraddittori senza dirlo.
23. Opera con identità incerta (se capita) → dichiarata «identificata con buona probabilità» o «incerta» → **errore se** la presenta come certa.

## 8. Episodi e prossime uscite TV
24. «Quante stagioni ha Breaking Bad?» e «Quando esce il prossimo episodio di House of the Dragon?» → SEMPRE `tvmaze_search` → **errore se** risponde `cinema_sql` o un RAG.
25. «Elencami gli episodi della seconda stagione di Lost» → `tvmaze_search`, solo numerazione e date, senza trame.

## 9. Tool esterni e fallback
26. «Dove posso vedere Dune in streaming in Italia?» → TMDb con provider e attribuzione JustWatch.
27. «Che punteggio ha Oppenheimer su Rotten Tomatoes e Metacritic?» → OMDb, punteggi con scala; «non disponibile» dichiarato se manca.
28. «Trovami un'intervista al regista di Parasite» → YouTube, link verificabili.
29. «Da quale racconto è tratto The Thing del 1982, e ci sono remake?» → Wikidata, con avvertenza sull'elenco parziale; «storia della produzione di Blade Runner» → Wikipedia.
30. Una serie inventata («Zorblax Quest») → «non trovata», nessuna invenzione, un solo passo di ripiego.

## 10. Frontend, streaming e fonti
31. La risposta scorre mentre si scrive (nessun salto finale). 32. Passi e fonti visibili per ogni tool, con link e licenze (Wikipedia CC BY-SA, TVmaze CC BY-SA, Wikidata CC0); le liste MovieLens mostrano le query SQL eseguite. 33. Le schede dei film (locandina) compaiono solo per i film consigliati. 34. Cambiando lingua al messaggio successivo, la risposta segue l'ultimo messaggio. 35. Un messaggio non cinematografico → rifiuto secco senza passi.
**Errore grave in qualunque scenario**: nome di una fonte nel testo della risposta (TMDb, OMDb, MovieLens…), id interni citati, dati inventati, tool bloccati dalla guardia che riappaiono nei passi, una risposta bloccata o vuota.
