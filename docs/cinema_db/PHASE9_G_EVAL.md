# Fase 9-G — valutazione del planner v2 / v3

66 record validi (0 con errore). Giudizio deterministico; le risposte vanno lette da una persona.

## Stadio 1 — prima decisione del planner

| Caso | Scenario | Stato | Tool / operazione | Atteso | OK | ms |
|---|---|---|---|---|---|---|
| V01 | verified film | v2 | cinema_sql/crew | cinema_sql crew/work_card/find_work | sì | 5911 |
| V01 | verified film | v2 | cinema_sql/crew | cinema_sql crew/work_card/find_work | sì | 4975 |
| V01 | verified film | v3 | cinema_sql/crew | cinema_sql crew/work_card/find_work | sì | 5788 |
| V01 | verified film | v3 | cinema_sql/crew | cinema_sql crew/work_card/find_work | sì | 2618 |
| V02 | uncertain identity | v2 | cinema_sql/work_card | cinema_sql/tmdb_search find_work/work_card | sì | 2853 |
| V02 | uncertain identity | v3 | cinema_sql/work_card | cinema_sql/tmdb_search find_work/work_card | sì | 2924 |
| V03 | by director | v2 | cinema_sql/filmography | cinema_sql filmography | sì | 3415 |
| V03 | by director | v2 | cinema_sql/filmography | cinema_sql filmography | sì | 4447 |
| V03 | by director | v3 | cinema_sql/filmography | cinema_sql filmography | sì | 3114 |
| V03 | by director | v3 | cinema_sql/filmography | cinema_sql filmography | sì | 2390 |
| V04 | main cast | v2 | tmdb_search/- | cinema_sql/tmdb_search cast | sì | 2941 |
| V04 | main cast | v3 | cinema_sql/cast | cinema_sql/tmdb_search cast | sì | 2363 |
| V05 | audience ratings of a title | v2 | movie_db_search/- | cinema_sql ratings | **NO** | 2848 |
| V05 | audience ratings of a title | v3 | cinema_sql/ratings | cinema_sql ratings | sì | 2458 |
| V06 | Metascore and Rotten Tomatoes | v2 | omdb_search/- | omdb_search  | sì | 2747 |
| V06 | Metascore and Rotten Tomatoes | v2 | omdb_search/- | omdb_search  | sì | 2859 |
| V06 | Metascore and Rotten Tomatoes | v3 | omdb_search/- | omdb_search  | sì | 3294 |
| V06 | Metascore and Rotten Tomatoes | v3 | omdb_search/- | omdb_search  | sì | 2705 |
| V07 | ranking by genre | v2 | movie_db_search/- | movie_db_search  | sì | 4661 |
| V07 | ranking by genre | v2 | movie_db_search/- | movie_db_search  | sì | 4654 |
| V07 | ranking by genre | v3 | cinema_sql/sql | movie_db_search  | **NO** | 6633 |
| V07 | ranking by genre | v3 | movie_db_search/- | movie_db_search  | sì | 2810 |
| V08 | information absent from the database | v2 | cinema_sql/awards | cinema_sql awards | sì | 2699 |
| V08 | information absent from the database | v3 | cinema_sql/awards | cinema_sql awards | sì | 2804 |
| V09 | namesake titles | v2 | tmdb_search/- | tmdb_search/cinema_sql/wikidata_search find_work | sì | 3634 |
| V09 | namesake titles | v2 | tmdb_search/- | tmdb_search/cinema_sql/wikidata_search find_work | sì | 2840 |
| V09 | namesake titles | v3 | tmdb_search/- | tmdb_search/cinema_sql/wikidata_search find_work | sì | 2790 |
| V09 | namesake titles | v3 | tmdb_search/- | tmdb_search/cinema_sql/wikidata_search find_work | sì | 2598 |
| V10 | person with a canonical identity | v2 | cinema_sql/filmography | cinema_sql filmography | sì | 3584 |
| V10 | person with a canonical identity | v2 | cinema_sql/filmography | cinema_sql filmography | sì | 2803 |
| V10 | person with a canonical identity | v3 | cinema_sql/filmography | cinema_sql filmography | sì | 3050 |
| V10 | person with a canonical identity | v3 | cinema_sql/filmography | cinema_sql filmography | sì | 2786 |
| V11 | dynamic data | v2 | tmdb_search/- | tmdb_search  | sì | 5467 |
| V11 | dynamic data | v2 | tmdb_search/- | tmdb_search  | sì | 5401 |
| V11 | dynamic data | v3 | tmdb_search/- | tmdb_search  | sì | 5413 |
| V11 | dynamic data | v3 | tmdb_search/- | tmdb_search  | sì | 4516 |
| V12 | provenance on request | v2 | cinema_sql/provenance | cinema_sql provenance | sì | 3309 |
| V12 | provenance on request | v2 | cinema_sql/provenance | cinema_sql provenance | sì | 2745 |
| V12 | provenance on request | v3 | cinema_sql/provenance | cinema_sql provenance | sì | 2760 |
| V12 | provenance on request | v3 | cinema_sql/provenance | cinema_sql provenance | sì | 2367 |
| V13 | ratings with the user-ratings preference | v2 | movie_db_search/- | cinema_sql ratings | sì | 3596 |
| V13 | ratings with the user-ratings preference | v3 | cinema_sql/ratings | cinema_sql ratings | sì | 2591 |
| V14 | reviews preference with critics' scores | v2 | omdb_search/- | omdb_search  | sì | 4787 |
| V14 | reviews preference with critics' scores | v2 | omdb_search/- | omdb_search  | sì | 4774 |
| V14 | reviews preference with critics' scores | v3 | omdb_search/- | omdb_search  | sì | 3431 |
| V14 | reviews preference with critics' scores | v3 | omdb_search/- | omdb_search  | sì | 6379 |

## Stadio 2 — turno completo

| Caso | Stato | Tool | Passi esterni | Entro il tetto | Vietati | Fatti | Livello detto | HTTP | s | Passi tool |
|---|---|---|---|---|---|---|---|---|---|---|
| V02 | v2 | cinema_sql>tmdb_search | 1 | sì | - | sì | sì | 3 | 13.01 | 2 |
| V02 | v3 | cinema_sql>tmdb_search | 1 | sì | - | sì | sì | 3 | 12.37 | 2 |
| V03 | v2 | cinema_sql | 0 | sì | - | sì | sì | 0 | 12.08 | 1 |
| V03 | v3 | cinema_sql | 0 | sì | - | sì | sì | 0 | 8.42 | 1 |
| V04 | v2 | tmdb_search | 1 | sì | - | sì | sì | 2 | 6.13 | 1 |
| V04 | v3 | cinema_sql | 0 | sì | - | sì | sì | 0 | 7.31 | 1 |
| V05 | v2 | movie_db_search | 1 | sì | movie_db_search | sì | sì | 0 | 8.95 | 1 |
| V05 | v2 | cinema_sql>omdb_search | 1 | sì | - | **NO** | sì | 1 | 15.42 | 2 |
| V05 | v3 | cinema_sql | 0 | sì | - | sì | sì | 0 | 6.38 | 1 |
| V05 | v3 | cinema_sql | 0 | sì | - | sì | sì | 0 | 5.91 | 1 |
| V08 | v2 | cinema_sql>wikipedia_search | 1 | sì | - | sì | sì | 2 | 15.51 | 2 |
| V08 | v3 | cinema_sql>wikipedia_search | 1 | sì | - | sì | sì | 2 | 16.07 | 2 |
| V10 | v2 | cinema_sql | 0 | sì | - | sì | sì | 0 | 10.27 | 1 |
| V10 | v3 | cinema_sql | 0 | sì | - | sì | sì | 0 | 10.89 | 1 |
| V12 | v2 | cinema_sql>wikipedia_search>tmdb_search | 2 | **NO** | - | sì | sì | 3 | 18.57 | 3 |
| V12 | v3 | cinema_sql | 0 | sì | - | sì | sì | 0 | 7.51 | 1 |
| V13 | v2 | movie_db_search | 1 | sì | - | sì | sì | 0 | 8.47 | 1 |
| V13 | v2 | movie_db_search | 1 | sì | - | sì | sì | 0 | 9.12 | 1 |
| V13 | v3 | cinema_sql | 0 | sì | - | sì | sì | 0 | 7.31 | 1 |
| V13 | v3 | cinema_sql | 0 | sì | - | sì | sì | 0 | 6.69 | 1 |

## Confronto

- routing v2: 22/23 first_ok, mediana 3.6 s
- routing v3: 22/23 first_ok, mediana 2.8 s
- full v2: 9/10 within_external_budget, mediana 11.2 s, passi esterni medi 0.90
- full v3: 10/10 within_external_budget, mediana 7.4 s, passi esterni medi 0.20

## Correzione delle prestazioni delle operazioni per persona (2026-11-09, quinta tornata)

**Causa.** La vista v3 `v_credit` calcolava `person_id` con `COALESCE(ec.canonical_entity_id, c.person_id)`: il filtro `person_id = ?` non poteva usare `credit_person` e SQLite partiva dalla scansione di tutte le opere. Piano PRIMA (conteggio dei crediti di una persona): `SEARCH w USING COVERING INDEX work_kind_year (kind=?)` → `SEARCH c USING INDEX credit_work (work_id=?)` per ogni opera, con sottoquery correlata (~2–4 s). Una seconda causa, indipendente: `top_collaborators` univa due volte la vista, e SQLite non spinge una condizione di join nei due rami di una vista composta (`SCAN b`, lettura di tutti i crediti).
**Correzione.** (1) `cinema_db/schema_v3.py`: `v_credit` a due rami `UNION ALL` — persone non fuse con `c.person_id`, e le 12 fuse tramite `entity_canonical` sotto la persona canonica (stessa esclusione dei doppioni di prima). (2) `tool/cinema_db/queries.py:top_collaborators`: le opere della persona vengono da un `WHERE b.work_id IN (SELECT ...)` invece del secondo join (stesso risultato; verificato uguale sul v2). Piano DOPO: `SEARCH c USING INDEX credit_person (person_id=?)` nel ramo 1 e `SEARCH ec USING COVERING INDEX entity_canonical_target (canonical_entity_id=?)` + `SEARCH c USING INDEX credit_person` nel ramo 2. `v_award_result` e `v_name` NON modificate: nessun problema dimostrato (`awards` 131 ms, nessun timeout; `v_name` 2 ms). Nessuna tabella, indice o colonna nuova; nomi, colonne e semantica delle viste invariati; policy rigenerata (`approved_views_v3.py`: cambia solo `STRUCTURE_DIGEST`, perché include il testo delle viste); `generate --check` exit 0.
**Ricostruzione.** `python -m cinema_db.harness.build.imdb_layer --out cinema_db/data/cinema.v3.candidate2.sqlite3` (943 s). **Nuovo file di riferimento: `cinema.v3.candidate2.sqlite3`**, 1.050.517.504 B, `content_sha256` = **`9db2c80d694e21183aa4a14738b237df322a09d8227b85aab7292a7cda5ff667`, identico alla precedente** (il digest copre i dati, non le viste: i dati sono invariati). Il file differisce solo nella definizione della vista. **Riproducibilità:** seconda build indipendente (`candidate2.verify.sqlite3`, 831 s): stesso digest dei dati e **stesso SHA-256 del file intero**. La candidata precedente `cinema.v3.candidate.sqlite3` è conservata come rollback (non toccata), come `candidate.verify`, le altre v3 e il v2 (`c888ebd0…`, invariato).
**Correttezza.** `integrity_check` ok; `foreign_key_check` 0; `v_credit`: 1.932.856 righe prima e dopo, insieme di tutte le righe e colonne **identico** (differenza simmetrica 0); le 12 persone fuse: stessi crediti sotto la canonica e nessuno rimasto sotto l'id fuso; le altre 23 viste: stessi conteggi e stesso SQL. `verify_reconciled` (confronto con la candidata precedente): 0 variazioni di tipo/anno/durata, 100 interrogazioni campione senza errori.
**Prestazioni** (file reali, 5 ripetizioni, macchina libera; "1ª" = prima chiamata, "med" = mediana delle successive; timeout di riferimento 2 s):
| Operazione | v2 | v3 prima | v3 dopo |
|---|---|---|---|
| `filmography` Nolan, senza filtri | 42 / 34 ms (4 query) | **timeout** | 44 / 43 ms (5 query) |
| `filmography` Nolan, ruolo e tipo | 34 / 34 | 1.326 / 1.133 | 43 / 44 |
| `filmography` Brad Pitt | 33 / 34 | **timeout** | 49 / 49 |
| `filmography` Fellini | 32 / 34 | **timeout** | 44 / 45 |
| `collaborations` Nolan | 28 / 29 (2 query) | 1.158 / 1.161 | 36 / 35 |
| `collaborations` Nolan + Bale | 33 / 32 | **timeout** | 41 / 43 |
| `find_person` Nolan | 22 / 22 | 1.825 / 1.819 | 26 / 25 |
| `awards` Nolan | 27 / 29 | 178 / 129 | 129 / 131 (non è un blocco) |
| `cast` Heat | 38 / 35 | 47 / 42 | 45 / 43 |
Apertura del file: 8–17 ms in tutti e tre i casi. Nessun timeout; la v3 costa una query in più (+7–15 ms), non decine di volte. Test aggiunto sul file reale con tetto di 0,6 s (`tests/test_cinema_sql_v3_real.py`); suite del cinema, preferenze e `tool_package`: 692 passati, 1 saltato.

### Tre turni completi (V03, V10, V12; 1 ripetizione)
| Caso | v2 | v3 |
|---|---|---|
| V03 filmografia Nolan | `cinema_sql`, 12,1 s; 13 film, «tra i registrati», avvisa che può essere incompleto | `cinema_sql`, 8,4 s; stessi 13 film più il cortometraggio *Tarantella* (1989), stesso avviso |
| V10 Brad Pitt, «sono tanti?» | `cinema_sql`, 10,3 s; 58 opere, 25 mostrate | `cinema_sql`, 10,9 s; 87 opere, 25 mostrate; la v3 ha più crediti (ad esempio *Fight Club*, assente dal v2); dichiara che comprende film TV e cortometraggi. La persona canonica non ha creato doppioni |
| V12 provenienza di Alien | **3 passi** (`cinema_sql` senza l'operazione → Wikipedia → TMDb), 3 HTTP, 18,6 s; risponde con anno e ID social, dice che «non c'è scheda di provenienza» | `cinema_sql` operazione `provenance`, 0 HTTP, 7,5 s (tool 449 ms, di cui SQL 394); anno 1979, ID (EIDR, IMDb, TMDb, Wikidata, Wikipedia), dichiara che non è indicata una fonte specifica |
Differenza di funzionalità V12: `provenance` esiste solo nel v3 (il v2 non ha claim né ID alternativi); sul v2 il planner la sceglie comunque e spreca un passo. Token: planner v2 74.296 in / 1.107 out (5 chiamate), v3 45.922 / 502 (3 chiamate); risposte v2 13.518 in, v3 10.669 in. Latenza totale: v2 41,0 s, v3 26,8 s (la differenza viene soprattutto dai passi evitati in V12; V03 e V10 sono nel rumore). Chiamate esterne: v2 3, v3 0. Nessuna informazione inventata.
**Consumo di questa tornata:** 20 chiamate LLM (8 planner, 6 risposte, 6 classificazioni) ≈ 144 k token in. **Cumulato della validazione 9-G:** ≈ 114 chiamate LLM, ≈ 1,18 M token in, 16 richieste HTTP esterne.
**Aperti:** una sola ripetizione per cella; `provenance` costa 0,4 s (1,1 s alla prima chiamata) e `awards` 130 ms sulla v3 (accettabili); il v2 non ha lo schema del planner adattato alla versione (V12); i livelli `rule_based` non sono mai stati provati con il modello reale; l'attivazione resta decisione del proprietario.

## Verifica finale con la candidata definitiva (2026-11-09, sesta tornata)
**Candidata:** `cinema_db/data/cinema.v3.candidate2.sqlite3`, schema 3, `content_sha256` `9db2c80d694e21183aa4a14738b237df322a09d8227b85aab7292a7cda5ff667`, `integrity_check` ok, 25 viste, `generate --check` exit 0; v2 `c888ebd0…` invariato. **V07 (decisione del planner, ripetizione 3):** v2 `movie_db_search` (4,8 s, 14.601 token in) e v3 `movie_db_search` (2,7 s, 15.276 in): corretti, terza conferma consecutiva con la regola corretta. **V13 (turno completo, ripetizione 3):** v3 `cinema_sql`, 0 HTTP, 7,6 s: 8,7/10 su 2.631.238 voti (8 nov 2026) e 4,1334/5 su 37.157 (13 ott 2023), «voti del pubblico, non giudizi della critica», scale non convertite né mediate, nessun giudizio qualitativo (terza risposta v3 consecutiva pulita). v2 questa volta ha usato `tmdb_search` (2 HTTP, 10,3 s): «8,5/10 dal pubblico su 41.816 voti», corretto ma una sola fonte e senza data (variabilità del planner v2 tra run: MovieLens, MovieLens, TMDb). Consumo: 4 chiamate LLM (2 planner, 2 risposte; più 2 classificazioni) ≈ 37 k token in, 2 richieste HTTP (TMDb, v2). **Cumulato 9-G:** ≈ 120 chiamate LLM, ≈ 1,22 M token in.
