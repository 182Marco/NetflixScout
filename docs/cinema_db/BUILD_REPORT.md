# Rapporto della prima build offline (fase 3)

Generato da `python -m cinema_db.harness.build.verify` sul file reale, in sola lettura. Nessuna rete, nessun credito. Le fonti sono quelle locali (snapshot Wikidata di film e serie, catalogo film v3, catalogo serie s5), non modificate.

## 1. Integrità

- File: **333 MB**; build in 707.4 s.
- `foreign_key_check`: 0 righe; `integrity_check`: ok; indice FTS5: coerente; regole (un solo nome primario per entità): rispettate; trigger: 0.
- Digest del contenuto ricalcolato = memorizzato: **True** (`d9d475d78874901b…`). La policy delle viste approvate accetta il file: **True**.
- Riproducibilità: una seconda build completa (492.5 s) dà lo stesso digest: **True**.

## 2. Righe per tabella

| Tabella | Righe |
|---|---|
| build_info | 6 |
| company | 1,109 |
| country | 183 |
| credit | 532,504 |
| entity | 386,683 |
| entity_name | 739,048 |
| entity_name_fts | 739,048 |
| external_id | 369,683 |
| franchise | 86 |
| genre | 38 |
| genre_label | 1,069 |
| genre_label_map | 688 |
| id_scheme | 11 |
| language | 246 |
| person | 92,041 |
| relation_type | 4 |
| role_type | 16 |
| source | 5 |
| work | 293,447 |
| work_company | 8,490 |
| work_country | 67,479 |
| work_financial | 9,212 |
| work_franchise | 198 |
| work_genre | 123,995 |
| work_kind | 12 |
| work_language | 49,758 |
| work_relation | 4,703 |
| work_release | 50,740 |

## 3. Copertura dei film importati

Film, cortometraggi e film TV del catalogo importati: **40,227**.

| Campo | Film | % |
|---|---|---|
| with_year | 40,197 | 99.9 |
| with_release_date | 39,651 | 98.6 |
| with_runtime | 37,107 | 92.2 |
| with_original_title | 37,957 | 94.4 |
| with_imdb | 39,926 | 99.3 |
| with_tmdb | 37,946 | 94.3 |
| with_eidr | 35,052 | 87.1 |
| with_wikidata_id | 40,199 | 99.9 |
| with_director | 38,776 | 96.4 |
| with_cast | 32,933 | 81.9 |
| with_genre_label | 38,051 | 94.6 |
| with_canonical_genre | 37,833 | 94.0 |
| with_country | 40,047 | 99.6 |
| with_language | 32,573 | 81.0 |
| with_company | 262 | 0.7 |
| with_franchise | 95 | 0.2 |
| with_relation | 2,635 | 6.6 |
| with_release_by_country | 14,048 | 34.9 |
| with_money | 5,033 | 12.5 |

Generi: 1,069 etichette originali, 563 mappate; asserzioni etichetta→opera mappate **92.1%** (114,162 su 123,995). Le etichette non mappate restano leggibili in `v_work_genre_label`.

Tipi di opera: episode 222,557, film 36,529, season 14,176, series 11,764, short 3,427, tv_film 2,817, miniseries 1,901, other 276.

Crediti: cast 416,981, director 48,704, writer 30,240, producer 16,051, composer 7,457, cinematographer 5,335, editor 3,757, creator 1,946, production_designer 1,277, costume_designer 756.

Relazioni: based_on 1,638, follows 3,065.

Nomi: primary 386,683, original 239,905, alias 56,711, translated 55,749.

Identificativi: wikidata 148,096, wikipedia_it 67,212, imdb_title 54,673, tmdb_movie 40,568, eidr 36,445, tmdb_tv 11,596, tvdb_series 11,093.

Omonimie: 28 coppie titolo+anno ripetute (opere diverse o duplicati da esaminare), 1,351 titoli usati da film di anni diversi.

## 4. Serie, stagioni, episodi

Importate: series 11,764, miniseries 1,901, season 14,176, episode 222,557; episodi con numero 198,366, con data 193,070; stagioni con numero 14,143.

## 5. Verifica a campione indipendente

400 film estratti a caso (seme 20261105); per ognuno si sono ricalcolati dal catalogo e dallo snapshot titolo, anno, durata, ID IMDb, ID Wikidata, registi e paesi, e confrontati con il database. **Differenze: 0.**

## 6. Cosa non è stato importato e perché (lacune per la fase 4)

| Motivo | Occorrenze |
|---|---|
| Crediti il cui nome non è nei file locali (solo il QID) | 144,630 |
| Società senza nome | 96,508 |
| Relazioni verso opere senza etichetta | 11,056 |
| Date di uscita con un luogo che non è un paese noto | 6,394 |
| Franchise senza nome | 5,129 |
| episode_air_date_not_parsed | 4,504 |
| genre_text_without_letters | 2,111 |
| Generi senza etichetta | 2,049 |
| series_not_imported | 2,032 |
| episode_row_duplicates_an_episode_page | 1,956 |
| episode_without_imported_series | 969 |
| Importi in valute diverse da USD (codice ISO non verificabile offline) | 962 |
| season_without_imported_series | 856 |
| episode_without_title | 472 |
| id_conflict | 240 |
| series_country_text_not_a_known_country | 151 |
| money_duplicate_same_key | 49 |
| Lingue senza etichetta | 27 |
| film_without_snapshot_entity | 23 |
| Paesi senza etichetta | 17 |
| release_year_differs_catalog_vs_wikidata | 1 |

Premi e candidature non importati (servono i nomi dei premi): **26,577** asserzioni. Persone importate: senza date di vita (0 con anno di nascita) né paese di nascita; paesi con codice ISO: 0 su 183 (i codici ISO non si deducono a memoria).

Stima delle richieste della fase 4 (da `SURVEY.md`, 50 id per richiesta; **stima**, nulla è stato richiesto): persone senza nome 983, premi e cerimonie 47, valute 1, bersagli di relazioni 121, società 86, franchise 17; tutto, comprese le date di vita di ogni persona: 3,119.

## 7. Interrogazioni reali attraverso il validatore e l'authorizer

| Domanda | Righe | ms | Esempio |
|---|---|---|---|
| film diretti da una persona (nome esatto) | 23 | 51.8 | [['Luci del varietà', 1950]] |
| film in cui recita una persona | 10 | 146.8 | [['Una pelliccia di visone', 1956, None]] |
| collaborazioni: film con regista A e attore B | 6 | 45.5 | [['La dolce vita', 1960]] |
| registi con più film nel catalogo | 10 | 203.0 | [['Mario Mattoli', 71]] |
| ricerca testuale di un titolo (FTS) | 10 | 5.6 | [[55913, 'Il padrino', None]] |
| ricerca per alias in inglese | 10 | 5.6 | [[140210, 'The Godfather', 'original']] |
| ricerca esatta per ID IMDb | 1 | 5.1 | [[365639, 'Il padrino', 1972]] |
| tratto da / basato su | 0 | 9.9 | [] |
| seguiti e precedenti in una serie di film | 2 | 26.3 | [['Il padrino - Parte II', 'follows', 'Il padrino']] |
| film di un franchise in ordine | 0 | 4.3 | [] |
| film per genere canonico e paese | 10 | 46.0 | [['Il mostro di Frankenstein', 1920]] |
| film più lunghi | 5 | 47.5 | [['Come Yukong spostò le montagne', 1976, 763]] |
| episodi di una stagione | 8 | 225.8 | [['Questione di chimica (Breaking Bad)', None, None]] |
| conteggio film per decennio | 14 | 189.9 | [[1890, 3]] |
| incassi dichiarati (USD) | 5 | 9.9 | [['Avatar', 2847379794, 'worldwide']] |
| termini d'uso delle fonti | 5 | 4.0 | [['wikidata-film-snapshot', 'CC0 1.0', 'open_public_domain', 0]] |
