# Rapporto della build con la fase 4 (verifica indipendente)

> Generato da `verify --reproduce --report-name PHASE4_BUILD_REPORT` sul database della fase 4. Il testo e la sezione 6 («lacune per la fase 4») sono quelli del modello della fase 3: per cosa la fase 4 ha aggiunto, importato e lasciato fuori vale `PHASE4_REPORT.md`; le colonne «Cosa non è stato importato» qui sotto sono ricalcolate sul nuovo file.

Generato da `python -m cinema_db.harness.build.verify` sul file reale, in sola lettura. Nessuna rete, nessun credito. Le fonti sono quelle locali (snapshot Wikidata di film e serie, catalogo film v3, catalogo serie s5), non modificate.

## 1. Integrità

- File: **405 MB**; build in 401.1 s.
- `foreign_key_check`: 0 righe; `integrity_check`: ok; indice FTS5: coerente; regole (un solo nome primario per entità): rispettate; trigger: 0.
- Digest del contenuto ricalcolato = memorizzato: **True** (`b3b0de5122e82432…`). La policy delle viste approvate accetta il file: **True**.
- Riproducibilità: una seconda build completa (448.3 s) dà lo stesso digest: **True**.

## 2. Righe per tabella

| Tabella | Righe |
|---|---|
| award | 1,060 |
| award_category | 1,785 |
| award_result | 27,751 |
| build_info | 7 |
| ceremony | 5,506 |
| company | 6,715 |
| country | 229 |
| credit | 675,327 |
| entity | 452,351 |
| entity_name | 804,772 |
| entity_name_fts | 804,772 |
| external_id | 435,347 |
| field_provenance | 158,067 |
| franchise | 1,071 |
| genre | 38 |
| genre_label | 1,069 |
| genre_label_map | 688 |
| id_scheme | 11 |
| language | 270 |
| person | 141,645 |
| relation_type | 4 |
| role_type | 16 |
| source | 6 |
| work | 301,860 |
| work_company | 103,155 |
| work_country | 67,496 |
| work_financial | 10,162 |
| work_franchise | 5,107 |
| work_genre | 123,995 |
| work_kind | 12 |
| work_language | 49,785 |
| work_relation | 15,311 |
| work_release | 51,028 |

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
| with_director | 38,810 | 96.5 |
| with_cast | 32,948 | 81.9 |
| with_genre_label | 38,051 | 94.6 |
| with_canonical_genre | 37,833 | 94.0 |
| with_country | 40,047 | 99.6 |
| with_language | 32,573 | 81.0 |
| with_company | 28,733 | 71.4 |
| with_franchise | 3,442 | 8.6 |
| with_relation | 7,543 | 18.8 |
| with_release_by_country | 14,050 | 34.9 |
| with_money | 5,641 | 14.0 |

Generi: 1,069 etichette originali, 563 mappate; asserzioni etichetta→opera mappate **92.1%** (114,162 su 123,995). Le etichette non mappate restano leggibili in `v_work_genre_label`.

Tipi di opera: episode 222,557, film 36,529, season 14,176, series 11,764, other 8,689, short 3,427, tv_film 2,817, miniseries 1,901.

Crediti: cast 441,298, director 52,097, writer 51,217, producer 37,061, composer 31,842, cinematographer 25,440, editor 19,086, production_designer 7,533, creator 4,962, costume_designer 4,791.

Relazioni: based_on 10,513, follows 4,798.

Nomi: primary 452,351, original 239,905, alias 56,711, translated 55,805.

Identificativi: wikidata 213,760, wikipedia_it 67,212, imdb_title 54,673, tmdb_movie 40,568, eidr 36,445, tmdb_tv 11,596, tvdb_series 11,093.

Omonimie: 28 coppie titolo+anno ripetute (opere diverse o duplicati da esaminare), 1,351 titoli usati da film di anni diversi.

## 4. Serie, stagioni, episodi

Importate: series 11,764, miniseries 1,901, season 14,176, episode 222,557; episodi con numero 198,366, con data 193,070; stagioni con numero 14,143.

## 5. Verifica a campione indipendente

400 film estratti a caso (seme 20261105); per ognuno si sono ricalcolati dal catalogo e dallo snapshot titolo, anno, durata, ID IMDb, ID Wikidata, registi e paesi, e confrontati con il database. **Differenze: 0.**

## 6. Cosa non è stato importato e perché (lacune per la fase 4)

| Motivo | Occorrenze |
|---|---|
| Date di uscita con un luogo che non è un paese noto | 6,106 |
| episode_air_date_not_parsed | 4,504 |
| person_birth_date_ambiguous | 3,184 |
| genre_text_without_letters | 2,111 |
| Generi senza etichetta | 2,049 |
| series_not_imported | 2,032 |
| episode_row_duplicates_an_episode_page | 1,956 |
| award_without_ceremony_or_year | 1,681 |
| person_death_date_ambiguous | 1,589 |
| episode_without_imported_series | 969 |
| season_without_imported_series | 856 |
| episode_without_title | 472 |
| credit_holder_is_an_organisation | 327 |
| company_assertion_for_a_human_not_imported | 277 |
| Relazioni verso opere senza etichetta | 268 |
| id_conflict | 244 |
| award_item_not_available | 178 |
| Crediti il cui nome non è nei file locali (solo il QID) | 154 |
| series_country_text_not_a_known_country | 151 |
| award_nominee_without_name | 115 |
| Società senza nome | 114 |
| company_country_ambiguous | 81 |
| money_duplicate_same_key | 50 |
| Franchise senza nome | 38 |
| ceremony_item_without_year | 25 |
| film_without_snapshot_entity | 23 |
| Importi in valute diverse da USD (codice ISO non verificabile offline) | 11 |
| person_birth_year_out_of_range | 8 |
| person_death_year_out_of_range | 6 |
| award_categories_with_the_same_name_in_one_award | 2 |
| country_iso2_ambiguous_or_repeated | 2 |
| ceremony_items_with_the_same_award_year_and_label | 1 |
| release_year_differs_catalog_vs_wikidata | 1 |

Premi e candidature non importati (servono i nomi dei premi): **0** asserzioni. Persone importate: senza date di vita (113171 con anno di nascita) né paese di nascita; paesi con codice ISO: 179 su 229 (i codici ISO non si deducono a memoria).

Stima delle richieste della fase 4 (da `SURVEY.md`, 50 id per richiesta; **stima**, nulla è stato richiesto): persone senza nome 983, premi e cerimonie 47, valute 1, bersagli di relazioni 121, società 86, franchise 17; tutto, comprese le date di vita di ogni persona: 3,119.

## 7. Interrogazioni reali attraverso il validatore e l'authorizer

| Domanda | Righe | ms | Esempio |
|---|---|---|---|
| film diretti da una persona (nome esatto) | 23 | 71.7 | [['Luci del varietà', 1950]] |
| film in cui recita una persona | 10 | 212.1 | [['Una pelliccia di visone', 1956, None]] |
| collaborazioni: film con regista A e attore B | 6 | 72.1 | [['La dolce vita', 1960]] |
| registi con più film nel catalogo | 10 | 280.1 | [['Mario Mattoli', 71]] |
| ricerca testuale di un titolo (FTS) | 10 | 7.2 | [[81017, 'Il padrino', None]] |
| ricerca per alias in inglese | 10 | 7.4 | [[165314, 'The Godfather', 'original']] |
| ricerca esatta per ID IMDb | 1 | 6.5 | [[415700, 'Il padrino', 1972]] |
| tratto da / basato su | 2 | 32.7 | [['Il nome della rosa', 'Il nome della rosa', 'other']] |
| seguiti e precedenti in una serie di film | 2 | 42.2 | [['Il padrino - Parte II', 'follows', 'Il padrino']] |
| film di un franchise in ordine | 9 | 8.6 | [['Guerre stellari', 1977]] |
| film per genere canonico e paese | 10 | 60.3 | [['Il mostro di Frankenstein', 1920]] |
| film più lunghi | 5 | 65.7 | [['Come Yukong spostò le montagne', 1976, 763]] |
| episodi di una stagione | 8 | 307.0 | [['Questione di chimica (Breaking Bad)', None, None]] |
| conteggio film per decennio | 14 | 250.9 | [[1890, 3]] |
| incassi dichiarati (USD) | 5 | 20.5 | [['Avatar', 2847379794, 'worldwide']] |
| termini d'uso delle fonti | 6 | 5.0 | [['wikidata-film-snapshot', 'CC0 1.0', 'open_public_domain', 0]] |
