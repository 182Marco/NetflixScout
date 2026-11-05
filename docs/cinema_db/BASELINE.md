# Baseline Fase 0 (offline, gratuita)

Generata da `python -m cinema_db.harness.baseline.run_baseline`. **MISURATO** = eseguito sul codice reale dei tool con i transport finti dei test (nessuna rete). **STIMATO** = sequenza dei tool, chiamate del planner e latenze di rete (il planner è un LLM e non è stato eseguito: nessun credito). Il campo `basis` di ogni costo dice quale dei due.

## 1. Richieste HTTP per operazione

| Operazione | Richieste | Base |
|---|---|---|
| `tmdb.details_by_title` | 2 | measured |
| `tmdb.details_by_tmdb_id` | 1 | measured |
| `tmdb.details_by_imdb_id` | 2 | measured |
| `omdb.by_title` | 2 | measured |
| `omdb.by_imdb_id` | 1 | measured |
| `tvmaze.info` | 1 | measured |
| `tvmaze.seasons_episodes` | 3 | measured |
| `tvmaze.next_episode` | 2 | measured |
| `wikidata.resolve_by_title` | 1 | measured |
| `wikidata.resolve_by_imdb_id` | 1 | measured |
| `wikidata.relations_by_title` | 3 | measured |
| `wikidata.relations_by_imdb_id` | 3 | measured |
| `tmdb.person_then_discover` | 2 | estimated: person search + discover (tool/tmdb/operations/discovery.py) |
| `tmdb.collection` | 2 | estimated: movie_details + collection_details |
| `tmdb.providers_or_trailer` | 1 | estimated: movie_details with append_to_response on an id already known |
| `tmdb.trending_or_upcoming` | 1 | estimated: one list endpoint |
| `rag.enrich_5_films` | 5 | estimated: one /find per returned film (by_imdb_only, max_candidates 5) |
| `wikipedia.search_and_article` | 2 | estimated: generator=search then the whole article (cache hit afterwards) |
| `youtube.one_kind` | 2 | estimated: one search.list + one videos.list |
| `movielens.sql_with_type_check` | 10 | estimated: up to 12 /find to drop series (work_type_checker budget) |
| `movielens.sql` | 0 | measured: local SQL |
| `local.sql` | 0 | local, planned |

## 2. 30 domande: oggi vs comportamento desiderato (sequenze STIMATE)

| # | Domanda | HTTP oggi | HTTP dopo | Planner oggi | Planner dopo | Lat. oggi (s, stima) | Lat. dopo (s, stima) |
|---|---|---|---|---|---|---|---|
| 1 | Quali film ha diretto Denis Villeneuve? | 2 | 0 | 1 | 1 | 2.8 | 2.0 |
| 2 | Chi ha scritto la sceneggiatura di Blade Runner? | 2 | 0 | 1 | 1 | 2.8 | 2.0 |
| 3 | Film con Cillian Murphy diretti da Christopher Nolan | 2 | 0 | 1 | 1 | 2.8 | 2.0 |
| 4 | Da quale libro è tratto Blade Runner? | 3 | 0 | 1 | 1 | 9.5 | 2.0 |
| 5 | Esiste un remake di The Thing? | 3 | 0 | 1 | 1 | 9.5 | 2.0 |
| 6 | Quali film fanno parte della saga di Alien? | 3 | 0 | 1 | 1 | 9.5 | 2.0 |
| 7 | Quanti Oscar ha vinto Parasite? | 2 | 0 | 2 | 1 | 5.6 | 2.0 |
| 8 | Chi ha vinto l'Oscar come miglior film nel 1995? | 2 | 0 | 2 | 1 | 5.6 | 2.0 |
| 9 | Distingui i film intitolati Crash (anno, regista, ID) | 1 | 0 | 1 | 1 | 4.5 | 2.0 |
| 10 | Qual è l'ID IMDb di Parasite? | 2 | 0 | 1 | 1 | 2.8 | 2.0 |
| 11 | Quanti film ha diretto Federico Fellini? | 2 | 0 | 1 | 1 | 2.8 | 2.0 |
| 12 | Chi ha composto la colonna sonora di Inception? | 2 | 0 | 1 | 1 | 2.8 | 2.0 |
| 13 | Punteggi della critica per i film di Villeneuve (preferenza reviews, 5 candidati) | 12 | 5 | 6 | 6 | 16.8 | 14.0 |
| 14 | Che Rotten Tomatoes ha Oppenheimer? | 2 | 1 | 1 | 2 | 2.8 | 4.4 |
| 15 | Regista, cast e punteggi della critica di Oppenheimer | 4 | 1 | 2 | 2 | 5.6 | 4.4 |
| 16 | Da cosa è tratto Oppenheimer e che punteggi ha? | 5 | 1 | 2 | 2 | 12.3 | 4.4 |
| 17 | Remake di Solaris e relativo punteggio Metascore | 5 | 1 | 2 | 2 | 12.3 | 4.4 |
| 18 | Interviste a Villeneuve su Dune e suoi premi | 4 | 2 | 3 | 2 | 9.2 | 5.6 |
| 19 | Dove vedo Dune in streaming in Italia? | 2 | 2 | 1 | 1 | 2.8 | 2.8 |
| 20 | Mostrami il trailer di Aftersun | 2 | 2 | 1 | 1 | 2.8 | 2.8 |
| 21 | Quali film escono questo mese? | 1 | 1 | 1 | 1 | 2.4 | 2.4 |
| 22 | Che voto medio ha Pulp Fiction? | 0 | 0 | 1 | 1 | 2.0 | 2.0 |
| 23 | Quali sono i 10 film più votati di sempre? | 10 | 10 | 1 | 1 | 2.0 | 2.0 |
| 24 | Consigliami un film malinconico ambientato in Giappone | 5 | 5 | 1 | 1 | 19.5 | 19.5 |
| 25 | Film come Arrival ma senza alieni | 5 | 5 | 1 | 1 | 19.5 | 19.5 |
| 26 | Quante stagioni ha Breaking Bad? | 3 | 3 | 1 | 1 | 3.2 | 3.2 |
| 27 | Quando esce il prossimo episodio di Severance? | 2 | 2 | 1 | 1 | 2.8 | 2.8 |
| 28 | Storia della Nouvelle Vague | 2 | 2 | 2 | 2 | 5.6 | 5.6 |
| 29 | Interviste al regista di Parasite | 2 | 2 | 1 | 1 | 3.6 | 3.6 |
| 30 | Cast e episodi della seconda stagione di Dark | 4 | 4 | 2 | 2 | 5.6 | 5.6 |

## 3. Totali

| Metrica | Oggi | Dopo |
|---|---|---|
| Richieste HTTP | 96 | 49 |
| Chiamate del planner (stima) | 44 | 42 |
| Passi con tool esterno | 39 | 22 |
| Latenza stimata (s) | 191.79999999999998 | 133.0 |

Domande la cui sequenza cambia: 18 su 30.

## 4. Latenza SQL locale (MISURATA, MovieLens aperto in sola lettura, 20 esecuzioni)

| Query | p50 (ms) | max (ms) |
|---|---|---|
| top_rated_50 | 0.11 | 5.06 |
| by_title | 0.02 | 1.82 |
| genre_stats | 72.49 | 100.05 |

## 5. Cosa dice la misura sul passaggio degli ID (correzione del piano)

- OMDb: per titolo 2 richieste, per IMDb id 1: **risparmio reale di 1 per titolo**.
- TMDb: per titolo 2, per IMDb id 2 (`/find` + dettagli), per TMDb id 1: l'IMDb id **non** risparmia nulla, solo il `tmdb_id` risparmia 1.
- Wikidata: relazioni per titolo 3, per IMDb id 3; `resolve` 1 contro 1: **l'ID non risparmia nulla** quando l'etichetta esatta basta (il ripiego a 3 richieste è raro). Il vantaggio di Wikidata è sostituire l'intero tool con SQL locale (3 richieste fino a 15 s ciascuna), non passare l'ID.
- Una chiamata `cinema_sql` solo per ottenere un ID costa un passo del planner (stimato ~2 s) per risparmiare una richiesta (~0,4 s): **non conviene da sola**. Conviene quando il DB risponde già alla domanda (nessun tool esterno) o quando alimenta una catena che comunque lo richiede (es. OMDb per più candidati).

## 6. Limiti

- Le sequenze dei tool vengono dalle regole di routing, non da un planner eseguito; il vantaggio reale dipende da cosa il planner sceglierà.
- «Dopo» assume che il DB abbia la risposta (premi e incassi hanno copertura parziale: in quel caso si ripiega sul tool online, e il guadagno si perde).
- Le latenze di rete sono stime dalle note live di AGENTS.md; non sono state misurate in questa fase.
- Le operazioni marcate «estimated» non hanno fixture nei test: il loro costo è letto dal codice, non misurato.
