# RAGWikipediaSeries — PROGRESS (documento di ripresa)

Aprire una sessione nuova, leggere `AGENTS.md` e questo file: bastano per ripartire dalla **preparazione degli embedding**.
Ultimo aggiornamento: 2026-11-05. HEAD all'inizio di questa sessione: `28889cc`. Per i commit creati vedi §9.

Legenda: **[V]** verificato (con il comando indicato) · **[S]** stima · **[P]** solo progettato, non fatto.

## 1. Stato in una riga
Il **dataset pulito è pronto e verificato** [V] (`build_clean verify` → «VERIFY OK: byte-identical rebuild»; 24 controlli di coerenza; 58 test). **Non esistono** (tutto [P]): embedding, collezione Qdrant `wikipedia_series_it_v1`, retriever, valutazione densa, tool dell'agente. Nessuna chiamata a pagamento è stata fatta. Il saldo OpenAI era esaurito; il prossimo passo richiede crediti **e** il consenso del proprietario (§8).

## 2. Architettura e separazione dai film
- `tool/RAGWikipediaFilm/` (rinominato da `tool/RAGWikipedia`, solo percorsi/import) = dati, audit e valutazione del RAG film. A runtime l'app usa **solo** `tool/rag/FromQueryEmbeddingToRes/film_index/` (retriever attivo, collezione `wikipedia_films_it_v3`, 41.138 film). Il RAG film non è stato modificato dal lavoro sulle serie [V: regressione identica byte per byte, vedi §7].
- `tool/RAGWikipediaSeries/` (questo progetto) = pipeline dati indipendente. **Nessun import da `tool/RAGWikipediaFilm`** (`tests/test_tool_package.py`): i moduli generici (`dump.py`, `clean_plot.py`, `wikidata_client.py`, `config.py`) sono copie. Si condivide solo il FILE del dump per percorso (`common.DUMP_PATH` = `tool/RAGWikipediaFilm/data/raw/itwiki-20261101-pages-articles.xml.bz2`, 4.286.436.387 byte, SHA-1 `53d757d92a4f3956880586074008f08a08760641`, sola lettura).
- Non è registrato nell'agente: nessun riferimento in `app.py`, `orchestrator.py`, `web_api`, `presenters`, `preferences`, `tool/rag` [V]. La regola `content_type=series` e `tvmaze_search`/`tmdb_search` restano invariate.
- Cache Wikidata propria: `data/cache/wikidata/itwiki-20261101-series-a` (188 MB, append-only). User-Agent con URL del repository, senza e-mail personali (`config.yaml`).
- Git: `data/` è ignorato (`tool/RAGWikipediaSeries/.gitignore:2`, `tool/RAGWikipediaFilm/.gitignore:2`, `.gitignore:74`). Versionati: codice, test, `config.yaml`, `PROGRESS.md`, `reports/*.json` (manifest e report sintetici) e `review/overrides.json` (decisioni: NON in `data/`).

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
| R | rinomina | `tool/RAGWikipedia`→`RAGWikipediaFilm`; 2091 test app, 105 film, `build_v3 verify`/`indexing.v3 check` identici prima/dopo |
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
- `python -m pytest tool/RAGWikipediaSeries/tests -q` → **58 passed** [V].
- `tool/RAGWikipediaFilm` test interni → **105 passed**; suite app (comando di `AGENTS.md` §4) → **2091 passed** [V].
- `python -m tool.RAGWikipediaSeries.build_clean verify` → «VERIFY OK: byte-identical rebuild» [V].
- `python -m tool.RAGWikipediaSeries.check_catalog` → 24 controlli, nessun fallimento [V] (id unici, ogni pagina S1 in S5, relazioni padre-figlio che risolvono, film TV senza padri, provenienza, coerenza mixed_media↔catalog_class↔default_search_eligible, riclassificati con originale).
- `python -m tool.RAGWikipediaFilm.audit.build_v3 verify` e `…indexing.v3 check` → OK; collezioni Qdrant `netflix_scout`, `wikipedia_films_it`, `_v2`, `_v3` intatte [V].
- `enrich_wikidata --offline` ricrea i file S2 byte per byte, 0 richieste [V].

## 8. Da fare, nell'ordine, e autorizzazioni
**Già autorizzato dal proprietario in passato, ancora valido**: lavoro offline e gratuito su questo progetto; commit solo su richiesta esplicita (questa sessione: autorizzati i commit di chiusura, §9).
**Richiede crediti OpenAI E consenso esplicito del proprietario prima di partire**:
1. (facoltativo, offline) rivedere `uncertain`/`class_check` aggiungendo voci a `review/overrides.json`, poi ricostruire (ordine in §10).
2. **Embedding** delle 101.706 unità di `data/s6/units.jsonl.gz` con `text-embedding-3-large`, 1536 dimensioni [S: 36.676.728 token, **≈ 4,77 USD** a 0,13 USD/M; episodi 78.705 = 3,83 $, serie 11.478 = 0,68 $, stagioni 9.971 = 0,16 $, film TV 1.552 = 0,10 $; 28 unità tagliate a 7.800 token con flag `truncated`]. Token misurati con tiktoken `cl100k_base` (stesso conteggio del modello). Riuso del metodo dei film: shard `.npz` atomici e riprendibili, riuso dei vettori per hash del testo (`text_sha256`). Rieseguire prima `build_clean verify` ed `embedding_units`.
3. **Benchmark densi** (interferenza tra livelli, effetto del prefisso, filtri, ricerca mista con raggruppamento per serie): finora solo proxy lessicale. Decide anche se l'indice unico regge o se servono due/tre collezioni [P].
4. **Collezione Qdrant NUOVA** `wikipedia_series_it_v1` (namespace uuid5 diverso da quello dei film; barriere non distruttive: mai scrivere le collezioni dei film; stima 1,2–2 GB [S]); payload con `entity_type`, `series_id`, `season_id`, `season_number`, `episode_number`, `default_search_eligible`, `catalog_class`, `ids_reliable`, `text_kind`, indici di payload e full-text come nella v3 dei film [P].
5. Retriever sperimentale, valutazione con giudice cieco (~1–3 $ [S]) — batteria di domande per livello, vincoli, esclusioni, navigazione padre↔figlio, non regressione del RAG film.
6. **Registrazione come tool dell'agente: decisione separata**, con aggancio alle impostazioni utente (skill §2f, `SOURCE_TOOLS`), regole di routing rispetto a `tvmaze_search`/`tmdb_search` e a `content_type=series`. Non iniziare senza esplicita richiesta.
**Vincoli sempre validi**: non cambiare comportamento/collezioni del RAG film; non integrare in agente, frontend, orchestratore senza richiesta; non cancellare dati originali (dump, snapshot, `data/phase0`); nessuna chiamata a pagamento né embedding senza consenso; nessun `git clean`/reset/amend.

**Punto esatto da cui ripartire (quando ci sono crediti)**: (1) `python -m tool.RAGWikipediaSeries.build_clean verify` deve dire VERIFY OK; (2) chiedere il consenso al proprietario sul costo (≈ 4,77 $); (3) scrivere il modulo di embedding con shard riprendibili partendo da `data/s6/units.jsonl.gz` (non esiste ancora: [P]); (4) poi indicizzazione in una collezione nuova.

## 9. Stato Git
Prima della sessione di chiusura nulla era committato per questi progetti (HEAD `28889cc`). Commit creati nella sessione di chiusura (autorizzati dal proprietario): Il `.gitignore` radice ha una sezione «RAGWikipedia* pipelines» (cache `eval/cache/`, `eval/results/*retrieval.jsonl`, cache di pytest/mypy/ruff, `*.part`).

| Commit | Contenuto |
|---|---|
| `bf06cbc` | `tool/RAGWikipediaFilm/` (progetto dati film, 170 file) + sezione «RAGWikipedia* pipelines» di `.gitignore` |
| `df6a862` | integrazione app del film index e precedenza delle impostazioni (lavoro preesistente, committato a parte): `film_index/`, `preferences/policy.py`, `app.py`, `orchestrator.py`, `turn.py`, enrichment TMDb per IMDb id, relativi test |
| `58b2862` | `tool/RAGWikipediaSeries/` (codice, test, config, `reports/`, `review/overrides.json`, questo file) |
| `33284a6` | `AGENTS.md`, `README.md`, `mappa.html` |
| (ultimo) | questo file con la tabella dei commit |
Dopo questi commit `git status` deve essere pulito; i dati restano in `data/` (ignorato).

## 10. Comandi esatti (dalla radice, con `source .venv/bin/activate`)
Verifica (offline, gratuita):
```bash
python -m tool.RAGWikipediaSeries.build_clean verify       # VERIFY OK: byte-identical rebuild
python -m tool.RAGWikipediaSeries.check_catalog            # 24 controlli
python -m pytest tool/RAGWikipediaSeries/tests -q          # 58 passed
python -m tool.RAGWikipediaSeries.enrich_wikidata --offline --out /percorso/temporaneo   # S2 da snapshot, 0 richieste
```
Ricostruzione completa (nessuna a pagamento; S1b e S2 usano rete gratuita se manca lo snapshot):
```bash
python -m tool.RAGWikipediaSeries.phase0.scan_dump         # ~64 min -> data/phase0/full/scan_*.jsonl
python -m tool.RAGWikipediaSeries.phase0.harvest           # ~20 min, wikitext delle pagine selezionate
python -m tool.RAGWikipediaSeries.harvest_animation        # S1b ~20 min
python -m tool.RAGWikipediaSeries.extract_series           # S1 ~12 min
python -m tool.RAGWikipediaSeries.enrich_wikidata          # S2 ~17 min (snapshot riprendibile)
python -m tool.RAGWikipediaSeries.build_relations          # S3 (legge review/overrides.json)
python -m tool.RAGWikipediaSeries.audit_series             # S4 (non scrive mai gli override)
python -m tool.RAGWikipediaSeries.build_clean build        # S5
python -m tool.RAGWikipediaSeries.check_catalog
python -m tool.RAGWikipediaSeries.build_clean verify
python -m tool.RAGWikipediaSeries.embedding_units          # S6: unità, token, costo; NESSUN embedding
python -m tool.RAGWikipediaSeries.publish_reports          # copia i report sintetici in reports/
```
Altri: `python -m tool.RAGWikipediaSeries.review_rules [--dry-run]` (rigenera le regole U1/U2/U3/D1 in `review/overrides.json`, solo le proprie), `python -m tool.RAGWikipediaSeries.phase0.analyze_tv_movies`. **Dopo una modifica a `review/overrides.json`**: `build_relations` → `audit_series` → `build_clean build` → `check_catalog` → `build_clean verify` → `embedding_units` → `publish_reports`.

## 11. File importanti
- Codice: `extract_series.py`, `harvest_animation.py`, `enrich_wikidata.py`, `build_relations.py`, `audit_series.py`, `review_rules.py`, `build_clean.py`, `check_catalog.py`, `embedding_units.py`, `publish_reports.py`, `tv_movies.py`; copie generiche `common.py`, `config.py`, `config.yaml`, `dump.py`, `clean_plot.py`, `wikidata_client.py`; `phase0/*` (scan, harvest, analisi, proxy lessicale, sonde Wikidata); `tests/`.
- Versionati: `review/overrides.json`, `reports/*.json` (17 file: manifest e report di ogni fase, incl. `s5_manifest.json`, `s5_coherence.json`, `s6_embedding_manifest.json`).
- Dati (ignorati, 1,2 GB; disco libero ≈262 GiB): `data/phase0` 408 MB (scan/harvest), `data/s1` 242 MB, `data/s2` 13 MB, `data/s3` 27 MB, `data/s4` 0,4 MB, `data/s5` 283 MB, `data/s6` 49 MB (`units.jsonl.gz` sha256 `de8dc508ba2ce3ae…`, `embedding_manifest.json` status `pending`), `data/cache/wikidata` 188 MB. Gli input S1: `harvest.jsonl.gz` sha256 `3309fc6c22585155…`, `harvest_animation.jsonl.gz` `72d08d199df27236…`. S1 `series.jsonl` `1b38db5d…`. **Sorgenti da conservare** (l'offline dipende da loro): dump, `data/phase0/full/harvest*.jsonl.gz`, snapshot Wikidata.
- Spazio previsto per i passi successivi [S]: vettori 101.706 × 1536 float32 ≈ 0,6 GB; collezione Qdrant ≈ 1,2–2 GB.

## 12. Limiti noti e non verificato
Nessuna rilettura integrale: la qualità è controllata su campioni (191 righe) e su controlli di coerenza. Righe di tabella con `rowspan` trattate in modo prudente (`partial`, mai allineate a indovinare). Comportamento di un indice denso (interferenza tra livelli, effetto del prefisso, ricerca mista) **non misurato**. Il flag `mixed_media` non garantisce che il testo parli del manga. Pagine con infobox di serie nel catalogo film v3 (58) solo osservate. Costo reale degli embedding da confermare alla prima esecuzione (stima su token misurati ma prezzo e modello da riverificare).
