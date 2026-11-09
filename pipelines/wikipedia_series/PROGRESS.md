# wikipedia_series — PROGRESS (documento di ripresa)

Aprire una sessione nuova, leggere `AGENTS.md` e questo file: bastano per ripartire. **Stato dal 2026-11-08: embedding, collezione, retriever e valutazione FATTI** (§0); resta la registrazione come tool dell'agente (decisione separata) e la fase di test reali.
Ultimo aggiornamento: 2026-11-08 (seconda sessione: tool dell'agente dietro flag, routing live, e2e, §0bis). Nulla è stato committato in questa sessione (HEAD `06ba627`; i commit di §9 sono della sessione precedente).

Legenda: **[V]** verificato (con il comando indicato) · **[S]** stima · **[P]** solo progettato, non fatto.

## 0ter. Terza sessione 2026-11-09 (classificatore, frontend, routing) [V]
Dettagli in `EVAL_REPORT.md` §11. Fatto: prompt del classificatore esteso agli anime (21/21 su 21 frasi, 99/99 domande di routing ancora cinematografiche; autorizzato dal proprietario); rendering del `kind` `series_index` nel frontend `marco-m-netflix` (lint, prettier, build, controllo Node; non provato in un browser); l'elenco degli episodi di una stagione va a `tvmaze_search`, la trama di stagioni/episodi descritti a `series_rag_search` (routing live 23/24, flag spento 71/77 con le stesse sei differenze del codice di HEAD); e2e limitato 5/5. `series_rag.enabled` resta **False**; nessun nuovo embedding né acquisizione; nessun commit. Limiti documentati: stagioni incomplete, buchi di numerazione, franchise. **Ambiente di prova**: `SERIES_RAG_ENABLED=1` con Qdrant acceso, backend e frontend (`npm run serve`); rollback: togliere la variabile.

## 0bis. Seconda sessione 2026-11-08: tool dell'agente `series_rag_search` (dietro flag, SPENTO) [V]
Dettagli, numeri e limiti in **`EVAL_REPORT.md` §6–§10**. In sintesi:
- **Fatto**: pacchetto `tool/rag/series/` (retriever di runtime, tool, trace), registrato da `app.build_app` solo con `series_rag.enabled` (spento di default; `SERIES_RAG_ENABLED=1`), regola di routing **1h** presente nel prompt solo se il tool è registrato (con il flag spento il prompt è identico: test), `tool_final_instructions`, `SOURCE_TOOLS` = `official information`, guardia `content_type` (`SERIES_ONLY_TOOLS`), presenter terminale/web (step `series_index`, it/en/de, licenza CC BY-SA, nessun `calls`), contratto SSE documentato e sincronizzato da un test, casi di routing (`SERIES_ROUTING_CASES`) e runner e2e (`movie_db/harness/evaluation/run_series_e2e.py`).
- **Test offline**: 2.938 passati, 1 saltato (suite di `AGENTS.md` + test del film e delle serie; `tests/test_series_rag.py` 25). **Routing live**: 19/22 al primo giro (confini 11/11), poi 8/11 sui soli casi del tool con la regola corretta; i residui sono attese troppo strette («un/una = 1») e il **classificatore di dominio che blocca «Consigliami un anime…»** (non toccato). **E2E** (17 turni, Qdrant + LLM + TMDb + TVmaze reali): 0 errori, routing 17/17, pertinenza 1,86/2, aderenza ai dati 1,71/2, turno mediano 13,4 s (tool 5,1 s, di cui riordino 2,2 s e parser 2,4 s), 0 chiamate HTTP a terzi del tool. Un turno reale via `web_api` (SSE) mostra lo step `series_index` e nessuna chiave nel flusso.
- **Costi**: nessun nuovo embedding del corpus (4,768 USD restano il totale). Query e2e: 377 token di embedding. LLM: 66 chiamate di routing + 17 turni e giudizi + 1 turno web, non misurate in dollari (pochi decimi). Token per stadio in `EVAL_REPORT.md` §9.
- **Decisioni confermate dal proprietario**: pagine miste manga/anime escluse dalla ricerca descrittiva (titolo esatto consentito); nessun confronto con un vecchio RAG delle serie inesistente; RAG film, `cinema_db` e relativi runtime non toccati; il vecchio RAG cinematografico non viene sostituito.
- **Prima dell'attivazione**: (1) ~~il frontend deve rendere il `kind` `series_index`~~ fatto (§0ter), da provare in un browser; (2) ~~decidere sul prompt del classificatore per «anime»~~ fatto (§0ter); (3) eventuale taratura del costo del riordino. **Attivazione**: Qdrant acceso, `SERIES_RAG_ENABLED=1` per `uvicorn web_api.main:app` o `python app.py`. **Rollback**: togliere la variabile e riavviare; la collezione non si tocca.
- Il punto 6 di §8 (registrazione come tool) è quindi FATTO ma non attivo; restano i test reali complessivi e, dopo, la decisione sul vecchio RAG.

## 0. Sessione 2026-11-08: embedding, collezione, retriever, valutazione [V]
Dettagli, tabelle e limiti in **`EVAL_REPORT.md`**. In sintesi:
- **Embedding**: 101.706 unità, `text-embedding-3-large` 1.536 dim, **4,768 USD** reali (= stima), 796 shard riprendibili in `data/s7/shards`, 0 errori (`embed.py`; richiede `SERIES_EMBED_AUTHORIZED=yes`). `python -m pipelines.wikipedia_series.embed plan|verify` offline.
- **Collezione `wikipedia_series_it_v1`**: 101.706 punti (serie 11.478, stagioni 9.971, episodi 78.705, film TV 1.552), verificata punto per punto (`index.py check`: 0 differenze); le collezioni dei film e `netflix_scout` intatte (sha256 degli id). Campo aggiunto dopo: `title_base_norm` (`index.py patch-title-base`).
- **Retriever** autonomo `retrieval.py`: UN retriever denso, livello (`entity_type`) obbligatorio, pagine miste manga/anime nascoste salvo richiesta sul manga o titolo esatto, serie nominata → `series_id`, navigazione padre/figli senza vettori, esclusioni per penalità, riordino LLM opzionale (raccomandato), nessun RRF né fusione né ripiego. Test: `tests/test_embed_and_retrieval.py` (14).
- **Misure**: l'indice unico regge (la ricerca mista seppellisce le stagioni: h@10 0,22 contro 0,59 filtrata); nominare la serie porta gli episodi a h@5 0,92. Batteria di 36 domande con giudice cieco: validi 47,5 % → **72,6 %** col riordino (migliore su 20 domande, peggiore su 1). Costo della decisione 8: le serie con pagina mista manga/anime non si trovano per descrizione (h@10 0,00 contro 0,89).
- **Discrepanze trovate tra documenti e stato reale**: (1) il prompt di ripresa citava `tool/RAGWikipedia/…` e `wikipedia_films_it_v2` con 41.137 film: la cartella è `pipelines/wikipedia_films/` e la collezione attiva è `_v3` (41.138); la `v2` resta intatta. (2) La «suite A/B da 62 test» è la batteria dei **film** (`wikipedia_films/eval/battery.json`) e chiede film: non è applicabile ai dati delle serie e non esiste un vecchio RAG delle serie; è stata scritta una batteria nuova equivalente (`eval/battery.json`, 36 domande). (3) §9 è corretto: i commit `bf06cbc`, `58b2862`, `33284a6` sono nella storia del ramo (HEAD `06ba627`); i file nuovi di questa sessione (`embed.py`, `index.py`, `retrieval.py`, `eval_known_item.py`, `eval/`, `schema_map.py`, `EVAL_REPORT.md`, `reports/series_data_map.md`, il test nuovo) sono non tracciati e non committati. (4) 150 figli hanno il padre in `uncertain` e 27 coppie (serie, stagione) sono duplicate: documentati in `reports/series_data_map.md`.
- **Mappa dei dati**: `reports/series_data_map.md` (campi e tipi, chiavi, relazioni con cardinalità misurate, payload Qdrant), generata da `python -m pipelines.wikipedia_series.schema_map`. La mappa del database relazionale (`cinema_db`, tabelle/colonne/PK/FK/cardinalità) è `docs/cinema_db/schema.html` e `schema_v3.html`, già coerenti con il file (`schema.generate --check` → exit 0); non toccata.

## 1. Stato in una riga (storico, prima di questa sessione)
Il **dataset pulito è pronto e verificato** [V] (`build_clean verify` → «VERIFY OK: byte-identical rebuild»; 24 controlli di coerenza; 58 test). **Non esistono** (tutto [P]): embedding, collezione Qdrant `wikipedia_series_it_v1`, retriever, valutazione densa, tool dell'agente. Nessuna chiamata a pagamento è stata fatta. Il saldo OpenAI era esaurito; il prossimo passo richiede crediti **e** il consenso del proprietario (§8).

## 2. Architettura e separazione dai film
- `pipelines/wikipedia_films/` (rinominato da `tool/RAGWikipedia`, solo percorsi/import) = dati, audit e valutazione del RAG film. A runtime l'app usa **solo** `tool/rag/film/retrieval/` (retriever attivo, collezione `wikipedia_films_it_v3`, 41.138 film). Il RAG film non è stato modificato dal lavoro sulle serie [V: regressione identica byte per byte, vedi §7].
- `pipelines/wikipedia_series/` (questo progetto) = pipeline dati indipendente. **Nessun import da `pipelines/wikipedia_films`** (`tests/test_tool_package.py`): i moduli generici (`dump.py`, `clean_plot.py`, `wikidata_client.py`, `config.py`) sono copie. Si condivide solo il FILE del dump per percorso (`common.DUMP_PATH` = `pipelines/wikipedia_films/data/raw/itwiki-20261101-pages-articles.xml.bz2`, 4.286.436.387 byte, SHA-1 `53d757d92a4f3956880586074008f08a08760641`, sola lettura).
- Non è registrato nell'agente: nessun riferimento in `app.py`, `orchestrator.py`, `web_api`, `presenters`, `preferences`, `tool/rag` [V]. La regola `content_type=series` e `tvmaze_search`/`tmdb_search` restano invariate.
- Cache Wikidata propria: `data/cache/wikidata/itwiki-20261101-series-a` (188 MB, append-only). User-Agent con URL del repository, senza e-mail personali (`config.yaml`).
- Git: `data/` è ignorato (`pipelines/wikipedia_series/.gitignore:2`, `pipelines/wikipedia_films/.gitignore:2`, `.gitignore:74`). Versionati: codice, test, `config.yaml`, `PROGRESS.md`, `reports/*.json` (manifest e report sintetici) e `review/overrides.json` (decisioni: NON in `data/`).

## 3. Dataset finale [V] (`data/s5/`, 283 MB; hash in `data/s5/manifest.json`, copia in `reports/s5_manifest.json`)
| File | Record | sha256 (primi 8) | Contenuto |
|---|---|---|---|
| `series.jsonl` | 15.697 | 31ba067c | serie TV, miniserie, serial, webserie, anime, serie animate, programmi episodici |
| `seasons.jsonl` | 15.032 | 585fc678 | 10.829 pagine con serie + 28 orfane (senza serie) + 4.175 **logiche** (senza testo, da evidenza nella pagina serie) |
| `episodes.jsonl` | 78.705 | 7322eb20 | episodi con trama (sezioni di pagine stagione/lista, 106 pagine episodio) |
| `episodes_meta.jsonl` | 147.249 | c9b80960 | righe di tabella (numero, titolo, data) senza trama: solo metadati, non vettori |
| `tv_movies.jsonl` | 2.578 | dafb616b | film TV narrativi, tipo autonomo |
| `uncertain.jsonl` | 303 | f01ee8ea | casi non classificabili (286 programmi + 17 film TV), mai forzati |
| `excluded.jsonl` | 9.684 | 020263d8 | esclusi, ognuno con motivo (programmi non episodici 3.960, manga/altra animazione 3.940, nessun segnale 1.634, film TV non narrativi 102, override 48) |
`overrides.json` sha256 `bed7583b…`. Altri file: `catalog_report.json`, `coherence.json`, `manifest.json`.

**Serie 15.697** per `subtype`: tv_series 7.526 · anime 3.007 · animated_series 2.062 · miniseries 1.901 · serial 678 · programme 400 · web_series 123. Testo: `plot` 8.711 · solo introduzione (`lead`) 2.767 · nessuno 4.219 (solo metadati). Con QID 15.675, con IMDb 12.904. `class_check` (infobox ↔ classe Wikidata P31): concordi 13.217 · `wikidata_film` 248 (+5) · `wikidata_other` 1.913 (≈1.650 sono pagine miste manga+anime) · sconosciuti 292 · senza entità 22; `ids_reliable = false` su 2.480.
**Serie miste manga/anime (`mixed_media`) 2.032**: restano nel catalogo, `catalog_class = franchise_page_mixed_media`, `default_search_eligible = false`; idonee alla ricerca predefinita 13.665. Flag verificato con un conteggio indipendente degli infobox su 5.069 pagine anime/animate: 5.067 concordi, 2 falsi negativi corretti con override M1 (Cobra (manga), Kyōkasho ni Nai!). Il flag descrive la struttura della pagina, non il contenuto del testo (solo 268/1.763 testi misti nominano manga/fumetto/videogioco nei primi 600 caratteri).
**Film TV 2.578** (`entity_type = tv_movie`, `series_id/season_id/parent_ids` nulli, nessuna relazione con serie/stagioni): plot 1.445 · introduzione 107 · senza testo 1.026 (solo metadati). IMDb 2.470, TMDb 2.329, **senza TMDb mantenuti 249**. Esclusi 102 non narrativi (documentari, concerti…). 23 passati da `uncertain` a `tv_movie` (regola U1). ≈115 pagine con la categoria «Film … per la televisione» ma senza infobox FictionTV NON sono incluse (candidati secondari, non esaminati).
**Episodi**: con serie nota 78.354 · con stagione-pagina 64.364 · numerati 54.235 (solo per titolo esatto = riga di tabella; **mai per posizione**) · senza numero 24.470.
**Provenienza**: ogni record ha `wikipedia_url`, `revision_id`, `text_kind` (`plot`/`lead`/`season_intro`/`series_section`/`none`) e, per serie e film TV, `text_provenance` (fonte it.wikipedia, revisione, sezione: Trama/Storia/Sinossi/introduzione). `original_classification` e `review_note` presenti sui record riclassificati. Relazioni: `relation_status` ∈ verified_wikidata / verified_wikipedia / inferred / reviewed / orphan (+`conflict` risolti).

## 4. Come è stato costruito (pipeline S0–S6, tutte [V])
| Fase | Modulo | Esito |
|---|---|---|
| R | rinomina | `tool/RAGWikipedia`→`wikipedia_films`; 2091 test app, 105 film, `build_v3 verify`/`indexing.v3 check` identici prima/dopo |
| 0 | `phase0/*` | scan integrale del dump (4.154.227 pagine, 64 min) e harvest del wikitext (37.717 pagine, 20 min); misure in §6 |
| S1 | `extract_series.py` | `data/s1/`: serie, stagioni, episodi, liste «Episodi di X», film TV, incerti, esclusi; rilancio = byte identico |
| S1b | `harvest_animation.py` | lacuna scoperta nel dry-run S3: 5.233 pagine `Fumetto e animazione` mai raccolte (serie animate, manga+anime) lette dal dump → `harvest_animation.jsonl.gz` (sha256 72d08d19…); infobox multipli valutati tutti |
| S2 | `enrich_wikidata.py` | 33.314 titoli → 32.412 entità, 902 senza; `--offline` ricrea i file byte per byte (0 richieste) |
| S3 | `build_relations.py` | stagioni/liste → serie con `torna a` + titolo + Wikidata (P179/P1545); 57 discordanze (27 padri: 22 per regola, 5 a mano; 30 numeri di stagione: titolo vince, P1545 spesso assoluto) |
| S4 | `audit_series.py` | accordo infobox↔P31, duplicati, campione stratificato (191 righe, seme fisso) rilette |
| S4b | `review_rules.py` | regole riproducibili U1/U2/U3/D1 + M1 manuale → `review/overrides.json` |
| S5 | `build_clean.py` | catalogo pulito + manifest + `verify` byte per byte; `check_catalog.py` 24 controlli |
| S6 | `embedding_units.py` | unità di testo, token (tiktoken), costo; stato `pending`, nessun embedding |

**Revisione (`review/overrides.json`, 5 relazioni · 48 esclusioni · 32 riclassificazioni · 49 bandiere)**: U1 23 film TV incerti → `tv_movie`; U2 37 programmi con classe Wikidata solo «radio program» → esclusi (+11 radio a mano); U3 9 programmi con classe di serie → serie; D1 47 miniserie che Wikidata dà come film → solo bandiera `possible_tv_movie` (un primo tentativo avrebbe spostato 145 miniserie, ma i loro testi le chiamano «miniserie/puntata»: due fonti in disaccordo = prove insufficienti); M1 2 bandiere mixed_media. Ogni voce conserva classificazione originale e motivo; togliere la voce e ricostruire ripristina il risultato automatico.
**Perché `uncertain` era 372 e non 40**: 372 = 332 programmi con genere ambiguo + 40 film TV incerti (i «40» dell'analisi film TV); ora 303.
**Ancora incerti/non forzati**: 212 programmi con classe «television program», sketch/special/short, docudrama con classe film generica, ~500 `class_check` discordi (solo bandiera), 47 `possible_tv_movie`.

## 5. Decisioni architetturali e motivazioni (approvate dal proprietario, 2026-11-05)
1. **Tipi inclusi**: serie TV, animate, anime, dorama, miniserie. **Programmi TV** solo con struttura episodica/genere narrativo; esclusioni documentate (3.960 non episodici).
2. **Una sola collezione gerarchica** (`series`/`season`/`episode` + `tv_movie`) con `entity_type`; ricerca **sempre filtrata per livello**; la ricerca mista va valutata a parte e **non è mai predefinita**. Motivo: con filtro di payload una collezione unica equivale a tre separate; il proxy lessicale (TF-IDF, 101.290 unità, 500 query/livello) mostra che senza filtro i livelli si mescolano (cercando una serie il 37% dei top-10 sono episodi; cercando un episodio per nome il 42% sono stagioni) e che il filtro recupera fino a +16 punti hit@1. [V come proxy lessicale; l'interferenza densa NON è misurata.]
3. **Vettori solo per testi utilizzabili** (episodi con trama ≥150 caratteri; serie/film TV con trama ≥400 car/60 parole o, come tipo distinto `lead`, introduzione ≥400 car; stagioni con introduzione propria ≥150 car). Il resto resta metadati.
4. **Stagioni senza pagina** = nodi logici collegati alla serie, nessun testo inventato, nessun vettore.
5. **Episodi** embeddati con prefisso di contesto «Serie – stagione N – episodio M – titolo» (il prefisso migliora +6/+8 punti nel proxy lessicale).
6. **Relazioni**: `{{torna a}}` + titolo + Wikidata; numero di stagione = quello del titolo; mai numerazione posizionale.
7. **Film TV** categoria autonoma: non contaminano le ricerche di serie (filtro `entity_type`, `default_search_eligible`); recuperabili se la richiesta li chiede.
8. **Serie miste manga/anime** tenute, con flag e `default_search_eligible = false`. Comportamento del futuro retriever [P]: (a) ricerca anime predefinita filtra `default_search_eligible = true`; (b) le miste si restituiscono solo se la richiesta parla di manga/franchise/adattamenti o se la ricerca per titolo esatto non trova altro, con avviso «pagina su manga e anime»; (c) `tv_movie` fuori dalle ricerche di serie salvo richiesta esplicita; (d) `ids_reliable = false` → non usare IMDb/TMDb di quel record per identificare l'opera; (e) `possible_tv_movie`/`uncertain` mai trattati come certezze; mostrare sempre la provenienza.
9. **Wikidata** via API/SPARQL con snapshot proprio (non il dump completo): gratuito, riprendibile, verificabile offline.
10. **Correzioni reversibili** in `review/overrides.json`, mai nei dati originali; `data/s1`–`s4` rigenerabili, `data/phase0` e snapshot sono le sorgenti.
11. Id Wikidata delle classi non scritti a memoria: verificati (`Q5398426` serie TV, `Q1259759` miniserie, `Q63952888` serie anime, `Q117467246` serie animata, `Q15416` programma TV, `Q3464665` stagione, `Q21191270` episodio, `Q506240` film TV, `Q98701476` film TV in due parti).

## 6. Misure di Fase 0 rimaste utili [V]
- Dump: 3.130.148 pagine ns 0; 125.913 con segnali. `{{FictionTV}}` 12.942 (serie TV 7.439, miniserie 1.894, serial 675, webserie 123, **film TV 2.694**); `{{Fumetto e animazione}}` 9.063; `{{Programma}}` 4.696. Le categorie nel wikitext sono incomplete: l'infobox è il segnale più forte.
- Stagioni: 10.857 pagine «Episodi di X (n-esima stagione)» (`torna a` in 10.802); altre ≈2.150 «Episodi di X» senza numero. Episodi quasi mai su pagine proprie (106 con `{{Episodio SerieTV}}`): vivono nelle pagine di stagione (tabella + sezioni di trama).
- Concordanza infobox↔Wikidata (campione 370): «miniserie tv» → miniserie solo 22/40 (uso incoerente); «film tv» → film TV 30/40.
- 13,5% delle serie FictionTV ha lo stesso titolo base di un film del catalogo v3; 885 film TV sono già nel catalogo film v3 (nessuna modifica fatta: il RAG film non si tocca); 58 pagine del catalogo v3 hanno un'infobox di serie (solo osservazione).
- Controllo sui 181 «serie» escluse dal catalogo film: la regola infobox ne riconosce 105/118 (esclusi i 63 manga).

## 7. Test e verifiche eseguiti (ultima esecuzione: sessione di chiusura, vedi §9)
- `python -m pytest pipelines/wikipedia_series/tests -q` → **58 passed** [V].
- `pipelines/wikipedia_films` test interni → **105 passed**; suite app (comando di `AGENTS.md` §4) → **2091 passed** [V].
- `python -m pipelines.wikipedia_series.build_clean verify` → «VERIFY OK: byte-identical rebuild» [V].
- `python -m pipelines.wikipedia_series.check_catalog` → 24 controlli, nessun fallimento [V] (id unici, ogni pagina S1 in S5, relazioni padre-figlio che risolvono, film TV senza padri, provenienza, coerenza mixed_media↔catalog_class↔default_search_eligible, riclassificati con originale).
- `python -m pipelines.wikipedia_films.audit.build_v3 verify` e `…indexing.v3 check` → OK; collezioni Qdrant `netflix_scout`, `wikipedia_films_it`, `_v2`, `_v3` intatte [V].
- `enrich_wikidata --offline` ricrea i file S2 byte per byte, 0 richieste [V].

## 8. Da fare, nell'ordine, e autorizzazioni
**Aggiornamento 2026-11-08**: i punti 2, 3, 4 e 5 qui sotto sono FATTI (§0). Restano: (a) **decisione del proprietario sulla visibilità delle pagine miste manga/anime** (§0 e `EVAL_REPORT.md` §2: nascoste per descrizione, h@10 0,00 sui 35 bersagli non idonei); (b) il punto 6 (registrazione come tool dell'agente: pacchetto `tool/<nome>/` con `Tool` Protocol, `SOURCE_TOOLS`, regole di routing contro `tvmaze_search`/`tmdb_search`, presenter e serializer web, guardia `content_type`, `catalog_enricher` no; **non iniziata**, serve richiesta esplicita); (c) i test reali complessivi, dopo i quali (fase successiva) si decide la cancellazione del vecchio RAG. Il testo che segue è lo storico della pianificazione.
**Già autorizzato dal proprietario in passato, ancora valido**: lavoro offline e gratuito su questo progetto; commit solo su richiesta esplicita (questa sessione: autorizzati i commit di chiusura, §9).
**Richiede crediti OpenAI E consenso esplicito del proprietario prima di partire**:
1. (facoltativo, offline) rivedere `uncertain`/`class_check` aggiungendo voci a `review/overrides.json`, poi ricostruire (ordine in §10).
2. **Embedding** delle 101.706 unità di `data/s6/units.jsonl.gz` con `text-embedding-3-large`, 1536 dimensioni [S: 36.676.728 token, **≈ 4,77 USD** a 0,13 USD/M; episodi 78.705 = 3,83 $, serie 11.478 = 0,68 $, stagioni 9.971 = 0,16 $, film TV 1.552 = 0,10 $; 28 unità tagliate a 7.800 token con flag `truncated`]. Token misurati con tiktoken `cl100k_base` (stesso conteggio del modello). Riuso del metodo dei film: shard `.npz` atomici e riprendibili, riuso dei vettori per hash del testo (`text_sha256`). Rieseguire prima `build_clean verify` ed `embedding_units`.
3. **Benchmark densi** (interferenza tra livelli, effetto del prefisso, filtri, ricerca mista con raggruppamento per serie): finora solo proxy lessicale. Decide anche se l'indice unico regge o se servono due/tre collezioni [P].
4. **Collezione Qdrant NUOVA** `wikipedia_series_it_v1` (namespace uuid5 diverso da quello dei film; barriere non distruttive: mai scrivere le collezioni dei film; stima 1,2–2 GB [S]); payload con `entity_type`, `series_id`, `season_id`, `season_number`, `episode_number`, `default_search_eligible`, `catalog_class`, `ids_reliable`, `text_kind`, indici di payload e full-text come nella v3 dei film [P].
5. Retriever sperimentale, valutazione con giudice cieco (~1–3 $ [S]) — batteria di domande per livello, vincoli, esclusioni, navigazione padre↔figlio, non regressione del RAG film.
6. **Registrazione come tool dell'agente: decisione separata**, con aggancio alle impostazioni utente (skill §2f, `SOURCE_TOOLS`), regole di routing rispetto a `tvmaze_search`/`tmdb_search` e a `content_type=series`. Non iniziare senza esplicita richiesta.
**Vincoli sempre validi**: non cambiare comportamento/collezioni del RAG film; non integrare in agente, frontend, orchestratore senza richiesta; non cancellare dati originali (dump, snapshot, `data/phase0`); nessuna chiamata a pagamento né embedding senza consenso; nessun `git clean`/reset/amend.

**Punto di ripartenza storico (SUPERATO il 2026-11-08, vedi §0)**: (1) `python -m pipelines.wikipedia_series.build_clean verify` deve dire VERIFY OK; (2) chiedere il consenso al proprietario sul costo (≈ 4,77 $); (3) scrivere il modulo di embedding con shard riprendibili partendo da `data/s6/units.jsonl.gz` (non esiste ancora: [P]); (4) poi indicizzazione in una collezione nuova.

## 9. Stato Git
Prima della sessione di chiusura nulla era committato per questi progetti (HEAD `28889cc`). Commit creati nella sessione di chiusura (autorizzati dal proprietario): Il `.gitignore` radice ha una sezione «RAGWikipedia* pipelines» (cache `eval/cache/`, `eval/results/*retrieval.jsonl`, cache di pytest/mypy/ruff, `*.part`).

| Commit | Contenuto |
|---|---|
| `bf06cbc` | `pipelines/wikipedia_films/` (progetto dati film, 170 file) + sezione «RAGWikipedia* pipelines» di `.gitignore` |
| `df6a862` | integrazione app del film index e precedenza delle impostazioni (lavoro preesistente, committato a parte): `film_index/`, `preferences/policy.py`, `app.py`, `orchestrator.py`, `turn.py`, enrichment TMDb per IMDb id, relativi test |
| `58b2862` | `pipelines/wikipedia_series/` (codice, test, config, `reports/`, `review/overrides.json`, questo file) |
| `33284a6` | `AGENTS.md`, `README.md`, `mappa.html` |
| (ultimo) | questo file con la tabella dei commit |
Dopo questi commit `git status` deve essere pulito; i dati restano in `data/` (ignorato).

## 10. Comandi esatti (dalla radice, con `source .venv/bin/activate`)
Verifica (offline, gratuita):
```bash
python -m pipelines.wikipedia_series.build_clean verify       # VERIFY OK: byte-identical rebuild
python -m pipelines.wikipedia_series.check_catalog            # 24 controlli
python -m pytest pipelines/wikipedia_series/tests -q          # 58 passed
python -m pipelines.wikipedia_series.enrich_wikidata --offline --out /percorso/temporaneo   # S2 da snapshot, 0 richieste
```
Ricostruzione completa (nessuna a pagamento; S1b e S2 usano rete gratuita se manca lo snapshot):
```bash
python -m pipelines.wikipedia_series.phase0.scan_dump         # ~64 min -> data/phase0/full/scan_*.jsonl
python -m pipelines.wikipedia_series.phase0.harvest           # ~20 min, wikitext delle pagine selezionate
python -m pipelines.wikipedia_series.harvest_animation        # S1b ~20 min
python -m pipelines.wikipedia_series.extract_series           # S1 ~12 min
python -m pipelines.wikipedia_series.enrich_wikidata          # S2 ~17 min (snapshot riprendibile)
python -m pipelines.wikipedia_series.build_relations          # S3 (legge review/overrides.json)
python -m pipelines.wikipedia_series.audit_series             # S4 (non scrive mai gli override)
python -m pipelines.wikipedia_series.build_clean build        # S5
python -m pipelines.wikipedia_series.check_catalog
python -m pipelines.wikipedia_series.build_clean verify
python -m pipelines.wikipedia_series.embedding_units          # S6: unità, token, costo; NESSUN embedding
python -m pipelines.wikipedia_series.publish_reports          # copia i report sintetici in reports/
```
Altri: `python -m pipelines.wikipedia_series.review_rules [--dry-run]` (rigenera le regole U1/U2/U3/D1 in `review/overrides.json`, solo le proprie), `python -m pipelines.wikipedia_series.phase0.analyze_tv_movies`. **Dopo una modifica a `review/overrides.json`**: `build_relations` → `audit_series` → `build_clean build` → `check_catalog` → `build_clean verify` → `embedding_units` → `publish_reports`.

## 11. File importanti
- Codice: `extract_series.py`, `harvest_animation.py`, `enrich_wikidata.py`, `build_relations.py`, `audit_series.py`, `review_rules.py`, `build_clean.py`, `check_catalog.py`, `embedding_units.py`, `publish_reports.py`, `tv_movies.py`; copie generiche `common.py`, `config.py`, `config.yaml`, `dump.py`, `clean_plot.py`, `wikidata_client.py`; `phase0/*` (scan, harvest, analisi, proxy lessicale, sonde Wikidata); `tests/`.
- Versionati: `review/overrides.json`, `reports/*.json` (17 file: manifest e report di ogni fase, incl. `s5_manifest.json`, `s5_coherence.json`, `s6_embedding_manifest.json`).
- Dati (ignorati, 1,2 GB; disco libero ≈262 GiB): `data/phase0` 408 MB (scan/harvest), `data/s1` 242 MB, `data/s2` 13 MB, `data/s3` 27 MB, `data/s4` 0,4 MB, `data/s5` 283 MB, `data/s6` 49 MB (`units.jsonl.gz` sha256 `de8dc508ba2ce3ae…`, `embedding_manifest.json` status `pending`), `data/cache/wikidata` 188 MB. Gli input S1: `harvest.jsonl.gz` sha256 `3309fc6c22585155…`, `harvest_animation.jsonl.gz` `72d08d199df27236…`. S1 `series.jsonl` `1b38db5d…`. **Sorgenti da conservare** (l'offline dipende da loro): dump, `data/phase0/full/harvest*.jsonl.gz`, snapshot Wikidata.
- Spazio previsto per i passi successivi [S]: vettori 101.706 × 1536 float32 ≈ 0,6 GB; collezione Qdrant ≈ 1,2–2 GB.

## 12. Limiti noti e non verificato
Nessuna rilettura integrale: la qualità è controllata su campioni (191 righe) e su controlli di coerenza. Righe di tabella con `rowspan` trattate in modo prudente (`partial`, mai allineate a indovinare). Comportamento di un indice denso (interferenza tra livelli, effetto del prefisso, ricerca mista) **non misurato**. Il flag `mixed_media` non garantisce che il testo parli del manga. Pagine con infobox di serie nel catalogo film v3 (58) solo osservate. Costo reale degli embedding da confermare alla prima esecuzione (stima su token misurati ma prezzo e modello da riverificare).
