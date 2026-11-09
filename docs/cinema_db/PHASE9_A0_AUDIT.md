# Fase 9 — A0: audit locale in sola lettura (rapporto)

Generato da `python -m cinema_db.harness.audit.run_audit report` a partire da `cinema_db/data/audit_a0/results.json` (copia in `docs/cinema_db/PHASE9_A0_RESULTS.json`). **Tutti i numeri sono misurati sui file locali** salvo dove la riga dice esplicitamente *ipotesi* o *stima*. Nessuna rete, nessuna scrittura sugli archivi, nessuna fusione.

## 1. Archivi e sovrapposizioni
- `cinema.sqlite3`: 301.718 opere, 141.646 persone, 675.327 crediti, 435.348 identificativi, 26.136 risultati di premio, 15.311 relazioni; digest `c888ebd0f6cf953f…`.
- MovieLens: 87.585 film, 87.585 link, 84.432 con statistiche, 32.000.204 voti, 2.000.066 tag.
- RAG v3: 41.138 film; estrazione dal dump: 41.421 accettate, 41.627 scartate (pagine con infobox film), 284 escluse in pulizia; serie s5: seasons 15.032, series 15.697, tv_movies 2.578, uncertain 303, puntate 78.705.
- Snapshot Wikidata: film 41.395 entità (1.676 richieste), serie 32.412 entità.

### 1.1 Insiemi di identificativi IMDb (opere) e confronto con `cinema_db`

| archivio | ID IMDb | non in cinema | % non in cinema | solo in questo archivio |
|---|---|---|---|---|
| cinema | 54.673 | — | — | 1 |
| movielens | 87.585 | 61.474 | 70.19 | 61.386 |
| rag_v3 | 40.799 | 0 | 0.0 | 0 |
| s5_series | 12.887 | 722 | 5.6 | 0 |
| s5_tv_movies | 2.470 | 14 | 0.57 | 0 |
| s5_uncertain | 107 | 105 | 98.13 | 0 |
| wikidata_film_snapshot | 40.966 | 37 | 0.09 | 9 |
| wikidata_series_snapshot | 15.628 | 903 | 5.78 | 59 |

### 1.2 Insiemi di QID Wikidata

| archivio | QID | non in cinema | solo in questo archivio |
|---|---|---|---|
| cinema | 64.342 | — | 8.378 |
| rag_v3 | 41.115 | 5 | 0 |
| s5_series | 15.675 | 2.561 | 0 |
| s5_tv_movies | 2.573 | 17 | 0 |
| s5_uncertain | 302 | 297 | 0 |
| wikidata_film_snapshot | 41.395 | 175 | 89 |
| wikidata_series_snapshot | 32.412 | 16.630 | 13.754 |

Nota: gli insiemi di serie includono stagioni e puntate che `cinema_db` rappresenta come opere figlie senza proprio QID; la differenza per le serie non va letta come perdita (da verificare per classe in B).

RAG v3 per tipo in `cinema_db` (per QID): film 36.502, short 3.427, tv_film 1.096, miniseries 35, other 32, absent 28, series 18.

## 2. Lacune ordinate per rilevanza
La rilevanza è misurata, non fissata: per ogni soglia di numero di voti MovieLens si riporta quanti film mancano. **Nessuna soglia è proposta qui.**

**Lacune in ordine di impatto sull'agente** (l'ordine è un giudizio, *ipotesi*; i numeri sono misurati):
1. Valutazioni: nessuna in cinema (0 %); 25.626 opere hanno statistiche MovieLens subito disponibili, il resto richiede fonti esterne.
2. Film noti assenti: 4.058 film con ≥50 voti MovieLens (25.31 % di quelli con almeno 50 voti), tra cui i più votati (§3); cause in §3.
3. Cast: nessun ordine (0 %); personaggio solo nel 12.95 % dei film (27.15 % tra quelli con ≥50 voti ML).
4. Persone: nessun ID IMDb/TMDb (141.646 persone), paese di nascita assente.
5. Uscite: 51.028 date per paese, nessuna con tipo (0 % `release_with_type`).
6. Premi: presenti per il 15.23 % dei film (32.14 % tra quelli con ≥50 voti ML); il nominato spesso non è registrato (limite noto).
7. Serie: regia solo per il 27.48 % delle serie; durata quasi assente (0.09 %).
8. Perdite tra sorgente e build: 88 film presenti in sorgenti locali ma non in cinema (§7).


| voti MovieLens ≥ | film ML | mancanti | % mancanti | voti dei mancanti | % voti totali |
|---|---|---|---|---|---|
| 1 | 84.432 | 58.806 | 69.65 | 1.767.073 | 5.52 |
| 5 | 43.884 | 23.446 | 53.43 | 1.699.391 | 5.32 |
| 10 | 31.961 | 14.284 | 44.69 | 1.639.145 | 5.15 |
| 20 | 23.350 | 8.299 | 35.54 | 1.558.937 | 4.91 |
| 50 | 16.034 | 4.058 | 25.31 | 1.429.404 | 4.54 |
| 100 | 12.191 | 2.313 | 18.97 | 1.308.736 | 4.19 |
| 500 | 6.226 | 543 | 8.72 | 930.844 | 3.12 |
| 1.000 | 4.397 | 248 | 5.64 | 727.254 | 2.55 |
| 5.000 | 1.489 | 27 | 1.81 | 299.380 | 1.36 |
| 10.000 | 772 | 8 | 1.04 | 172.041 | 1.02 |

MovieLens senza link IMDb: 0; senza statistiche: 3.153.

Lacune per campo (film): copertura su tutti i film e sui film con ≥50 voti MovieLens (i più rilevanti misurabili). Unità: film con almeno un dato, non righe (il «personaggio» è quindi diverso dal 12,6 % dei *crediti* citato altrove).

| campo | tutti i film | film con ≥50 voti ML |
|---|---|---|
| rating_any_source | 0.0 % | 0.0 % |
| cast_with_billing_order | 0.0 % | 0.0 % |
| cast_with_character | 12.95 % | 27.15 % |
| release_with_type | 0.0 % | 0.0 % |
| award_result | 15.23 % | 32.14 % |
| company | 71.39 % | 97.27 % |
| franchise | 6.8 % | 14.51 % |
| financial | 15.37 % | 38.45 % |
| relation | 23.09 % | 43.74 % |
| original_title | 94.22 % | 99.82 % |
| runtime | 94.98 % | 99.72 % |
| writer | 76.89 % | 91.49 % |
| cinematographer | 60.93 % | 82.1 % |
| composer | 65.59 % | 89.74 % |
| language | 84.93 % | 99.75 % |
| cast | 86.12 % | 93.85 % |
| director | 97.34 % | 99.91 % |
| genre | 96.63 % | 99.89 % |
| country | 99.55 % | 100.0 % |
| imdb_id | 99.31 % | 100.0 % |
| tmdb_id | 96.66 % | 99.98 % |
| release_year | 99.95 % | 100.0 % |

Film totali 36.529; film con ≥50 voti ML presenti in cinema 11.593.

Per decennio (film):

| decennio | film | regia % | cast % | personaggio % | generi % | durata % | premi % | società % | IMDb % |
|---|---|---|---|---|---|---|---|---|---|
| 1890s | 3 | 100.0 | 33.33 | 33.33 | 100.0 | 100.0 | 0.0 | 33.33 | 100.0 |
| 1900s | 52 | 88.46 | 21.15 | 1.92 | 94.23 | 65.38 | 0.0 | 28.85 | 100.0 |
| 1910s | 2.227 | 97.26 | 76.83 | 1.57 | 98.38 | 57.52 | 0.0 | 64.39 | 99.42 |
| 1920s | 1.975 | 99.04 | 88.3 | 3.49 | 98.73 | 85.92 | 1.82 | 69.87 | 99.95 |
| 1930s | 1.347 | 97.92 | 91.39 | 7.8 | 95.99 | 94.73 | 13.81 | 76.02 | 99.7 |
| 1940s | 1.502 | 99.0 | 94.14 | 8.72 | 97.67 | 96.54 | 20.57 | 79.03 | 99.33 |
| 1950s | 2.607 | 99.23 | 94.86 | 8.29 | 97.05 | 98.85 | 13.31 | 71.19 | 99.39 |
| 1960s | 2.573 | 99.38 | 94.48 | 12.09 | 97.94 | 99.14 | 13.18 | 62.42 | 99.77 |
| 1970s | 2.999 | 98.8 | 93.06 | 11.4 | 97.93 | 98.97 | 11.67 | 54.45 | 99.87 |
| 1980s | 2.818 | 98.83 | 91.02 | 14.62 | 97.87 | 98.55 | 20.62 | 68.91 | 99.33 |
| 1990s | 3.428 | 98.86 | 90.64 | 19.25 | 97.67 | 99.12 | 21.38 | 77.28 | 99.56 |
| 2000s | 5.511 | 98.35 | 86.86 | 13.92 | 98.0 | 99.13 | 19.25 | 81.75 | 99.15 |
| 2010s | 6.557 | 95.32 | 77.9 | 15.82 | 96.57 | 97.7 | 18.24 | 75.86 | 98.96 |
| 2020s | 2.911 | 90.31 | 71.52 | 22.09 | 86.47 | 96.74 | 14.6 | 64.27 | 98.49 |
| unknown | 19 | 5.26 | 5.26 | 0.0 | 10.53 | 0.0 | 0.0 | 10.53 | 73.68 |

Copertura per tipo di opera (percentuale di opere con il dato):

| tipo | opere | director | cast | cast_with_character | genre | runtime | release_year | imdb_id | tmdb_id | award_result | company |
|---|---|---|---|---|---|---|---|---|---|---|---|
| film | 36.529 | 97.34 | 86.12 | 12.95 | 96.63 | 94.98 | 99.95 | 99.31 | 96.66 | 15.23 | 71.39 |
| short | 3.427 | 88.27 | 38.17 | 0.99 | 73.65 | 63.67 | 99.94 | 99.45 | 69.97 | 4.64 | 72.02 |
| tv_film | 2.817 | 89.81 | 68.58 | 4.44 | 98.76 | 28.9 | 99.79 | 95.39 | 90.49 | 1.7 | 70.75 |
| series | 11.764 | 27.48 | 52.25 | 4.29 | 96.12 | 0.09 | 92.78 | 89.73 | 86.94 | 2.77 | 91.63 |
| miniseries | 1.901 | 67.12 | 49.76 | 7.47 | 99.16 | 1.05 | 100.0 | 84.06 | 68.86 | 1.89 | 91.9 |
| season | 14.176 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| episode | 222.415 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 86.81 | 0.03 | 0.0 | 0.0 | 0.0 |
| other | 8.689 | 0.1 | 0.03 | 0.01 | 0.23 | 0.21 | 0.33 | 0.12 | 0.1 | 0.02 | 0.07 |

Persone: 141.646; anno di nascita 113.171 (79.9 %), anno di morte 40.550, paese di nascita 0. Cast medio per opera con cast: 10.56 (max 579). Valutazioni di qualunque fonte in `cinema_db`: 0 (non esiste una tabella).

## 3. I film MovieLens mancanti
- Mancanti in totale (con link IMDb, qualunque numero di voti): **61.474**; con ≥50 voti: **4.058** (voti totali 1.429.404); con ID TMDb in MovieLens: 4.045.
- Scansione del dump eseguita: **sì**.

Cause (euristica a cascata: stesso TMDb in cinema → presente in altra fonte locale → stesso titolo/anno in cinema → pagina nel dump → nessuna traccia):

| causa | tutti i mancanti | ≥50 voti |
|---|---|---|
| no_itwiki_page_with_that_title | 41.430 | 1.568 |
| itwiki_film_page_rejected:plot_too_short | 7.249 | 1.629 |
| itwiki_page_without_film_infobox | 5.332 | 260 |
| itwiki_title_only_candidate_year_not_confirmed | 4.779 | 215 |
| itwiki_redirect_to_other_page | 1.096 | 70 |
| itwiki_film_page_rejected:no_plot_section | 835 | 253 |
| probable_same_work_under_other_ids | 613 | 33 |
| in_local_source_but_not_in_cinema | 88 | 9 |
| present_in_cinema_with_another_imdb_id | 34 | 14 |
| itwiki_film_page_in_extraction_but_not_in_cinema | 17 | 7 |
| itwiki_film_page_not_in_extraction_lists | 1 | 0 |

Per decennio (≥50 voti): 1910s 2, 1920s 10, 1930s 28, 1940s 58, 1950s 47, 1960s 123, 1970s 181, 1980s 410, 1990s 862, 2000s 1.048, 2010s 1.127, 2020s 155, unknown 7.
Generi principali (≥50 voti): Action 423, Adventure 210, Comedy 1.547, Crime 372, Documentary 669, Drama 1.619, Horror 323, Romance 486, Sci-Fi 257, Thriller 470.

I 25 più votati tra i mancanti:

| titolo | voti | causa |
|---|---|---|
| Fight Club (1999) | 77.332 | itwiki_film_page_rejected:no_plot_section |
| This Is Spinal Tap (1984) | 19.492 | itwiki_film_page_rejected:plot_too_short |
| Christmas Story, A (1983) | 15.016 | itwiki_film_page_rejected:plot_too_short |
| Best in Show (2000) | 12.835 | itwiki_film_page_rejected:plot_too_short |
| So I Married an Axe Murderer (1993) | 12.764 | itwiki_film_page_rejected:plot_too_short |
| Planet of the Apes (2001) | 12.420 | itwiki_film_page_rejected:no_plot_section |
| Searching for Bobby Fischer (1993) | 11.176 | itwiki_film_page_rejected:plot_too_short |
| Caddyshack (1980) | 11.006 | itwiki_film_page_rejected:plot_too_short |
| Brady Bunch Movie, The (1995) | 9.903 | itwiki_film_page_rejected:plot_too_short |
| West Side Story (1961) | 9.813 | itwiki_film_page_rejected:no_plot_section |
| Wallace & Gromit: The Best of Aardman Animation (1996) | 8.612 | no_itwiki_page_with_that_title |
| Jerk, The (1979) | 7.981 | itwiki_film_page_rejected:plot_too_short |
| Waterboy, The (1998) | 7.923 | itwiki_film_page_rejected:plot_too_short |
| Grindhouse (2007) | 6.739 | itwiki_film_page_rejected:no_plot_section |
| Mystery Science Theater 3000: The Movie (1996) | 6.524 | itwiki_film_page_rejected:plot_too_short |
| Spy Hard (1996) | 6.511 | itwiki_film_page_rejected:plot_too_short |
| Waiting for Guffman (1996) | 6.433 | itwiki_film_page_rejected:no_plot_section |
| Crumb (1994) | 6.363 | itwiki_film_page_rejected:no_plot_section |
| Hamlet (1996) | 6.151 | itwiki_film_page_rejected:plot_too_short |
| Wayne's World 2 (1993) | 6.066 | itwiki_film_page_rejected:plot_too_short |
| Circle of Friends (1995) | 5.936 | itwiki_film_page_rejected:no_plot_section |
| My Left Foot (1989) | 5.936 | itwiki_film_page_rejected:plot_too_short |
| Milk Money (1994) | 5.487 | itwiki_film_page_rejected:plot_too_short |
| Black Sheep (1996) | 5.419 | itwiki_film_page_rejected:plot_too_short |
| Amistad (1997) | 5.255 | itwiki_film_page_rejected:no_plot_section |

### 3.1 Il dump Wikipedia: pagine-film scartate dall'estrazione
- Pagine con infobox film trovate nel dump: 80.469 (accettate nell'estrazione 39.852, scartate 40.612, né l'una né l'altra 5).
- Motivi di scarto: no_plot_section 2.785, plot_too_short 37.827.
- Tra gli scartati: anno nota 40.595; con corrispondenza in cinema per titolo+anno ±1: 626; **senza** opera corrispondente in cinema: 39.986.
- Scartati per decennio: 1880s 5, 1890s 149, 1900s 1.840, 1910s 14.480, 1920s 1.998, 1930s 1.828, 1940s 1.678, 1950s 2.309, 1960s 2.356, 1970s 2.203, 1980s 1.963, 1990s 2.081, 2000s 2.824, 2010s 3.148, 2020s 1.733, unknown 17.
- Scartati per motivo e presenza di un'intestazione di trama riconosciuta dalla scansione: no_plot_section:False 2.738, no_plot_section:True 47, plot_too_short:True 37.827.

## 4. Identificativi e possibilità di riconciliazione

| schema | tipo entità | righe | entità |
|---|---|---|---|
| wikidata | person | 141.634 | 141.634 |
| wikipedia_it | work | 67.212 | 67.212 |
| wikidata | work | 64.342 | 64.342 |
| imdb_title | work | 54.673 | 54.612 |
| tmdb_movie | work | 40.568 | 40.547 |
| eidr | work | 36.445 | 36.333 |
| tmdb_tv | work | 11.596 | 11.589 |
| tvdb_series | work | 11.093 | 11.089 |
| wikidata | company | 5.706 | 5.706 |
| wikidata | award | 1.059 | 1.059 |
| wikidata | franchise | 1.020 | 1.020 |

- Persone con un identificativo diverso da Wikidata in cinema: **0** su 141.646.
- Risposte di fase 4 (Wikidata mirato) contengono per le persone solo: {'birth': 131193, 'death': 46478, 'label': 293518}.
- RAG v3: 358.210 righe di attori, 326.165 con QID, 66.350 con personaggio; nessun altro identificativo di persona.
- MovieLens: 87.585 link IMDb e 87.461 TMDb su 87.585 film; nessun dato sulle persone.
- **Conclusione sulle persone**: no local archive carries IMDb (nm) or TMDb person identifiers: the targeted Wikidata responses hold label/birth/death only and the film snapshots hold films. The Italian dump pages of persons were not scanned for external links (hypothesis: not a source of nm ids).

Proprietà Wikidata con tipo `external-id` presenti negli snapshot locali dei film (prime 15 per numero di entità; l'etichetta è nota solo dove verificata):

| proprietà | significato | entità film | importata dalla build |
|---|---|---|---|
| P345 | IMDb title/name ID | 40.937 | sì |
| P2529 | (label not verified) | 39.035 | no |
| P4947 | TMDb movie ID | 38.845 | sì |
| P2603 | (label not verified) | 38.516 | no |
| P6127 | Letterboxd film ID | 38.482 | no |
| P12096 | (label not verified) | 36.860 | no |
| P2704 | EIDR ID | 35.457 | sì |
| P12196 | (label not verified) | 34.640 | no |
| P11460 | (label not verified) | 34.317 | no |
| P12492 | (label not verified) | 32.147 | no |
| P8013 | (label not verified) | 31.047 | no |
| P3138 | (label not verified) | 29.725 | no |
| P12879 | (label not verified) | 28.698 | no |
| P480 | (label not verified) | 28.003 | no |
| P646 | (label not verified) | 27.569 | no |

Proprietà `external-id` distinte negli snapshot film: 948. Etichette non verificate: i numeri di proprietà sono dati, il significato va controllato in B.

Qualificatori del cast negli snapshot (utili a ordine e personaggi):

| snapshot | dichiarazioni P161 | con ordinale (P1545) | con nome del personaggio (P4633) | con personaggio come voce (P453) | entità con ordinale |
|---|---|---|---|---|---|
| film_snapshot | 365.043 | 6.579 | 35.496 | 23.132 | 236 |
| series_snapshot | 88.708 | 2.561 | 11.301 | 14.584 | 118 |

## 5. Duplicati, omonimi e conflitti (candidati, nessuna fusione)
- Opere con più identificativi dello stesso schema: {'eidr': 110, 'imdb_title': 58, 'tmdb_movie': 17, 'tmdb_movie+tmdb_tv': 338, 'tmdb_tv': 7, 'tvdb_series': 4}; prove per i doppi IMDb: {'all_ids_are_distinct_movielens_films': 5, 'no_external_evidence': 41, 'one_id_in_movielens': 12}.
- Coppie di opere con stesso titolo normalizzato e anno: {'duplicate_candidate_same_director': 7, 'homonym_different_directors': 35, 'undetermined_director_unknown': 40}.
- Persone: 1.962 nomi condivisi; coppie per classe: {'homonym_different_birth_year': 1125, 'same_person_candidate_same_birth_year': 29, 'same_person_candidate_shared_work_other_role': 44, 'same_person_candidate_strong_shared_work_and_role': 256, 'undetermined_birth_year_missing': 988}.
- Conflitti di identificativi tra fonti: {'movielens_imdb_shared_by_several_movies': 0, 'movielens_tmdb_differs_from_cinema_for_same_imdb': 257, 'movielens_tmdb_shared_by_several_movies': 36, 'snapshot_film_imdb_id_on_several_qids': 4, 'snapshot_series_imdb_id_on_several_qids': 65}.
- File dei candidati (con prove): `cinema_db/data/audit_a0/candidates_work_multiple_ids.jsonl`, `candidates_work_homonyms.jsonl`, `candidates_person_pairs.jsonl`, `candidates_id_conflicts.jsonl`.
- Classi: *strong* = stesso nome e stesso ruolo nella stessa opera (una persona accreditata due volte con QID diversi); *homonym_different_birth_year* = omonimi legittimi; *undetermined* = manca l'anno di nascita o il regista, non decidibile offline.

## 6. Cosa aggiunge ogni fonte locale

| fonte | informazione nuova rispetto a `cinema_db` | quantità misurata |
|---|---|---|
| MovieLens | voto medio e numero di voti (nessuno in cinema) | 25.626 opere già in cinema (11.976 con ≥50 voti); 30.233.131 dei 32.000.204 voti |
| MovieLens | tag degli utenti (≥2 utenti per lo stesso tag) | 156.452 coppie film-tag; 11.496 opere già in cinema |
| MovieLens | film assenti dal catalogo | 61.474 (di cui 4.058 con ≥50 voti) |
| RAG v3 | ordine di elenco degli attori nell'infobox (proxy di ordine, ipotesi) | 37.318 film, 358.210 righe |
| RAG v3 | personaggio per crediti già in cinema | 38.623 righe; nuove (cinema non ha il personaggio): 1.832 |
| RAG v3 | crediti non presenti in cinema | 41 righe collegate; 32.045 righe senza QID (nome soltanto) |
| Snapshot Wikidata | ordinale del cast (P1545) | 6.579 su 365.043 dichiarazioni film |
| Catalogo s5 | serie/film TV non in cinema per QID | serie 2.561, film TV 17, incerti 297 |
| Catalogo s5 | puntate | 78.705 nel catalogo (con numero 54.261) contro 222.415 in cinema |

## 7. Discrepanze rispetto al piano, anomalie e limiti
**Discrepanze rispetto al piano della fase 9 (documentate, non corrette altrove):**
- Il piano dava «357 opere con 2 ID TMDb». Quel conteggio raggruppava per opera gli ID `tmdb_movie` **e** `tmdb_tv`: sono opere che hanno un ID di film e uno di serie. Doppi ID dello **stesso** schema: tmdb_movie 17, tmdb_tv 7, imdb_title 58, eidr 110, tvdb_series 4. Le coppie film+serie (338) sono esportate in `candidates_work_multiple_ids.jsonl` (scheme `tmdb_movie+tmdb_tv`) e vanno classificate in B.
- «240 film in due QID» (PROGRESS) **non è riprodotto** da questo audit: qui si misurano gli ID IMDb condivisi da più QID negli snapshot (film 4, serie 65). Sono misure diverse; la fonte dei 240 non è stata ricontrollata.
- Le «33 coppie nome+anno di nascita uguali» del piano erano gruppi; qui le coppie sono classificate (vedi §5) e il numero cambia perché cambia l'unità.
- Il piano e `PROGRESS.md` citavano 293.447 opere (build della fase 3); il database attuale ne ha 301.718 (fase 4 e successive): il piano usava un numero superato, le altre cifre del piano coincidono.
- Confermati: 4.058 film MovieLens ≥50 voti assenti; *Fight Club* (1999) assente da cinema e da RAG v3; ID persona non Wikidata = 0; uscite 100 % `unspecified`.

**Anomalie osservate:**
- 88 film MovieLens mancanti hanno invece lo stesso IMDb in RAG v3, in uno snapshot Wikidata o nel catalogo s5 ma **non** in cinema (9 con ≥50 voti; esempi: *Robot Carnival*, *Cat Soup*, *Generation War*, *Grease Live*): sono opere perse tra la sorgente e la build (classificate come altro tipo o scartate). Causa non indagata: da fare in B (non è una lacuna di sorgente ma di build).
- 17 mancanti hanno una pagina itwiki accettata dall'estrazione ma nessuna opera con quell'IMDb in cinema (es. *Bottle Rocket* = «Un colpo da dilettanti»; i due *Eleanor Rigby* sono su una sola pagina): possibili IMDb diversi tra fonti o pagine che coprono più film.
- Il dump contiene 80.469 pagine con infobox film, l'estrazione ne aveva classificate 83.048 tra accettate e scartate: la differenza dipende dal criterio (categoria film senza infobox) e non è stata analizzata.

**Limiti dell'audit (non sono errori ma confini della misura):**
- I titoli MovieLens sono inglesi o originali, le pagine itwiki spesso italiane: **«nessuna pagina itwiki con quel titolo» non prova che la pagina non esista** (potrebbe avere un titolo italiano senza redirect). È un limite superiore.
- La corrispondenza per titolo e anno ±1 è un'euristica: due classi (`probable_same_work_under_other_ids`, `itwiki_title_only_candidate_year_not_confirmed`) sono **candidati**, non identificazioni.
- Le pagine scartate dall'estrazione hanno un anno ma **nessun QID né IMDb**: si possono legare a un'opera solo con Wikidata (sitelink) o con titolo+anno su un'altra fonte, quindi non in A0.
- I tempi di esecuzione non sono riportati: la scansione del dump è stata interrotta da una sospensione del computer e il suo orologio non è affidabile.
- Ordine del cast e personaggi: l'ordine di elenco dell'infobox è un indizio (ipotesi), non una fonte di *billing*.

## 8. Raccomandazioni quantitative per A1 e B
**Fatti che orientano A1 (acquisizioni, tutte da autorizzare una per una):**
1. **Persone**: nessun ID IMDb/TMDb in nessun archivio locale. Servono per 141.646 persone: la fonte candidata copre molto con un solo scaricamento (dataset IMDb) o con ≈473 richieste Wikidata a gruppi di 300 QID [stima aritmetica].
2. **Cast con ordine e personaggio**: l'ordinale Wikidata (P1545) esiste su 6.579 dichiarazioni su 365.043 (1.8 %): insufficiente. RAG v3 aggiunge solo 1.832 personaggi nuovi. Una fonte esterna è necessaria per ordine e personaggi.
3. **Film mancanti con ID noti**: i 61.474 film MovieLens mancanti hanno tutti un IMDb; 4.045 dei 4.058 con ≥50 voti hanno anche TMDb. Il bulk IMDb li identifica senza richieste per titolo.
4. **Pagine itwiki esistenti ma scartate**: 39.986 pagine con infobox film (con anno) non hanno un'opera in cinema; il motivo prevalente è `plot_too_short` (37.827), cioè un vincolo del RAG sulla trama che **non serve a un database strutturato**. Per collegarle a un'opera servono QID (sitelink) o titolo+anno su una fonte con ID.
5. **Valutazioni**: 25.626 opere già in cinema hanno statistiche MovieLens utilizzabili **senza alcuna richiesta**; tag (≥2 utenti): 11.496 opere. Le altre fonti di valutazione richiedono A1.

**Dati per decidere le soglie di ingresso in B (nessuna soglia proposta):**
- Film ML mancanti per soglia di voti: ≥1 → 58.806; ≥10 → 14.284; ≥50 → 4.058; ≥100 → 2.313; ≥1000 → 248. I voti coperti dai mancanti sono solo il 4.54 % del totale a ≥50: in termini di *attenzione degli utenti* il catalogo è già alto, ma la mancanza di titoli notissimi (§3) è visibile.
- Prima di scegliere A/B/C per i film mancanti, A1 deve misurare quanti dei 61 mila hanno un record nel dataset esterno con voti e tipo (film/corto/TV), perché MovieLens contiene anche titoli che non sono lungometraggi.

**Per B (progetto del database finale):** (a) indagare le perdite tra sorgente e build (§7); (b) classificare le 338 opere con ID TMDb di film e di serie e i 58 doppi IMDb; (c) esaminare i 256 candidati forti di persone doppie; (d) fissare le regole di ingresso usando la curva di §2 e i risultati di A1; (e) decidere se le pagine itwiki scartate per trama breve entrano come opere senza trama.

## 9. Riproducibilità
```bash
python -m cinema_db.harness.audit.run_audit targets   # MovieLens mancanti -> targets.json
python -m cinema_db.harness.audit.run_audit scan      # una passata sul dump locale -> dump_scan.jsonl
python -m cinema_db.harness.audit.run_audit run       # tutte le sezioni -> results.json + candidati
python -m cinema_db.harness.audit.run_audit report    # questo documento
python -m pytest tests/test_cinema_audit.py -q        # 8 test, offline, miniature
```
Gli output stanno in `cinema_db/data/audit_a0/` (ignorata da git: `results.json`, `ml_missing.jsonl`, `candidates_*.jsonl`, `dump_scan.jsonl`); `results.json` è copiato anche in `docs/cinema_db/PHASE9_A0_RESULTS.json`.

