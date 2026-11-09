# Fase 9 — Riconciliazione: classificazione dei duplicati e degli identificativi condivisi

**Nessuna entità è stata modificata e nessuna fusione eseguita.** Questa è una classificazione con prove e una proposta. Dati: `cinema_db/data/audit_a1/reconciliation/*.jsonl` (per ogni caso: entità, identificativi, prove, classe, rischio di fusione errata, azione proposta).

## 430 ID IMDb di persona reclamati da più persone di cinema

| classe | casi |
|---|---|
| duplicate_possible_shared_work_other_role | 9 |
| duplicate_probable_same_person_two_entities | 29 |
| homonym_or_split_no_proof | 166 |
| id_belongs_to_one_person_birth_year_decides | 205 |
| id_probably_wrong_for_all_birth_year_contradicts | 21 |

Rischio di fusione errata: high 392, medium 38.
- Esempio `homonym_or_split_no_proof`: `{"entities": [{"birth": 1966, "credits": 31, "name": "John Frizzell", "person_id": 7156, "qid": "Q331664"}, {"birth": null, "credits": 7, "name": "John Frizzell", "person_id": 311246, "qid": "Q16243972"}], "evidence": {"birth_contradicts_imdb": [], "birth_matches_imdb": [], "same_work": false, "same_work_and_role": false}, "imdb_birth": null, "nconst": "nm0002227"}` → keep both; attach to none.
- Esempio `id_belongs_to_one_person_birth_year_decides`: `{"entities": [{"birth": 1961, "credits": 1, "name": "David Price", "person_id": 340404, "qid": "Q113488816"}, {"birth": 1985, "credits": 1, "name": "David Price", "person_id": 340405, "qid": "Q332804"}], "evidence": {"birth_contradicts_imdb": [340405], "birth_matches_imdb": [340404], "same_work": true, "same_work_and_role": false}, "imdb_birth": 1961, "nconst": "nm0002606"}` → attach nm0002606 to person 340404 only; the others stay without this id (homonyms or wrongly matched).
- Esempio `duplicate_probable_same_person_two_entities`: `{"entities": [{"birth": 1977, "credits": 2, "name": "Miranda Bailey", "person_id": 372278, "qid": "Q11781641"}, {"birth": null, "credits": 1, "name": "Miranda Bailey", "person_id": 372279, "qid": "Q2400233"}], "evidence": {"birth_contradicts_imdb": [], "birth_matches_imdb": [372278], "same_work": true, "same_work_and_role": true}, "imdb_birth": 1977, "nconst": "nm0047419"}` → merge candidate (new build, canonical map); attach the id to the survivor.
- Esempio `duplicate_possible_shared_work_other_role`: `{"entities": [{"birth": 1945, "credits": 2, "name": "Michael Berg", "person_id": 356105, "qid": "Q6828594"}, {"birth": null, "credits": 3, "name": "Michael Berg", "person_id": 365027, "qid": "Q28857154"}], "evidence": {"birth_contradicts_imdb": [], "birth_matches_imdb": [], "same_work": true, "same_work_and_role": false}, "imdb_birth": null, "nconst": "nm0073850"}` → keep both; attach to none until a second proof.
- Esempio `id_probably_wrong_for_all_birth_year_contradicts`: `{"entities": [{"birth": null, "credits": 4, "name": "Juan Bosch (regista)", "person_id": 350656, "qid": "Q1710380"}, {"birth": 1909, "credits": 1, "name": "Juan Bosch", "person_id": 367598, "qid": "Q439980"}], "evidence": {"birth_contradicts_imdb": [367598], "birth_matches_imdb": [], "same_work": true, "same_work_and_role": true}, "imdb_birth": 1925, "nconst": "nm0090625"}` → attach to none; keep as candidate.

## 58 opere con due ID IMDb

| classe | casi |
|---|---|
| different_titles_possible_conflation_of_two_works | 25 |
| imdb_has_two_entries_same_title_year_type | 3 |
| same_title_different_year_or_type | 16 |
| stale_id_one_unknown_to_imdb | 14 |

Rischio di fusione errata: high 25, low 14, medium 19.
- Esempio `same_title_different_year_or_type`: `{"details": [{"imdb": "tt0121220", "in_movielens": false, "known_to_imdb": true, "movielens_votes": null, "runtime": 24, "title": "Dragon Ball Z", "type": "tvSeries", "votes": 106222, "year": 1989}, {"imdb": "tt0214341", "in_movielens": false, "known_to_imdb": true, "movielens_votes": null, "runtime": 24, "title": "Dragon Ball Z", "type": "tvSeries", "votes": 182764, "year": 1996}], "evidence": {"all_ids_on_the_same_` → check whether the work conflates two releases; keep both ids, no split without proof.
- Esempio `different_titles_possible_conflation_of_two_works`: `{"details": [{"imdb": "tt26545971", "in_movielens": false, "known_to_imdb": true, "movielens_votes": null, "runtime": 50, "title": "Accidentally Famous", "type": "tvMiniSeries", "votes": 1797, "year": 2024}, {"imdb": "tt42026819", "in_movielens": false, "known_to_imdb": true, "movielens_votes": null, "runtime": null, "title": "Nord Sud Ovest Est: La leggendaria storia degli 883", "type": "tvMiniSeries", "votes": 119,` → do not merge anything; candidate for a SPLIT of the work (new build).
- Esempio `imdb_has_two_entries_same_title_year_type`: `{"details": [{"imdb": "tt0465834", "in_movielens": false, "known_to_imdb": true, "movielens_votes": null, "runtime": 30, "title": "Littl' Bits", "type": "tvSeries", "votes": 93, "year": 1980}, {"imdb": "tt0179584", "in_movielens": false, "known_to_imdb": true, "movielens_votes": null, "runtime": null, "title": "The Littl' Bits", "type": "tvSeries", "votes": 626, "year": 1980}], "evidence": {"all_ids_on_the_same_wikid` → keep both ids on the work (primary = the one with more votes); do not create a second work.
- Esempio `stale_id_one_unknown_to_imdb`: `{"details": [{"imdb": "tt21153032", "in_movielens": false, "known_to_imdb": false, "movielens_votes": null, "runtime": null, "title": null, "type": null, "votes": null, "year": null}, {"imdb": "tt0074053", "in_movielens": false, "known_to_imdb": true, "movielens_votes": null, "runtime": 24, "title": "The Scooby-Doo Show", "type": "tvSeries", "votes": 4873, "year": 1976}], "evidence": {"all_ids_on_the_same_wikidata_it` → keep the id IMDb knows as primary; keep the other as non-primary historical id.

## 256 coppie di persone (stesso nome, stesso ruolo nella stessa opera)

| classe | casi |
|---|---|
| duplicate_confirmed_by_imdb_same_person_id | 125 |
| duplicate_probable_same_name_same_role_same_work | 34 |
| homonym_birth_years_differ | 91 |
| homonym_distinct_imdb_people | 6 |

Rischio di fusione errata: high 97, low 125, medium 34.
- Esempio `duplicate_confirmed_by_imdb_same_person_id`: `{"birth_years": [1978, 1979], "imdb_ids": [["nm1378320"], ["nm1378320"]], "imdb_tiers": ["strong", "conflict_birth_year"], "persons": [26527, 324404], "qids": ["Q4661797", "Q2820018"]}` → merge candidate in a new build; survivor = the entity with a birth year, else more credits.
- Esempio `homonym_birth_years_differ`: `{"birth_years": [1958, 1966], "imdb_ids": [null, null], "imdb_tiers": [null, null], "persons": [366129, 366131], "qids": ["Q6712373", "Q4690880"]}` → do NOT merge.
- Esempio `duplicate_probable_same_name_same_role_same_work`: `{"birth_years": [null, 1922], "imdb_ids": [null, null], "imdb_tiers": [null, null], "persons": [40806, 329770], "qids": ["Q526529", "Q172574"]}` → merge candidate after a second proof (a shared id or a birth year).
- Esempio `homonym_distinct_imdb_people`: `{"birth_years": [1929, 1946], "imdb_ids": [["nm0904562"], ["nm0904563"]], "imdb_tiers": ["strong", "strong"], "persons": [414275, 418428], "qids": ["Q12022022", "Q1675630"]}` → do NOT merge: IMDb knows two different people.

## Proposta di riconciliazione (da approvare, non applicata)
1. **Identificativi condivisi**: dove l'anno di nascita decide (`id_belongs_to_one_person_birth_year_decides`) l'ID va alla sola persona coerente; le altre restano senza ID e con il candidato registrato. Dove non c'è prova (`homonym_or_split_no_proof`) nessuno riceve l'ID.
2. **Persone doppie**: le coppie `duplicate_confirmed_by_imdb_same_person_id` (stessa persona IMDb per entrambe) sono candidate alla fusione in una **build nuova**, con una mappa `canonical_entity_id`, conservando entrambi i QID come identificativi e il nome dell'entità superstite; sopravvive l'entità con anno di nascita o con più crediti. Le `homonym_*` non si toccano mai.
3. **Opere con due ID IMDb**: `stale_id_one_unknown_to_imdb` → l'ID noto a IMDb diventa primario, l'altro resta non primario; `imdb_has_two_entries_same_title_year_type` → entrambi gli ID sulla stessa opera; `different_titles_possible_conflation_of_two_works` → **nessuna fusione**, candidate a *scissione* dell'opera in una build nuova (l'elemento Wikidata ne unisce due).
4. Prima e dopo ogni build di riconciliazione: `foreign_key_check`, conteggio di crediti, relazioni e ID per entità prima/dopo, 100 interrogazioni campione identiche; il file attuale resta come `.previous`.

## Decisioni e questioni aperte (checkpoint del 2026-11-08)
**Approvato dal proprietario**: nessuna fusione automatica; classificare i casi con entità, identificativi, prove, classe proposta e rischio; preparare una proposta; eseguire le fusioni **solo** in una build nuova con controlli FK e verifica delle relazioni prima/dopo. Nessuna regola di fusione è stata approvata.
**Non ancora deciso (proposte di questo documento)**: tutte le azioni della tabella «Proposta di riconciliazione». Nel v3 prototipo NON sono stati attaccati ID di persona condivisi tra più entità (restano candidati `shared_by_several_entities`), nessuna persona è stata fusa, nessuna opera con due ID IMDb è stata modificata né scissa, e nessuna entità è stata cancellata.
**Fatto nel v3 senza essere una fusione**: 25 ID IMDb di MovieLens attaccati come alias non primari a un'opera esistente perché MovieLens e il catalogo danno lo stesso ID TMDb (identificazione certa da ID locali); 237 ID recuperati per record con `ids_reliable=false` confermati da IMDb.
**Questioni aperte**: (1) approvare le classi `duplicate_confirmed_by_imdb_same_person_id` (125 coppie) come candidate alla fusione in una build di riconciliazione; (2) decidere come trattare le 25 opere con due ID IMDb di titoli diversi (scissione?); (3) decidere se attribuire l'ID alla persona coerente per anno di nascita nelle 205 `id_belongs_to_one_person_birth_year_decides`; (4) stabilire il sopravvissuto e la mappa `canonical_entity_id` (non esiste ancora nello schema); (5) i 1.656 titoli trattenuti (26 con lo stesso regista, di cui 6 su opere senza ID IMDb) sono un secondo insieme di candidati, in `cinema.v3.separate/not_entered.jsonl`.


## Esito dell'applicazione (2026-11-08, seconda tornata) — vedi `PHASE9_RECONCILED_REPORT.md`
Le proposte sono state approvate con modifiche e applicate in una build nuova (`cinema.v3.reconciled.sqlite3`): **12** fusioni di persone (non 18: `merge_check` esclude chi ha una morte che IMDb non conferma o nascite diverse; Aaron Abrams e Jana Nováková restano distinti) come mappa reversibile `entity_canonical`; **204** ID attaccati per anno di nascita; doppi ID: primario per regola (noto a IMDb, titolo, voti, ordine lessicografico), alias in `entity_claim`; **1.133** titoli trattenuti rilasciati (523 restano, 457 per un difetto dei nomi non latini). Nessuna scissione di opere è stata fatta (le 25 opere «possibile fusione di due opere» restano con i due ID, il secondario come alias e claim).

## Aggiornamento (2026-11-08, sera)
Titoli trattenuti: dei 522 identificativi distinti (523 voci) ne sono stati recuperati **456** dopo la correzione Unicode (450 senza alcun candidato reale, 4 con la regola B, 2 con la A); **66** restano con un candidato reale. Le 11.524 persone create per candidati deboli restano distinte: rapporto in `PHASE9_RECONCILED_REPORT.md`.

## Aggiornamento (2026-11-09)
Opere collegate a MovieLens con pagina debole: 642 su 705 tornano `verified`; vedi `PHASE9_F_REPORT.md` §2. Titoli trattenuti (66), fusioni (12) e persone (11.524 create, nessuna fusione) invariati.
