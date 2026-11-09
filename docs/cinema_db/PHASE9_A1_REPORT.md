# Fase 9 — A1: acquisizione IMDb e analisi (rapporto)

Generato da `python -m cinema_db.harness.audit.run_a1 report`. Misurato = calcolato sui file; *ipotesi* e *stima* sono dichiarate. Autorizzate e usate **solo** le quattro acquisizioni IMDb (`title.basics`, `name.basics`, `title.principals`, `title.crew`). Nessuna richiesta a TMDb, OMDb, TVmaze, Wikidata, OpenAI. Nessun database, snapshot, MovieLens o catalogo RAG modificato.

## 1. Acquisizione e archivio

| dataset | byte | sha256 | acquisito (UTC) | Last-Modified del server |
|---|---|---|---|---|
| name.basics | 312.602.615 | cf0e550dec6a35e6… | 2026-11-08T12:56:22Z | Sat, 07 Nov 2026 12:58:16 GMT |
| title.basics | 230.046.569 | 13f6a416aaf8cf54… | 2026-11-08T12:56:16Z | Sun, 08 Nov 2026 00:30:32 GMT |
| title.crew | 84.003.630 | d0825a092267e69c… | 2026-11-08T12:56:29Z | Sun, 08 Nov 2026 00:31:11 GMT |
| title.episode | 55.403.804 | 0b7aba203b92e800… | 2026-11-08T14:12:37Z | Sun, 08 Nov 2026 00:30:52 GMT |
| title.principals | 789.739.416 | 5f416017611acf78… | 2026-11-08T12:56:30Z | Sun, 08 Nov 2026 00:31:26 GMT |
| title.ratings | 8.741.674 | a1e7ef9ff031aa53… | 2026-11-08T14:12:37Z | Sun, 08 Nov 2026 00:31:11 GMT |

- Archivio read-only: `cinema_db/data/imdb_snapshot/2026-11-08/` con `manifest.json` (URL `https://datasets.imdbws.com/<dataset>.tsv.gz`, URL finale, stato HTTP, client). Verifica degli hash: `python -m cinema_db.harness.acquire.imdb verify`.
- Nota: `name.basics` risulta modificato il 7 novembre, gli altri tre l'8 novembre (il sito li rigenera ogni giorno): i dataset non sono un'unica istantanea atomica. Effetto atteso minimo (ipotesi).
- `title.basics`: 12.947.333 titoli; conservati nel file di analisi 3.725.891 (tipi di opera audiovisiva più tutti gli ID di interesse). Per tipo: movie 760.303, short 1.168.126, tvEpisode 10.022.141, tvMiniSeries 74.124, tvMovie 156.961, tvPilot 1, tvSeries 307.991, tvShort 11.108, tvSpecial 62.345, video 333.242, videoGame 50.991.
- `title.crew` 12.947.333 righe (conservate 3.725.891); `title.principals` 102.617.182 righe, conservate 2.324.243 (titoli di cinema_db, di MovieLens e candidati delle pagine italiane); `name.basics` 15.797.779 persone, conservate 678.311.
- File di analisi (non è il database di prodotto): `cinema_db/data/audit_a1/imdb_staging.sqlite3`, ignorato da git, ricostruibile con `run_a1 stage`.

## 2. Copertura IMDb sulle opere di `cinema_db`
- Opere con ID IMDb in cinema: 54.612; presenti in `title.basics`: 54.578 (99.94 %). **Non** presenti (ID probabilmente fuso o ritirato): 34 (film 8, miniseries 2, series 23, short 1).
- Accordo dell'anno: {'different': 429, 'equal': 51403, 'off_by_one': 2021}; della durata: {'different': 3834, 'equal': 23415, 'within_5_min': 9806}.
- Dati che IMDb darebbe dove cinema è vuoto: durata 13.554 opere, generi 2.361, anno 722.
- Opere di cinema segnalate adulte da IMDb: 124.
- Opere con **due** ID IMDb (58 in A0): {'all_ids_known_to_imdb': 44, 'exactly_one_id_known_to_imdb': 14} → in 14 casi uno dei due ID non esiste più in IMDb (ID obsoleto); in 44 esistono entrambi (due titoli IMDb distinti: candidati a duplicato o a edizioni diverse, non decidibili senza ulteriori prove).

Tipo di opera in cinema contro tipo IMDb (le 20 combinazioni più frequenti; le discordanze sono un controllo sulla classificazione di cinema, non una correzione):

| tipo in cinema | tipo IMDb | opere |
|---|---|---|
| episode | tvEpisode | 74 |
| episode | tvMovie | 1 |
| episode | video | 1 |
| film | movie | 34.803 |
| film | short | 566 |
| film | tvEpisode | 13 |
| film | tvMiniSeries | 7 |
| film | tvMovie | 177 |
| film | tvSeries | 2 |
| film | tvShort | 4 |
| film | tvSpecial | 5 |
| film | video | 690 |
| film | videoGame | 2 |
| miniseries | movie | 8 |
| miniseries | tvEpisode | 13 |
| miniseries | tvMiniSeries | 1.109 |
| miniseries | tvMovie | 244 |
| miniseries | tvSeries | 221 |
| miniseries | video | 1 |
| other | movie | 3 |

Ad esempio 1.466 opere classificate `film` in cinema hanno un tipo IMDb diverso da `movie` (video, cortometraggio, film TV…): da valutare in B prima di fidarsi dell'una o dell'altra classificazione.

## 3. Persone e crediti
Metodo: ID del titolo + nome normalizzato (insieme di parole) + ruolo compatibile; l'anno di nascita conferma o smentisce. **Nessuna fusione, nessun ID assegnato**: è una misura di recuperabilità.

| esito per persona | persone | % delle persone di cinema |
|---|---|---|
| risolte con prova forte (≥2 titoli concordi, o 1 titolo + anno di nascita uguale) | 70.754 | 49.95 |
| risolte con un solo titolo e senza conferma dell'anno | 17.269 | 12.19 |
| conflitto: anno di nascita diverso | 2.544 | 1.8 |
| conflitto: più ID IMDb candidati | 417 | 0.29 |
| non risolte | 50.662 | 35.77 |

- Persone di cinema: 141.646; con almeno un credito su un'opera con ID IMDb: 139.941.
- Crediti di cinema: 675.327; su opere con ID IMDb 674.033; riconosciuti in IMDb come stessa persona e ruolo: **422.359** (62.54 %).

| ruolo | crediti in cinema | riconosciuti in IMDb | % | crediti IMDb non presenti in cinema (candidati nuovi o nomi diversi) |
|---|---|---|---|---|
| cast | 441.298 | 237.291 | 53.77 | 307.516 |
| director | 52.097 | 48.509 | 93.11 | 3.265 |
| writer | 51.217 | 46.034 | 89.88 | 50.359 |
| producer | 37.061 | 24.695 | 66.63 | 33.601 |
| composer | 31.842 | 22.429 | 70.44 | 14.885 |
| cinematographer | 25.440 | 22.199 | 87.26 | 18.074 |
| editor | 19.086 | 16.967 | 88.9 | 23.768 |
| production_designer | 7.533 | 4.235 | 56.22 | 20.801 |
| creator | 4.962 | 0 | 0.0 | 0 |
| costume_designer | 4.791 | 0 | 0.0 | 0 |

- **430 ID IMDb di persona sono reclamati da più di una persona di cinema**: candidati a duplicato (file `candidates_nconst_shared.jsonl`), da non fondere in A1.
- Persone non risolte, per motivo misurato: no credit on a work with imdb id 1.705, only cast credits on titles whose imdb cast list is full (10 or more) 39.125, other credit roles or short imdb lists (possible name or identity mismatch) 9.832. `title.principals` elenca solo i primi accreditati di ogni titolo (vedi §4), mentre cinema, da Wikidata, arriva a centinaia di nomi per film. Un ID per le persone non risolte richiederebbe un'altra fonte (nessuna autorizzata ora).

## 4. Ordine del cast e personaggi
- Crediti di cast in cinema: 441.298; riconosciuti in IMDb: 237.291 (53.77 %), tutti con un **ordine** (`ordering`).
- Film con crediti di cast e ID IMDb: 41.653; film che acquisirebbero l'ordine per almeno un credito: 41.055 (98.56 %).
- Personaggi: disponibili per 233.955 dei crediti riconosciuti; **nuovi** per cinema (cinema non li ha) 207.117; dove entrambi li hanno (26.838) coincidono (uguali o contenuti) in 22.044 casi e differiscono in 4.794 (17.86 %; ipotesi: lingua o formulazione diversa).
- Titoli di cinema con cast principale in IMDb: mediana 10 attori per titolo (90° percentile 11, massimo 42); distribuzione (10 = 10 o più): {'1': 4255, '2': 4028, '3': 4182, '4': 4642, '5': 4580, '6': 4012, '7': 3663, '8': 3362, '9': 3103, '10': 106046}.
- Crediti di cast **non** riconosciuti: 204.007; di questi 202.329 stanno su titoli i cui principali IMDb sono già 10 o più (l'elenco è troncato: sono attori oltre i primi accreditati), solo 898 su titoli con meno di 10 (possibile discrepanza di nome o di identità). Conclusione: **l'ordine è recuperabile per i primi accreditati, non per l'intero cast**.

Regia (confronto con `title.crew`, opere di tipo film/corto/film TV con ID IMDb): cinema_has_directors_imdb_has_none 23, directors_disagree_or_names_unmatched 1.023, directors_overlap 39.910, imdb_has_directors_cinema_has_none 1.011, neither_has_directors 396, title_not_in_crew_file 9.

## 5. I 61.474 titoli MovieLens mancanti, classificati con IMDb

| classe (da tipo IMDb) | titoli | % dei mancanti | con ≥50 voti |
|---|---|---|---|
| lungometraggio | 48.197 | 78.4 | 3.542 |
| cortometraggio | 4.335 | 7.05 | 118 |
| film_tv | 5.685 | 9.25 | 208 |
| serie | 449 | 0.73 | 54 |
| episodio | 720 | 1.17 | 35 |
| altro | 1.862 | 3.03 | 65 |
| non_identificabile_via_imdb | 226 | 0.37 | 36 |

Mappatura: `movie` → lungometraggio; `short`/`tvShort` → cortometraggio; `tvMovie`/`tvSpecial` → film TV; `tvSeries`/`tvMiniSeries` → serie; `tvEpisode` → episodio; `video`, `videoGame`, `tvPilot` → altro. Tipi IMDb: (not in title.basics) 226, movie 48.197, short 4.171, tvEpisode 720, tvMiniSeries 358, tvMovie 4.791, tvSeries 91, tvShort 164, tvSpecial 894, video 1.860, videoGame 2.

Per soglia di voti MovieLens (nessuna soglia è scelta qui):

| voti ≥ | mancanti | lungom. | corto | film TV | serie | episodio | altro | non identif. |
|---|---|---|---|---|---|---|---|---|
| 1 | 58.806 | 45.989 | 4.263 | 5.431 | 441 | 698 | 1.765 | 219 |
| 5 | 23.446 | 19.208 | 1.433 | 1.578 | 237 | 264 | 610 | 116 |
| 10 | 14.284 | 11.920 | 737 | 883 | 164 | 153 | 345 | 82 |
| 20 | 8.299 | 7.055 | 340 | 492 | 101 | 89 | 159 | 63 |
| 50 | 4.058 | 3.542 | 118 | 208 | 54 | 35 | 65 | 36 |
| 100 | 2.313 | 2.055 | 50 | 106 | 31 | 12 | 34 | 25 |
| 500 | 543 | 491 | 8 | 16 | 9 | 4 | 6 | 9 |
| 1000 | 248 | 227 | 6 | 7 | 4 | 1 | 1 | 2 |
| 5000 | 27 | 26 | 0 | 0 | 0 | 0 | 0 | 1 |
| 10000 | 8 | 8 | 0 | 0 | 0 | 0 | 0 | 0 |

**Lungometraggi** (`movie`): 48.197. Di questi 491 hanno in cinema un'opera con lo stesso titolo (primario o originale) e anno ±1 (probabile stesso film con altro ID: *candidato*, non verificato), quindi **47.706 sarebbero lungometraggi nuovi** per il catalogo. Durata: {'120+': 4944, '40-59': 929, '60-89': 16177, '90-119': 26018, '<40': 3, 'unknown': 126}; documentari 6.963; segnalati adulti 24; anno IMDb diverso da MovieLens di più di un anno: 696. Per decennio: 1900s 2, 1910s 51, 1920s 219, 1930s 1.446, 1940s 1.376, 1950s 1.604, 1960s 2.140, 1970s 3.047, 1980s 3.131, 1990s 3.738, 2000s 7.877, 2010s 18.302, 2020s 5.253, unknown 11.


| voti ≥ | lungometraggi | di cui senza candidato in cinema |
|---|---|---|
| 1 | 45.989 | 45.508 |
| 5 | 19.208 | 18.987 |
| 10 | 11.920 | 11.783 |
| 20 | 7.055 | 6.981 |
| 50 | 3.542 | 3.511 |
| 100 | 2.055 | 2.037 |
| 500 | 491 | 488 |
| 1000 | 227 | 227 |
| 5000 | 26 | 26 |
| 10000 | 8 | 8 |

**Non identificabili tramite IMDb**: 226 (ID assente da `title.basics`; con ID TMDb in MovieLens: 217); per soglia: {'1': 219, '10': 82, '100': 25, '1000': 2, '10000': 0, '20': 63, '5': 116, '50': 36, '500': 9, '5000': 1}. Esempi più votati: Wallace & Gromit: The Best of Aardman Animation (1996) (8.612 voti); Confessions of a Dangerous Mind (2002) (3.636 voti); Lagaan: Once Upon a Time in India (2001) (949 voti); Clockstoppers (2002) (848 voti); Pokémon 3: The Movie (2001) (759 voti); Force Majeure (Turist) (2014) (689 voti). Ipotesi: ID IMDb fusi o ritirati dopo la compilazione di MovieLens (2023); si possono recuperare solo con un'altra fonte (TMDb, **non autorizzata**).

## 6. Pagine italiane scartate per trama breve o assente
Pagine con infobox film scartate dall'estrazione e valutate: 40.612. Criteri (rigidi, applicati nell'ordine): **identificata** = esattamente un titolo IMDb di tipo audiovisivo con anno uguale a quello della pagina, titolo (o titolo originale) uguale e almeno un regista in comune; **dubbia** = esistono candidati ma i tre requisiti non valgono in modo unico; **nessun candidato**. Nessun criterio è stato abbassato.

| stato | pagine | % |
|---|---|---|
| opera identificata, senza trama | 28.163 | 69.35 |
| opera dubbia, da non inserire automaticamente | 8.842 | 21.77 |
| nessun candidato IMDb | 3.606 | 8.88 |
| già in cinema (stesso ID) | 1 | 0.0 |

- Identificate per tipo IMDb: {'movie': 17364, 'short': 10328, 'tvMovie': 164, 'tvShort': 2, 'tvSpecial': 4, 'video': 301}; per motivo di scarto: {'no_plot_section': {'already_in_cinema': 1, 'dubious': 351, 'identified_without_plot': 2119, 'no_candidate': 314}, 'plot_too_short': {'dubious': 8491, 'identified_without_plot': 26044, 'no_candidate': 3292}}.
- Pagine senza anno: 17 (mai identificate); senza regista sulla pagina: 3.826 (non possono superare il requisito del regista: restano dubbie o senza candidato).
- Lo stato «opera identificata con trama» non riguarda queste pagine: sono le 41.138 già nel catalogo RAG (hanno QID e trama).
- Queste pagine hanno ora un ID IMDb ma **non** un QID Wikidata (nessuna richiesta Wikidata): per cinema servirebbe comunque un'identità interna; la riconciliazione col QID resta aperta.

**Verifica dei criteri su verità nota**: applicati alle 39.552 pagine del catalogo RAG di cui l'ID IMDb è già noto, i criteri identificano 32.232 pagine (richiamo 81.49 %) e danno l'ID giusto in 32.210 casi: **precisione 99.93 %** (22 errori). Gli esiti sulle pagine scartate non sono quindi perfetti: l'errore atteso è dell'ordine di (100 − precisione) %.

**Lungometraggi nuovi** (stessa regola su entrambe le vie: tipo IMDb `movie`): da MovieLens, senza candidato in cinema, 47.706; dalle pagine italiane identificate 17.363 (tutti i tipi: 28.162); in comune 7.805; **unione 57.264**. Nessuna soglia di rilevanza applicata: la decisione su quanti «meritano» di entrare è per B con le tabelle sopra.

## 7. La perdita dei film tra fonte e build (le «88»)
Percorso ricostruito leggendo `cinema_db/harness/build/build.py` (non eseguito) e verificato sui record. Gli identificativi IMDb presenti in una fonte locale e assenti da cinema sono **915**, di cui **88** in MovieLens (le 88 di A0).

| causa (primo punto di esclusione) | 88 in MovieLens | tutti i 915 |
|---|---|---|
| series_catalogue_uncertain_records_not_imported | 5 | 105 |
| series_imported_without_identifiers | 67 | 384 |
| series_not_imported:franchise_page_mixed_media | 7 | 338 |
| snapshot_entity_excluded_by_series_catalogue:override_exclude | 0 | 1 |
| snapshot_entity_excluded_in_cleaning:approved | 2 | 2 |
| snapshot_entity_excluded_in_cleaning:other_work | 0 | 3 |
| snapshot_entity_excluded_in_cleaning:series | 1 | 2 |
| snapshot_entity_excluded_in_cleaning:topic | 0 | 4 |
| tv_movie_imported_without_identifiers | 3 | 14 |
| wikidata_snapshot_entity_without_catalogue_record | 3 | 62 |

Lettura delle cause:
1. `series_imported_without_identifiers` — `build.series()` importa la serie ma, se `ids_reliable` è falso nel catalogo s5, **non** aggiunge né QID né IMDb: l'opera è in cinema ma senza identificativi, quindi non risulta quando si cerca per ID. È la causa dominante (67 su 88 in MovieLens). I tipi IMDb di queste 88: {'movie': 3, 'short': 2, 'tvEpisode': 1, 'tvMiniSeries': 42, 'tvMovie': 16, 'tvSeries': 7, 'tvShort': 2, 'tvSpecial': 4, 'video': 11} (miniserie e film TV soprattutto).
2. `series_not_imported:franchise_page_mixed_media` — `default_search_eligible` falso: pagine miste manga/anime scartate per scelta (2.032 in tutto).
3. `series_catalogue_uncertain_records_not_imported` — `uncertain.jsonl` non è un input della build.
4. `tv_movie_imported_without_identifiers` — come la 1 per `tv_movies()`.
5. Entità degli snapshot senza record di catalogo: l'entità c'è ma nessun catalogo la elenca; dove possibile la causa è la pagina scartata dall'estrazione o esclusa nella pulizia (tabella).

Quanto IMDb **conferma** i record persi (stesso titolo e anno ±1; è un minimo, perché titoli italiani e IMDb spesso differiscono): series_catalogue_uncertain_records_not_imported: 65/105, series_imported_without_identifiers: 185/384, series_not_imported:franchise_page_mixed_media: 98/338, tv_movie_imported_without_identifiers: 12/14.
Opere già presenti in cinema (stesso titolo) ma senza identificativo: series_catalogue_uncertain_records_not_imported: 7, series_imported_without_identifiers: 341, series_not_imported:franchise_page_mixed_media: 27, tv_movie_imported_without_identifiers: 13.

**Soluzione proposta (NON applicata, la pipeline non è stata modificata):** (a) per i record con `ids_reliable` falso, aggiungere l'ID IMDb e il QID come identificativi *non primari* quando IMDb conferma titolo, anno e tipo (misurato sopra), conservando la provenienza e lasciando fuori gli altri; (b) per le pagine miste manga/anime ammettere solo quelle che IMDb classifica come film o serie e confermano titolo e anno; (c) leggere `uncertain.jsonl` con la stessa conferma IMDb; (d) lasciare fuori le entità escluse in pulizia per tema (argomenti, non opere). Da decidere in B insieme alla regola di ingresso.

## 8. Limiti residui e acquisizioni che potrebbero servire
- **Cast**: IMDb copre l'ordine e i personaggi dei soli primi accreditati (mediana 10 per titolo). Per il cast completo restano Wikidata (senza ordine) o un'altra fonte (TMDb), non autorizzata.
- **Persone non risolte** (50.662): per la maggior parte sono comparse oltre i primi accreditati; un ID richiede un'altra fonte o l'uso di `knownForTitles` di `name.basics` (non usato in A1).
- **Titoli non identificabili** (226 di MovieLens, 34 opere di cinema): servono TMDb (ID di MovieLens) o altro.
- **Valutazioni**: `title.ratings` di IMDb **non** era tra i dataset autorizzati e non è stato scaricato; MovieLens resta l'unica fonte locale di voti.
- **Episodi e stagioni**: `title.episode` non autorizzato; i 222 mila episodi di cinema restano senza ID IMDb (76 con ID).
- **Pagine italiane**: l'identificazione si basa su titolo, anno e regista; le 8.842 dubbie e le 3.606 senza candidato richiederebbero Wikidata (sitelink) o TMDb.
- **Anno e tipo**: IMDb e cinema discordano in migliaia di casi (§2); la scelta della fonte prevalente per campo è una decisione di B.
- Il matching di persone e titoli è un'euristica documentata; nessuna riga è stata scritta nel database di prodotto.

## 9. Riproducibilità e integrità
```bash
python -m cinema_db.harness.acquire.imdb fetch <dataset>    # un dataset alla volta; non riscarica se già nel manifest
python -m cinema_db.harness.acquire.imdb verify            # hash dell'archivio
python -m cinema_db.harness.audit.run_a1 stage             # archivio -> file di analisi (circa 5 minuti)
python -m cinema_db.harness.audit.run_a1 run               # analisi -> results.json e candidati
python -m cinema_db.harness.audit.run_a1 report            # questo documento
python -m pytest tests/test_imdb_acquire.py tests/test_cinema_audit_imdb.py tests/test_cinema_audit.py -q
```
Output in `cinema_db/data/audit_a1/` (ignorata da git): `results.json`, `ml_missing_classified.jsonl`, `italian_pages_classified.jsonl`, `build_losses.jsonl`, `candidates_*.jsonl`, `staging_stats.json`. Copia dei risultati: `docs/cinema_db/PHASE9_A1_RESULTS.json`.

