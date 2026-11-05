# Piano tecnico: database cinematografico locale + tool SQL read-only

Stato: piano approvato il 2026-11-05; implementazione per fasi. **Punto di ripresa e stato autorevole: `docs/cinema_db/PROGRESS.md`.** Le decisioni D1–D7 sono registrate in fondo (§15).
Legenda: **[V]** verificato sul codice/sui file locali o su una pagina ufficiale letta oggi · **[S]** stima · **[P]** proposta · **[?]** da verificare prima di costruire.

---------------------------------------------------------------------------------------------------

## 1. Analisi dell'architettura attuale (dal codice)

### 1.1 Cosa dà ogni tool [V]
| Tool | Dati | Costo tipico per turno | Note dal codice |
|---|---|---|---|
| `rag_search` (film index) | 41.138 film: titolo, originale, anno, regia, cast+personaggi, durata, paesi, lingue, generi, trama it, `imdb_id`, `wikidata_id`, `wikipedia_url`, franchise | embedding + parser LLM + riordino LLM (~3 s) + 1 `/find` TMDb per film restituito (locandina) | già restituisce i metadati strutturati: il planner non deve richiamare TMDb per quelli |
| `movie_db_search` | MovieLens 32M: voto medio, n. voti, generi, tag, anno (fino al 2022); 6 operazioni fisse | 1 chiamata LLM di parsing + SQL locale + fino a 12 `/find` TMDb (`work_type_checker`) per scartare le serie | il parser LLM è necessario perché il modello non scrive SQL |
| `tmdb_search` | uscite, cast completo, streaming, trailer, trending, discover, serie, persone, collezioni, voto del pubblico TMDb | budget 10 chiamate/turno; 17 operazioni | è il tool più generico: copre anche dati che stanno già nel RAG o in Wikidata |
| `wikipedia_search` | prosa enciclopedica (storia, produzione, differenze con il romanzo) | fino a 6 chiamate; articolo intero in cache 1 h | unico per la prosa; non va sostituito |
| `youtube_search` | video (interviste, making-of) | max 2 `search.list`/turno, quota 100/giorno | non sostituibile |
| `omdb_search` | Metascore, Rotten Tomatoes, voto IMDb | 1–2 richieste per titolo, 10/turno, 1.000/giorno | nessuna cache per licenza |
| `tvmaze_search` | stato, rete, stagioni, episodi, prossimo episodio di UNA serie | 1–4 richieste | dati vivi (prossimo episodio): non copiabili |
| `wikidata_search` | `resolve` (omonimi) e `relations` (fonte, remake, precedente/successiva, franchise) | 1–3 richieste SPARQL per identificare + 1 per le relazioni + 1 per i membri del franchise; query fino a 15 s | **è già una "vista online" di ciò che il nuovo DB conterrebbe**: le sue risposte sono tutte derivabili dal grafo locale |

### 1.2 Sovrapposizioni e ridondanze [V dal codice, tranne dove indicato]
1. **Identificazione di un titolo**: oggi la fa ogni tool per conto suo — TMDb `search`, OMDb `s=` + `i=` (2 richieste), TVmaze `/search/shows`, Wikidata `label_request` (1 SPARQL, fino a 3 con il ripiego di testo), Wikipedia `generator=search`. Per un singolo turno "dimmi il voto della critica di X e i film da cui è tratto" si possono avere **5–7 richieste di sola identificazione** prima del primo dato utile. Il DB locale risolve titolo → `film_id`/QID/IMDb/TMDb in 0 richieste.
2. **Il planner non conosce gli ID**: OMDb e Wikidata accettano `imdb_id`/`tmdb_id` solo se compaiono "nella richiesta, nella conversazione o in un passo già fatto" (regole 1d/1f). Quindi, a titolo non noto, si paga l'identificazione per titolo anche quando il RAG o il DB sa già l'ID.
3. **Dati strutturati duplicati TMDb ↔ RAG ↔ Wikidata**: regia, cast, durata, paesi, generi, anno sono in RAG (payload), in TMDb `movie_details` e in Wikidata. Il RAG già vieta il richiamo a TMDb per questi (regola 3), ma per film **fuori dal RAG** (dopo il 2019 incompleto, serie) il planner ripiega su TMDb.
4. **Relazioni tra opere**: `wikidata_search relations` (online, 2–5 richieste SPARQL, fino a 15 s di timeout) vs `movie_collection`/`collection_details` TMDb vs `franchise_id` del RAG (solo 4.049 film, 10%). Tre fonti parziali per la stessa domanda.
5. **Classifiche e filmografie**: `discover_movies` (TMDb, voto del pubblico TMDb) vs `movie_db_search` (voto MovieLens, fermo al 2022) vs nessuna fonte per "film di regista X ordinati per anno" locale (oggi: TMDb discover con `people`, 1 risoluzione persona + 1 discover).
6. **Chiamate sequenziali**: il ciclo di `LLMOrchestrator.run` (`orchestrator.py` ~l.1018–1110) è **strettamente seriale**: un `tool.run` alla volta, con una chiamata LLM di `_plan_next` tra un passo e l'altro. Non esiste parallelismo ([V]: nessun `ThreadPool`/`asyncio` in `orchestrator.py`, `app.py`, `tool/*/tool.py`). Ogni passo in più costa 1 chiamata di pianificazione (~1–3 s [S]) più la latenza del tool.
7. **Tool scartati/inutili** [S, da misurare]: non ci sono log aggregati nel repository; i numeri vanno ricavati dalle trace (vedi §8, misura di base). Dalle regole: `movie_db_search` viene scelto per domande di classifica ma costa un parser LLM per 6 operazioni fisse; `wikidata_search resolve` serve di rado (solo omonimi esplicitamente chiesti); `tmdb_search` viene chiamato "per sicurezza" dopo il RAG nonostante la regola 3 (rischio da misurare, non provato).

### 1.3 Cosa si può recuperare localmente [V sui file]
- **`tool/RAGWikipediaFilm/data/clean_v3/films.v3.jsonl`** (143 MB): 41.138 film; QID 99,9 %, IMDb 99,2 %, regia 98,7 %, cast 90,7 %, durata 91,7 %, paesi 99,9 %, generi 99,4 %; `actors[]` e `director[]` con QID delle persone; `work_format`, `franchise_*`.
- **Snapshot Wikidata originale** `tool/RAGWikipediaFilm/data/cache/wikidata/itwiki-20261101-a` (344 MB, 829 blocchi gzip, indice `requests.jsonl`) e `tool/RAGWikipediaSeries/data/cache/wikidata/...` (188 MB). **Verificato su 40 blocchi (721 entità)**: contengono i *claims* completi, non solo quelli usati finora: `P166` premio ricevuto (44/721 entità), `P1411` candidature (71), `P2142` incasso (66), `P2130` budget (74), `P58` sceneggiatore (522), `P86` compositore (460), `P162` produttore (397), `P344` direttore della fotografia (384), `P1040` montatore (314), `P272` produzione, `P161` cast, `P136`, `P495`, `P577`. → i dati di nodi/relazioni film **si possono ricostruire offline, a rete bloccata, dallo snapshot già scaricato** (come fanno già `enrich_metadata.py --offline`), con 0 richieste.
- **Dump itwiki 20261101** (4,29 GB, SHA-1 `53d757d9…`, già scaricato, condiviso per percorso): fonte di prosa, infobox (incassi, budget, date di uscita per paese, produttori) e liste.
- **Catalogo serie `data/s5/`** (283 MB): 15.697 serie, 15.032 stagioni (4.175 logiche), 78.705 episodi con trama, 147.249 righe episodio senza trama, 2.578 film TV; relazioni padre-figlio verificate (`relation_status`).
- **MovieLens**: `links` (movie_id, imdb_id, tmdb_id) permette il join per `imdb_id` con il nuovo DB.
- **Non c'è** nessun dato locale su persone (data/luogo di nascita, professioni) né sui premi con i *qualificatori* (categoria, anno della cerimonia, vincitore vs candidato): servono i claims delle persone e le entità dei premi (poche migliaia di richieste, non un dump).

---------------------------------------------------------------------------------------------------

## 2. Architettura proposta

```
                     ┌────────────────────────────────────────────────────────────┐
 offline (riproducibile)                                                          │
  snapshot Wikidata già scaricato ──┐                                              │
  + richieste mirate (persone,      ├─> tool/cinema_db_build/  ─> cinema.sqlite3   │ (file nuovo, MAI MovieLens)
    premi, cerimonie, ~poche migl.) │      extract → normalize                     │
  + dump itwiki (infobox, liste)  ──┤      → resolve ids → dedup → import          │
  + catalogo film v3 / serie s5   ──┘      → integrity check → schema.html         │
                     └────────────────────────────────────────────────────────────┘
 runtime
  planner ─> cinema_sql (tool in-process)
               ├─ validator.py   parsing AST, una sola SELECT, whitelist
               ├─ policy.py      tabelle/viste/colonne/funzioni ammesse (dati, non codice)
               ├─ connection.py  mode=ro + immutable? + query_only + authorizer + limiti
               ├─ executor.py    esecuzione parametrizzata, righe/tempo
               ├─ formatter.py   risultato → chunks/metadata (con provenienza e licenza)
               └─ errors.py      errori tipizzati (mai il testo SQL dell'utente nei log del prompt)
  MovieLens (movie_db_search) invariato, file e tool intatti
```

Scelte:
- **Un file SQLite nuovo** `cinema_db/data/cinema.sqlite3` (cartella ignorata da git, come `movie_db/data/`). MovieLens resta un file e un tool separati: `ATTACH` è vietato, quindi il nuovo tool **non può** raggiungere MovieLens neppure per errore.
- **Pacchetti separati**: `tool/cinema_db/` (runtime, rispetta `tests/test_tool_package.py`: nessun import da altri domini né da presenter) e `cinema_db/` radice (database: `schema.py`, `config.py`, `harness/` offline per la costruzione; analogo a `movie_db/`). La costruzione non è mai importata a runtime.
- **Il modello scrive SQL** (a differenza di `movie_db_search`, dove SQL è costante): per questo la difesa è a più livelli (§5). In alternativa a SQL libero si può offrire anche un piccolo insieme di **viste** pre-costruite (`v_film`, `v_person_credit`, `v_award`, `v_relation`) su cui il modello scrive SELECT semplici: riduce errori e superficie. **[P: SQL libero ma ristretto alle viste.]**

### Cosa NON è nel DB (per non duplicare)
Voti e punteggi correnti (TMDb, OMDb), streaming, trailer, locandine, cast completo aggiornato, uscite recenti e trending (TMDb); episodi futuri e rete (TVmaze); video (YouTube); prosa lunga (Wikipedia, resta tool online + RAG). Trama: **nel DB solo il puntatore** (`wikipedia_url`, `source_revision_id`); le trame restano in Qdrant (nessuna doppia copia di 125 MB di testo).

---------------------------------------------------------------------------------------------------

## 3. Schema relazionale preliminare (SUPERATO: vedi §16 e `cinema_db/schema.py`, la fonte di verità)

Convenzioni: chiave primaria = **intero interno** (`*_id`), `qid` UNIQUE; ogni riga ha `source` e (dove ha senso) `source_revision`/`retrieved_at`. `PRAGMA foreign_keys=ON` in costruzione, `WITHOUT ROWID` solo dove utile.

**Nodi**
- `work(work_id PK, qid UNIQUE, kind CHECK IN ('film','tv_film','series','season','episode','short','miniseries'), title_it, title_en, original_title, year, release_date, runtime_min, status, work_format, imdb_id, tmdb_id, tvdb_id, wikipedia_it_url, wikipedia_en_url, source)`
- `person(person_id PK, qid UNIQUE, name, name_norm, birth_year, death_year, birth_country_id→country, imdb_nm, tmdb_id, wikipedia_it_url, source)`
- `genre(genre_id PK, qid, label_en, label_it)`, `country(country_id PK, qid, iso2, label)`, `language(language_id PK, qid, iso1, label)`, `company(company_id PK, qid, name, country_id)`
- `award(award_id PK, qid, name, kind)` (es. Oscar al miglior film) · `ceremony(ceremony_id PK, award_id→award, edition, year, date, qid)` · `franchise(franchise_id PK, qid, name)` (anche i `franchise_id` del RAG)
- `external_id(work_id|person_id, scheme, value)` per ID non elencati nei nodi (TVDB, Letterboxd…); UNIQUE(scheme, value)

**Relazioni (molti-a-molti)**
- `credit(credit_id PK, work_id→work, person_id→person, role CHECK IN ('director','writer','cast','composer','cinematographer','editor','producer','production_designer'), character, billing_order, source)` — INDEX (person_id, role), (work_id, role)
- `work_genre(work_id, genre_id)`, `work_country(work_id, country_id)`, `work_language(work_id, language_id)`, `work_company(work_id, company_id, role)`
- `work_relation(work_id, related_work_id|related_qid, relation CHECK IN ('based_on','derivative_of','follows','followed_by','part_of_series','franchise','remake_of','adaptation_of'), source)` — `related_qid` per opere non-film (romanzi, videogiochi, fumetti) che non meritano una riga in `work`; tabella `related_entity(qid PK, label, kind)`
- `work_franchise(work_id, franchise_id)`
- `season(season_id PK, series_work_id→work, number, year, episode_count)` ed `episode(episode_id PK, season_id, series_work_id, number, title, air_date)` — dal catalogo serie s5 (solo metadati; trame in Qdrant)
- `award_result(result_id PK, ceremony_id→ceremony, category TEXT, work_id→work NULL, person_id→person NULL, outcome CHECK IN ('won','nominated'), source, CHECK(work_id IS NOT NULL OR person_id IS NOT NULL))`
- `box_office(work_id, amount, currency, scope CHECK IN ('worldwide','domestic','country'), country_id NULL, as_of_year, source)` · `budget(work_id, amount, currency, source)` — attenzione: i valori Wikidata hanno qualificatori (P3005 luogo di validità, P585 data) e **valute diverse e anni diversi: nessuna conversione inflazionistica**, si espone `amount+currency+as_of_year` come sono.

**Provenienza (richiesta del §3)**
- `source(source_id PK, name, url, license, license_url, retrieved_at, snapshot_sha256, notes)`; ogni tabella di fatti ha `source_id→source` e, per i dati da Wikipedia, `revision_id`.
- `build_info(key, value)`: versione dello schema, hash dell'ingresso, data della costruzione.

**Viste pubbliche per l'agente** (la sola superficie interrogabile): `v_work`, `v_person`, `v_credit` (join già risolti: titolo + persona + ruolo), `v_award`, `v_relation`, `v_box_office`, `v_provenance`. Le tabelle base restano non interrogabili direttamente (whitelist sulle viste), così lo schema interno può evolvere senza rompere i prompt.

**Indici**: `work(imdb_id)`, `work(tmdb_id)`, `work(title_norm, year)`, `person(name_norm)`, `credit(person_id, role)`, `credit(work_id, role)`, `award_result(person_id)`, `award_result(work_id)`, `work_relation(work_id, relation)`; FTS5 su `work.title_*`, `person.name` **[?]** per ricerca per nome approssimata (FTS5 è compilata in SQLite 3.53.4 locale [V versione]; da verificare l'opzione di compilazione; la sua funzione `MATCH` va nella whitelist se si usa).

---------------------------------------------------------------------------------------------------

## 4. Fonti e licenze

| Fonte | Cosa si acquisisce | Come | Dimensione [S] | Licenza | Esito |
|---|---|---|---|---|---|
| **Snapshot Wikidata già locale** (film 344 MB + serie 188 MB) | claims di ~56.000 opere: ruoli (P57, P58, P161, P86, P344, P1040, P162), P136, P495, P364, P577, P272, P144/P4969/P155/P156/P179/P8345, P166/P1411, P2142, P2130, ID esterni | **offline, 0 richieste** | -- | CC0 (struttura) **[V: pagina Wikidata:Database download]** | **fonte primaria** |
| **Wikidata, richieste mirate** | entità persona (label, nascita/morte, ID) per tutti i QID in `credit` (~150–250 k [S]); entità premio/cerimonia (poche migliaia) | `wbgetentities` 50 id/richiesta ⇒ ~3–5 k richieste; o SPARQL a lotti | cache ~300–600 MB gz [S] | CC0 | **non un dump**; rispetta User-Agent e ritmo; richiede il tuo permesso (rete) |
| **Dump Wikidata completo** (`latest-all.json.gz`) | -- | -- | **130,5 GiB** (gz, 2024-01-01) **[V]**, in crescita | CC0 | **sconsigliato**: 130+ GB, ore di parsing, inutile per ~60 k opere |
| **WDQS** (endpoint SPARQL) | alternativa alle richieste per ID: estrazioni per classe/anno | SPARQL | -- | CC0 | limiti ufficiali **[V]**: 60 s di timeout, 60 s di CPU per 60 s per client, 5 query parallele per IP, 429 con `Retry-After`; un backend nuovo è previsto per il 2026-27 (le query potrebbero richiedere revisione) |
| **Dump itwiki 20261101** (locale) | infobox film/serie (incassi, budget, date, produzione), liste di premi in prosa non strutturata, filmografie "in tabella" | parsing offline; nessun download | già presente (4,29 GB) | testo CC BY-SA 4.0 | **fonte secondaria** per ciò che manca a Wikidata; i fatti (un numero, una data) non sono testo creativo, ma l'attribuzione si conserva in `source`/`revision_id` |
| **Wikipedia en** | solo dove it manca (biografie, incassi) | API mirate per pagina, non dump | piccola | CC BY-SA 4.0 | opzionale, dopo la fase 3 |
| **IMDb Non-Commercial Datasets** (`title.basics/crew/principals/ratings/episode`, `name.basics`) | ID, tipo opera, regia/sceneggiatura, cast per ordine, **numero di voti e voto IMDb**, mappa episodi | gz TSV scaricabili gratis, aggiornati ogni giorno **[V]** | ~1–1,5 GB gz [S] | **"personal and non-commercial use"** **[V pagina ufficiale]**; i termini di riuso/ridistribuzione NON sono stati letti per esteso | **opzionale e da decidere**: coerente con l'uso portfolio non commerciale già accettato per OMDb, ma duplicherebbe il voto IMDb che OMDb dà già: da non importare di default. Utile solo per colmare i buchi di cast/ID dopo il 2019 |
| **Premi Oscar** (CSV pubblici) | vincitori e candidati 1927–2023 | Kaggle/Zenodo/figshare | <10 MB | CC0 su aggregatori terzi **[V come indicazione, non verificato alla fonte]**; il database ufficiale dell'Academy non mostra termini di riuso **[V: nessuna licenza trovata]** | **non adottare**: provenienza non verificabile; si preferisce **Wikidata P166/P1411**, poi confronto di campione con le liste di Wikipedia |
| **Box office / classifiche storiche** | -- | -- | -- | **non esiste un dataset aperto e verificabile con incassi per film** (nessuno trovato) **[V]**; Box Office Mojo/The Numbers vietano lo scraping | **solo** Wikidata P2142/P2130 + infobox Wikipedia, con la nota che la copertura è parziale e i valori non omogenei (valuta/anno/ambito) |
| **TMDb/OMDb/TVmaze** | -- | -- | -- | -- | **non duplicati**: del TMDb si mantiene solo `tmdb_id` per join; punteggi mai copiati (OMDb vieta copie/indici) |

Licenza del database risultante: i fatti CC0 non impongono nulla, i dati ricavati da Wikipedia portano CC BY-SA ⇒ `source.license` per riga, **database locale non redistribuito** (come MovieLens).

---------------------------------------------------------------------------------------------------

## 5. Visualizzazione dello schema

**Soluzione: un generatore Python di ~250 righe, `cinema_db/harness/schema_doc.py`, che produce `docs/cinema_db/schema.html`, un file HTML autonomo (CSS e JS inline, nessuna libreria, nessuna CDN).**

- **Input**: il file SQLite reale, interrogato con `PRAGMA table_xinfo`, `PRAGMA foreign_key_list`, `PRAGMA index_list/index_xinfo`, `sqlite_master` (CHECK, UNIQUE, viste, DDL). Zero descrizioni scritte a mano per struttura e vincoli.
- **Cosa mostra**: tabelle come schede con colonne, tipo, `PK`/`FK`/`UNIQUE`/`NOT NULL`/`CHECK`, indici; le frecce FK con cardinalità dedotta (1:N dalla FK; N:M quando una tabella ha 2 FK che formano la PK, es. `work_genre`); clic su una tabella evidenzia le sue relazioni; ricerca per nome; filtro per gruppo (nodi / relazioni / premi / provenienza / viste); riquadro "provenienza" con `source` e licenza da `source` (tabella reale) e conteggi righe (`SELECT count(*)`) — i conteggi sono dati reali, non descrizioni.
- **Layout**: un SVG disegnato dal generatore (posizione per gruppi, nessun algoritmo di layout esterno: griglia a colonne per gruppo, routing ortogonale semplice). Alternativa valutata: **Mermaid `erDiagram`** — produce un testo comodo, ma richiede la libreria Mermaid (CDN o 2–3 MB inline) e non è né interattivo né filtrabile; resta come output secondario `schema.mmd` (testo, zero dipendenze) per incollarlo in un viewer. Graphviz/eralchemy scartati (dipendenze di sistema).
- **Annotazioni umane** (descrizione di tabella/colonna, provenienza): in un unico `cinema_db/schema_notes.yaml`… **[P: JSON, per non aggiungere PyYAML]**; il generatore **fallisce** se una tabella o colonna reale non ha nota, o se una nota cita una colonna che non esiste ⇒ non si può avere documentazione obsoleta.
- **Aggiornamento automatico**: il passo finale della build rigenera `schema.html`/`schema.mmd`; un test confronta l'hash del DDL con `build_info.schema_hash` e con quello incorporato nell'HTML (`<meta name="schema-hash">`): se lo schema cambia e l'HTML no, il test fallisce.
- **Aperto con un doppio clic**, in linea con `mappa.html` (già nel repo, stesso criterio "file HTML autonomo"). `mappa.html` dovrà indicare i nuovi file (`TREE` a mano, §regole del repo).

---------------------------------------------------------------------------------------------------

## 6. Sicurezza SQL: difese deterministiche

Punto di partenza [V]: `tool/movie_db/sql/guard.py` ha già authorizer (SELECT + READ su tabelle note + funzioni in whitelist `avg, coalesce, count, group_concat, like, max, min, round, sum`) e progress handler a tempo; `connection.py` apre `mode=ro` + `PRAGMA query_only`. Quel modello funziona perché l'SQL è costante. Con SQL scritto dal modello servono livelli in più; **ogni livello deve bastare da solo a impedire una scrittura**, e la loro somma limita anche i danni di disponibilità.

### Livello A — connessione
1. `sqlite3.connect("file:...?mode=ro", uri=True)`; per un DB che non cambia mai a runtime, **`&immutable=1`** (SQLite non apre mai il journal né prende lock: nessuna scrittura possibile nemmeno da file system). Il file non viene creato se manca.
2. Permessi del file `chmod 444` e cartella non scrivibile dall'utente del server **[P, difesa del sistema operativo]**.
3. Subito dopo l'apertura e **prima** di installare l'authorizer: `PRAGMA query_only=ON`, `PRAGMA trusted_schema=OFF` (le viste/trigger non possono chiamare funzioni "non fidate"), `PRAGMA foreign_keys=OFF`, `PRAGMA temp_store=MEMORY` e un `cache_size` basso.
4. `conn.enable_load_extension(False)` (il default in Python, asserito da un test) e **nessuna funzione definita dall'applicazione** (`create_function` mai chiamata su questa connessione).
5. Limiti SQLite per connessione con `conn.setlimit` (Python ≥ 3.11 [V: .venv è 3.11, SQLite 3.53.4]): lunghezza SQL (es. 2.000), numero di termini in un SELECT composto, profondità delle espressioni, argomenti di funzione, lunghezza dei pattern LIKE, numero di variabili.
6. Una connessione **per chiamata**, chiusa a fine uso (come `readonly_connection` oggi); nessuno stato condiviso tra thread.

### Livello B — validazione sintattica prima dell'esecuzione
Parser: **`sqlglot`** (puro Python, nessun binario, dialetto `sqlite`) per costruire l'AST. È una **nuova dipendenza**: richiede la tua approvazione (regola del repo: niente dipendenze senza chiedere). Alternativa senza dipendenza: tokenizer scritto a mano + il solo authorizer — meno robusto, **sconsigliato**: il tokenizer duplicherebbe la grammatica SQLite e sbaglierebbe sui casi limite (commenti annidati, stringhe, quoting).

Regole applicate sull'AST (rifiuto con un errore tipizzato e un motivo, mai silenzioso):
1. **Una sola istruzione**: `parse()` deve restituire esattamente 1 espressione; qualunque `;` residuo, anche dentro commenti `/* */`, `--`, o dopo stringhe, rende l'AST di 2 istruzioni o non parsabile ⇒ rifiuto. In più `sqlite3` stesso rifiuta le istruzioni multiple in `execute` (secondo livello).
2. **Radice**: solo `Select` (con `UNION/INTERSECT/EXCEPT` fra SELECT e `WITH` non ricorsive) ed eventualmente `EXPLAIN QUERY PLAN` (usato **solo internamente** per il controllo dei costi, mai esposto al modello **[P]**).
3. **Nessun nodo vietato nell'albero**: `Insert/Update/Delete/Create/Drop/Alter/Command/Pragma/Attach/Detach/Vacuum/Reindex/Analyze/Transaction/Replace/Merge/Set/Use/Copy`, `RETURNING`, `INTO`, trigger, `WITH RECURSIVE` (esclusa: rischio di runaway), `VALUES`/`pragma_*` come table-valued function, `LOAD_EXTENSION`.
4. **Whitelist funzioni** (insieme minimo, estendibile da test): aggregati `count, sum, avg, min, max, group_concat, total`; scalari `abs, coalesce, ifnull, nullif, iif, length, lower, upper, substr, trim, ltrim, rtrim, replace, instr, round, cast, typeof, like, glob` (**non** `random`, `randomblob`, `readfile`, `writefile`, `load_extension`, `fts5_*` non nell'elenco, `sqlite_*`, `printf`/`format` per evitare memoria, `zeroblob`, `unhex`, `json_*` finché non servono); ogni nodo `Anonymous`/`Func` è confrontato col nome, in minuscolo; funzioni utente o sconosciute ⇒ rifiuto. Table-valued function (`json_each`, `generate_series`…) **vietate**.
5. **Whitelist tabelle/viste**: ogni nodo `Table` deve essere nell'insieme `{v_work, v_person, v_credit, v_award, v_relation, v_box_office, v_provenance}`; schema qualificato (`main.x`, `sqlite_master`, `temp.x`, `other.x`) ⇒ rifiuto; alias e CTE definite nella query sono risolte per nome e NON possono ombreggiare una tabella reale (un CTE chiamato come una tabella non whitelisted è rifiutato).
6. **Whitelist colonne**: **sì**, per le viste (non per le tabelle base): ogni vista espone solo le colonne utili; in questo modo `birth_year` di una persona o `imdb_id` sono scelti per vista, e colonne sensibili/tecniche (`source_id`, hash interni, `snapshot_sha256`) non sono raggiungibili. Il costo è trascurabile perché le viste sono già un contratto. `SELECT *` si espande sull'elenco della vista (non sul DDL).
7. **Costruzioni valutate**: CTE non ricorsiva **ammessa** (utile per classifiche in due passi), subquery **ammesse** con profondità massima 3, `UNION` ammesso con massimo 3 rami, `PRAGMA/ATTACH/DETACH/VACUUM/REINDEX/ANALYZE/EXPLAIN` (raw)/`BEGIN/COMMIT` **vietati**, `ORDER BY` con espressioni ammesso; `LIMIT` obbligatorio e ricondotto a `max_rows` riscrivendo l'AST; commenti rimossi nell'AST rigenerato e **si esegue il testo rigenerato dall'AST** (mai il testo originale del modello) ⇒ quello che passa la validazione è esattamente quello che gira.
8. **Parametri**: i valori dell'utente non entrano mai nel testo; il modello può scrivere literal solo dentro l'AST che il validatore ha controllato (stringhe/numeri); il passaggio ideale è che il modello produca `{"sql": "... ? ...", "params": [...]}` con segnaposto; i literal nel testo sono accettati ma limitati in lunghezza e conteggio. Non esiste interpolazione di stringhe nel codice.

### Livello C — esecuzione
1. **Authorizer SQLite** (stessa idea di `guard.py`, ma più rigido): consente solo `SQLITE_SELECT`, `SQLITE_READ` su viste/tabelle sottostanti alle viste approvate (`arg1 in ALLOWED_BASE_TABLES`; le tabelle base servono perché la vista le legge; il validatore garantisce che il modello nomina solo viste, l'authorizer è la rete di sicurezza), `SQLITE_FUNCTION` in whitelist, **`SQLITE_RECURSIVE` negato**; **ogni altro codice** (`INSERT/UPDATE/DELETE/CREATE_*/DROP_*/ALTER_TABLE/PRAGMA/ATTACH/DETACH/TRANSACTION/SAVEPOINT/REINDEX/ANALYZE/CREATE_VTABLE/DROP_VTABLE`) è negato per costruzione (deny-by-default, come già fa `guard.py`). Un test enumera le costanti `SQLITE_*` del modulo e controlla che tutte tranne le consentite siano negate.
2. **Tempo**: progress handler ogni ~1.000 istruzioni VM + `deadline` (come oggi, timeout 2 s per query; massimo 1 query per chiamata di tool, al massimo 3 per turno), e `conn.interrupt()` da un timer di guardia.
3. **Righe**: `fetchmany(max_rows+1)`; se c'è la riga extra, il risultato è marcato `truncated` (e il modello deve dichiararlo). Dimensione del risultato in byte limitata (es. 60 KB di JSON) prima di entrare nel prompt.
4. **Complessità**: prima dell'esecuzione `EXPLAIN QUERY PLAN` (interno) e rifiuto se compare `SCAN` di una tabella base grande **senza** `LIMIT` risolvibile o un prodotto cartesiano (`JOIN` senza condizione, `CROSS JOIN`); massimo 4 `JOIN`, massimo 1 `GROUP BY`, `ORDER BY` solo su colonne di output o indicizzate per le viste grandi. Limiti di memoria con `PRAGMA max_page_count` non servono (read-only) ma `SQLITE_LIMIT_LENGTH` limita il singolo valore.
5. **Dopo ogni run**: verifica che `conn.total_changes == 0` (asserzione, difesa extra) e che il file non sia cambiato (mtime/size stat invariati all'avvio e dopo un campione di chiamate, solo in test).

### Come si evita che una query "innocua" scriva o abbia effetti collaterali
- *Scritture*: impossibili a 4 livelli indipendenti (URI `ro`/`immutable`, `query_only`, authorizer deny-by-default, AST solo `SELECT`). *Funzioni con effetti* (`load_extension`, `writefile`, `randomblob` per saturare): fuori whitelist e `enable_load_extension(False)`. *Trigger/viste con effetti collaterali*: `trusted_schema=OFF` e il DB di sola lettura non contiene trigger (verifica nella build: `SELECT count(*) FROM sqlite_master WHERE type='trigger'` = 0). *Vista malevola in un DB sostituito*: il DB è prodotto dalla nostra build, con hash verificato all'avvio.
- *Disponibilità* (non è una scrittura, ma blocca l'app): timeout + `interrupt`, righe, byte, join, `RECURSIVE` vietato, `LIKE` con pattern lunghi (limite `LIKE_PATTERN_LENGTH`), `GLOB`/`LIKE` iniziali con `%` su tabelle grandi valutati dal costo.
- *Fuga di dati*: whitelist di viste e colonne; nessuna lettura di `sqlite_master` (negata) ⇒ il modello non vede lo schema reale, solo quello documentato nel prompt.
- *Injection verso il modello* (dati di terzi nelle celle): i risultati sono dati, mai istruzioni; `tool_final_instructions` lo dichiara, come per Wikipedia; caratteri di controllo rimossi.

### Esempi di query che devono essere bloccate (test obbligatori)
```
DROP TABLE work                          -- DDL
DELETE FROM v_work                       -- DML
INSERT INTO v_work VALUES (...)          -- DML
UPDATE v_person SET name='x'             -- DML
SELECT 1; DROP TABLE work                -- multi-statement
SELECT 1 /*; DROP TABLE work*/; SELECT 2 -- multi-statement mascherato da commento
SELECT * FROM v_work;--                  -- accettabile solo dopo rigenerazione dell'AST (il `--` sparisce)
ATTACH DATABASE '/tmp/x' AS x            -- file esterno
PRAGMA writable_schema=1                 -- amministrazione
SELECT load_extension('/tmp/x.so')       -- estensione
SELECT readfile('/etc/passwd')           -- file (se presente)
SELECT * FROM sqlite_master              -- schema interno
SELECT * FROM work                       -- tabella base non in whitelist
SELECT * FROM main.v_work                -- schema qualificato
WITH RECURSIVE t(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM t) SELECT count(*) FROM t   -- runaway
SELECT randomblob(1000000000)            -- memoria
SELECT * FROM v_work a, v_work b, v_work c, v_credit d    -- prodotto cartesiano
SELECT * FROM pragma_table_info('work')  -- table-valued function
SELECT * FROM v_work WHERE title LIKE '%'||'%'||'%'||...  -- pattern estremo
EXPLAIN SELECT 1                         -- se non autorizzato
SELECT * FROM v_work LIMIT 99999999      -- il limite è ricondotto a max_rows
VACUUM INTO '/tmp/copy.db'               -- copia/scrittura
SELECT 1 UNION SELECT 1 UNION ... (100 rami)  -- limite composto
```
Un fuzzer deterministico (seme fisso) genera mutazioni (commenti, maiuscole, unicode, `\x00`, stringhe con `;`) delle query valide e controlla che il risultato sia sempre "rifiutata dal validatore **oppure** stessi risultati, mai scrittura".

---------------------------------------------------------------------------------------------------

## 7. Tool dell'agente

**Nome**: `cinema_sql` (in `CONFIG["orchestrator"]["allowed_tools"]`, registrato in `build_app`; flag `CONFIG["cinema_db"]["enabled"]`, **spento di default** finché non verificato).

**Contratto** (`Tool` Protocol): input Pydantic `CinemaSqlInput{ query: str (la richiesta), sql: str (SELECT con ? ), params: list[str|int|float|None] }`. Il planner scrive `sql` e `params` nella STESSA chiamata che sceglie il tool (nessuna chiamata LLM in più, a differenza di `movie_db_search` che ha un parser dedicato ⇒ **si risparmia 1 chiamata LLM per turno** sulle domande che oggi passano da MovieLens, ma solo per le nuove).

**Moduli e responsabilità** (una responsabilità ciascuno, funzioni pure dove possibile):
- `config.py` (`CinemaDbConfig`: `db_path`, `max_rows` 50, `timeout_ms` 2000, `max_queries_per_turn` 3; `extra="forbid"`), `settings.py` (costanti: whitelist, limiti, funzioni).
- `validator.py` — `validate(sql, params) -> ValidatedQuery | Rejection` (pura, nessun I/O, nessuna connessione).
- `policy.py` — dati e confronto: tabelle/viste, colonne per vista, funzioni; unica fonte, usata anche dal prompt.
- `connection.py` — apertura e guardia (authorizer, progress, limiti).
- `executor.py` — esegue il SQL **rigenerato**, parametrizzato, conta righe, tempo, marca `truncated`.
- `formatter.py` — righe → `chunks`/`metadata` con provenienza (`source.name`, licenza) e `follow_up` se vuoto/errore.
- `errors.py` — errori tipizzati (`rejected:<codice>`, `timeout`, `too_many_rows`, `db_missing`): al modello solo il codice e la regola violata, mai il messaggio di SQLite; il planner può correggere UNA volta (budget `max_queries_per_turn`).
- `trace.py` — step `cinema_sql_calls` con `sql` e `params` realmente eseguiti (come `db_query`), lista delle viste lette, conteggio righe, tempo; presenter terminale/web e serializer (regola del repo: kind in `STEP_RENDERERS` e `STEP_SERIALIZERS`).
- `tool.py` — `CinemaSqlTool`, `planner_schema()` (< 3.500 caratteri, come gli altri), `answer_hints`.

**Cosa riceve il planner**: (1) descrizione corta; (2) **schema delle viste** in forma compatta (nome, colonne, tipo, una riga di significato, valori ammessi dei CHECK); (3) 6–8 esempi di SQL tipici; (4) regole: solo SELECT, sempre `LIMIT`, usare `?`, nomi in inglese/originali dove indicato; (5) quando preferirlo (§8). Lo schema nel prompt è generato dalle stesse annotazioni di §5 (una sola fonte).

**Quando preferirlo agli altri**
- **Sì**: filmografie e carriere ("film di Villeneuve", "chi ha scritto X"), collaborazioni ("film con regista A e attore B"), premi e candidature, relazioni e franchise ("da cosa è tratto", "remake di", "tutti i film della saga"), identificazione/omonimi (anno, regista, ID), conteggi e aggregati ("quanti film ha diretto"), ricerca per paese/anno/genere senza criteri semantici, incassi/budget storici dichiarati, ID esterni.
- **No**: voti MovieLens (`movie_db_search`, invariato), punteggi correnti (OMDb, TMDb), disponibilità/uscite/trending/trailer (TMDb), prosa (Wikipedia), temi/atmosfera/"simile a" (RAG), episodi futuri (TVmaze), video (YouTube).
- **Confini**: se `cinema_sql` restituisce 0 righe, `follow_up` verso il tool online corrispondente (un solo passo, mai due tentativi ripetuti), perché l'assenza locale non prova l'assenza reale (copertura recente incompleta).

---------------------------------------------------------------------------------------------------

## 8. Riduzione di latenza e chiamate

### 8.1 Comportamento desiderato (descritto, non implementato; il planner non si tocca in questa fase)
1. **Risolvere in locale prima di chiamare fuori.** Un titolo → `work_id`/`imdb_id`/`tmdb_id`/`qid` con una SELECT da ~ms. **Correzione dopo la misura di Fase 0** (`docs/cinema_db/BASELINE.md`, richieste contate eseguendo il codice reale dei tool): passare l'ID risparmia **1 richiesta solo a OMDb** (2 → 1) e a TMDb **solo se si passa il `tmdb_id`** (2 → 1; con l'IMDb id TMDb costa ancora 2: `/find` + dettagli); a Wikidata **0** (1 richiesta per titolo con etichetta esatta, 1 per ID; relazioni 3 in entrambi i casi). Una chiamata `cinema_sql` fatta solo per ottenere un ID costa un passo di pianificazione (stimato ~2 s) per risparmiare ~0,4 s di rete: **non conviene da sola**. Il guadagno vero è sostituire interi tool (relazioni, filmografie, premi: −2…3 richieste e fino a 15 s di SPARQL) e alimentare catene che comunque servono (OMDb per più candidati: 10 → 5 richieste).
2. **Relazioni e franchise dal DB locale**: la regola 1f deve preferire `cinema_sql` e ricadere su `wikidata_search` solo se l'opera non è nel DB o ha 0 relazioni (l'assenza non prova). Risparmio: 2–5 richieste SPARQL (fino a 15 s di timeout ciascuna) ⇒ 1 SELECT.
3. **Filmografie e premi**: TMDb `person_details`+`discover` (2–3 richieste) ⇒ 1 SELECT; premi (oggi nessuna fonte strutturata) ⇒ 1 SELECT.
4. **Un solo tool al posto della catena**: "film di Nolan con Cillian Murphy tratti da un libro" oggi = TMDb (persona) + TMDb (discover) + Wikidata (relazioni) + risposta; con `cinema_sql` = 1 SELECT con 2–3 join.
5. **Parallelismo**: dove i passi sono indipendenti (es. `cinema_sql` + `youtube_search`, o `omdb_search` e `tmdb_search` per lo stesso titolo già identificato) il ciclo seriale potrebbe lanciarli insieme. Richiede una modifica del ciclo di `LLMOrchestrator.run` e del budget per turno (già per `turn_id`, quindi thread-safe in gran parte: `omdb/turns.py`, `wikipedia/budget.py` hanno lock; `youtube` ha "un solo slot" **[V AGENTS.md]** ⇒ non sicuro in parallelo senza modifiche). **Proposta: fase separata, solo per l'accoppiata locale + un tool remoto**, misurata prima.
6. **Cache e ID**: oltre al DB come "cache permanente di identificazione", il memo del turno esiste già in ogni tool. Nessuna nuova cache dei dati che vietano la copia (OMDb) o che vanno tenuti freschi (YouTube ≤ 30 giorni).
7. **Approfondimento esterno solo se serve**: `cinema_sql` non copre punteggi, streaming, prosa, serie vive ⇒ la risposta locale non si arricchisce "per sicurezza".

### 8.2 Routing e preferenze utente (`preferences/`, `SOURCE_TOOLS`)
Le impostazioni **prevalgono** sulla richiesta (decisione 2026-11-05). Aggancio proposto (skill §2f):
- **Tipo di fonte del DB**: dati strutturati enciclopedici (Wikidata/Wikipedia): è la categoria più vicina a **"official information"** (come `wikidata_search`). `SOURCE_TOOLS["cinema_sql"] = "official information"` **[P]**. Premi = verifica per `official`; **non** porta voti del pubblico né giudizi di critica ⇒ non si aggancia a `user ratings` né a `reviews`.
- **"Giudizio del pubblico"** (`user ratings`): MovieLens (`movie_db_search`) per le classifiche storiche + OMDb/TMDb per il voto corrente: invariati. Il DB può dare **il join** (via `imdb_id`) solo se si accetta lo snapshot MovieLens nel DB (decisione D3 sotto).
- **"Critica"** (`reviews`): OMDb (Metascore, Rotten Tomatoes) invariato; **i premi** (Oscar, Palma d'oro) sono un segnale di critica/industria, ma sono un'altra cosa: vanno dichiarati "premi", non "recensioni". Regola proposta: con `reviews` attiva e richiesta di "film premiati", `cinema_sql` fornisce l'elenco, OMDb i punteggi per i primi 5 (stessa eccezione già prevista nella regola 1d).
- **"Informazioni generali e approfondimenti"**: DB per i fatti; `wikipedia_search` per l'approfondimento; nessuna chiamata aggiuntiva a causa della preferenza.
- **Conflitti**: richiesta esplicita di un'altra fonte con una preferenza diversa ⇒ vince l'impostazione (regola attuale); `cinema_sql` non aggiunge passi per nessuna preferenza. Test del conflitto richiesto dalla skill.
- **Spoiler**: nessuno (nomina opere, premi, ruoli, mai la trama). **Film/serie**: `content_type=series` vieta i film ⇒ `check_step` dovrà conoscere le viste ammesse (la guardia attuale lavora per nome-tool e operazione; per `cinema_sql` serve ispezionare le viste lette: `v_work.kind` IN serie vs film ⇒ aggiunta di un filtro `kind` imposto dal tool, non dal modello **[P]**).

### 8.3 Vantaggi misurabili (metriche, **senza OpenAI**)
- n. richieste HTTP per turno e per tool (dal `calls[]` già in trace) su un insieme fisso di ~30 domande scriptate;
- n. passi di pianificazione per turno (stessa fonte: step `tool_selection`);
- latenza del tool (`elapsed_ms` in `tool_outcome`) e latenza SQL (p50/p95 su ≥ 200 query rappresentative, locale, zero costo);
- % di domande risolte senza chiamate esterne (rapporto, sulla suite di §10);
- **Base di riferimento prima**: contare, con un transport finto già esistente nei test (`tests/*_support.py`), le richieste attese per ogni domanda tipo con le regole di routing attuali (offline, deterministico); poi contare le richieste attese con il comportamento desiderato **descrivendo il plan**, non eseguendo il planner LLM. I numeri reali con il planner richiedono crediti OpenAI ⇒ si rimandano finché non ci sono.

---------------------------------------------------------------------------------------------------

## 9. Nuovo ruolo dei tool esistenti

| Tool | Dopo |
|---|---|
| `movie_db_search` | **invariato** (MovieLens resta la fonte del giudizio storico del pubblico; nessuna modifica a file, tool, schema) |
| `rag_search` | invariato: temi/atmosfera/"simile a"; passa `imdb_id`/`wikidata_id` che il DB e gli altri usano come chiave |
| `cinema_sql` | **nuovo**: fatti strutturati, relazioni, premi, filmografie, identificazione |
| `tmdb_search` | meno chiamate di identificazione/filmografia; resta per streaming, uscite, trailer, voti correnti, trending, cast attuale |
| `wikidata_search` | **ripiego** (opera assente dal DB o DB senza relazioni); il DB assorbe `resolve` e `relations` per le opere note; da non eliminare |
| `wikipedia_search` | invariato (prosa) |
| `omdb_search` | invariato; riceve l'`imdb_id` dal DB (−1…2 richieste) |
| `tvmaze_search` | invariato (dati vivi) |
| `youtube_search` | invariato |

---------------------------------------------------------------------------------------------------

## 10. Pipeline di acquisizione e aggiornamento

Directory `cinema_db/harness/build/` (offline, mai importata a runtime). Ogni fase scrive un manifest con SHA-256 e il suo output è **ricostruibile a rete bloccata dagli snapshot** (principio già adottato da `RAGWikipediaFilm`/`Series`).

| Fase | Contenuto | Rete | Tempo [S] |
|---|---|---|---|
| B0 | Verifica input: SHA-1 dump (`53d757d9…`), hash di `films.v3.jsonl`, `data/s5/manifest.json`, indici snapshot Wikidata | no | secondi |
| B1 | **Estrazione dai claims dello snapshot**: nodi `work` e relazioni (`credit`, `work_genre`, `work_country`, `work_language`, `work_relation`, `work_company`, `award_result` grezzi, `box_office`, `budget`) per ~41 k film + ~15 k serie + 2,6 k film TV | no | minuti |
| B2 | **Raccolta mirata** (con permesso): entità `person` (QID raccolti in B1), entità `award`/`ceremony`/`company`/`genre`/`country`/`language` | sì, `wbgetentities` ~50/req, circa 3–5 k richieste, ~1–2 h a 1 req/s [S]; snapshot nuovo accanto al vecchio (non lo modifica) | 1–2 h |
| B3 | **Infobox itwiki** (dal dump locale) per incassi/budget mancanti; regole di parsing esplicite; ogni valore con `revision_id` | no | 30–60 min (lettura del dump, come Phase 0: 64 min [V]) — o 20 min con l'harvest già fatto se contiene l'infobox [?] |
| B4 | Normalizzazione: nomi, `name_norm`, valute/importi, date a precisione variabile (anno/mese/giorno), paesi/lingue ISO | no | secondi |
| B5 | **Risoluzione degli ID**: QID ↔ `imdb_id` ↔ `tmdb_id` (TMDb/IMDb dalle claims P345/P4947/P4983, `links` di MovieLens solo come verifica incrociata, mai scrivendoli); conflitti elencati, mai risolti a caso | no | secondi |
| B6 | **Deduplicazione**: stesso QID = una riga; film senza QID (0,1 %) con chiave `wp-<page_id>`; duplicati di persone con stesso QID uniti; omonimi di nome NON uniti | no | secondi |
| B7 | Import SQLite in transazione unica, `PRAGMA foreign_keys=ON`, poi `PRAGMA foreign_key_check` (deve restituire 0 righe), `PRAGMA integrity_check`, `ANALYZE`, creazione viste, `VACUUM` | no | 1–3 min |
| B8 | Controlli di qualità (§11), generazione di `schema.html`/`.mmd`, `build_info`, hash del file | no | secondi |
| Aggiornamento | **Per snapshot, non per diff**: ogni release trimestrale = nuovo dump itwiki + nuove richieste B2 solo per QID nuovi; la nuova DB si costruisce accanto, si verifica, si sostituisce con un `rename` atomico; il vecchio resta come rollback. Aggiornamento incrementale vero (diff con `schema:dateModified`/RecentChanges) **non proposto in questa fase** (complessità > beneficio per 56 k opere) | sì, ridotta | -- |

**Dimensioni stimate [S]**: `work` ~60 k righe, `person` ~200–300 k, `credit` ~800 k–1,2 M, `award_result` ~30–60 k (copertura Wikidata parziale), `work_relation` ~30–50 k, `box_office` ~5–10 k; file SQLite **150–400 MB** (senza trame). **Costi**: 0 USD (nessun OpenAI; nessuna API a pagamento); tempo di sviluppo: vedi fasi. **Dump da scaricare**: nessuno nuovo nella fase 1; IMDb (opzionale, ~1 GB) e itwiki sono già locali.

---------------------------------------------------------------------------------------------------

## 11. Piano di test (tutti offline e gratuiti, salvo dove indicato)

1. **Qualità dei dati**: copertura per campo (soglie documentate, p.es. QID ≥ 99,9 %, regia ≥ 98 %); nessuna chiave duplicata; nessun `imdb_id` ripetuto tra opere diverse (salvo noti); campione stratificato (≥ 150 righe, seme fisso) confrontato con la pagina Wikipedia; `award_result` confrontato con 10 cerimonie note (Oscar miglior film 1990–2024) — copertura dichiarata, non assunta.
2. **Coerenza relazionale**: `PRAGMA foreign_key_check` vuoto; `work_relation` senza archi orfani (target mancante ⇒ `related_entity`); relazioni simmetriche (`follows` ↔ `followed_by`) ; nessun `credit` senza persona o opera; `CHECK` rispettati; film/serie del catalogo s5 con gerarchia coerente (24 controlli già esistenti riusati).
3. **ID**: duplicati/mancanti per schema; formato (`tt\d{7,9}`, `Q\d+`); coerenza con `links` MovieLens (solo lettura, report di divergenza).
4. **Correttezza delle risposte**: ~60 domande scriptate "SQL atteso → risultato atteso" su un **DB fixture minuscolo** (costruito nei test come `conftest.py` fa per MovieLens), poi le stesse su campioni reali con valori verificati a mano (offline).
5. **Sicurezza SQL**: tutte le query di §6 (parametrizzate in un test unico); fuzzer deterministico; test che enumera i codici `SQLITE_*` dell'authorizer; test che la connessione non riesce a scrivere (`INSERT` diretto via connessione grezza fallisce); `total_changes == 0`; file invariato (hash prima/dopo); `enable_load_extension` falso; test AST che `http`/rete non sono importati nel modulo (stile `test_tool_package.py`).
6. **Whitelist**: ogni vista/colonna/funzione ammessa accettata, ogni altra rifiutata; un test che l'insieme di colonne nel prompt = insieme nella policy = viste reali (3 fonti, 1 verità).
7. **Prestazioni**: p50/p95 per 200 query rappresentative; soglie (es. p95 < 100 ms, timeout 2 s mai raggiunto nelle query legittime); piano delle query con indici (nessun `SCAN` di tabelle grandi nelle query-tipo).
8. **Riduzione delle chiamate**: test offline con transport finti che contano le richieste per domanda nel "comportamento desiderato" (via ID dal DB) vs "oggi"; asseriscono il risparmio atteso. Il confronto con il planner reale **non si esegue** (crediti): resta come verifica futura.
9. **Regressione**: `tests/test_movie_db_*.py` e `tests/test_tool_package.py` invariati e verdi; nessuna differenza di byte nei file di `tool/movie_db/` e in `movie_db/`; il RAG film/serie non toccati (hash di `build_v3 verify` e `build_clean verify`).
10. **Documentazione sincronizzata**: test che `schema.html` e `policy.py` rispecchiano il DB (§5).

---------------------------------------------------------------------------------------------------

## 12. Fasi di implementazione (per priorità, commit atomici quando me lo chiederai)

0. **Misura di base** (1 giorno): contare richieste/passi attesi per ~30 domande con le regole attuali (offline) e censire dai test i "tool chiamati inutilmente". Nessuna modifica.
1. **Sicurezza prima del dato**: `tool/cinema_db/{validator,policy,connection,executor,errors}` + fixture + tutti i test di §6/§11.5–6. Nessun DB reale. *(Il rischio più alto è qui; si chiude per primo.)*
2. **Schema + generatore** `schema.html` su DB fixture (§3, §5).
3. **Build B0–B1, B4–B8 offline** dallo snapshot già locale: nodi film/serie, ruoli, generi, paesi, relazioni, franchise, premi grezzi, incassi/budget — **senza rete**. Primo DB utile.
4. **Build B2 + B3** (persone, premi, cerimonie, infobox): con il tuo permesso per la rete.
5. **Tool completo** (`formatter`, `trace`, presenter terminale/web, `SOURCE_TOOLS`, test del conflitto delle preferenze, schema del planner < 3.500 caratteri). Spento di default.
6. **Routing**: regola nuova nel planner (numerazione senza rinumerare), eval di routing **offline** per la parte di validazione degli argomenti; la parte live solo quando ci saranno crediti.
7. **Ottimizzazioni**: passaggio degli ID ai tool esterni, ripiego Wikidata, valutazione del parallelismo (modifica separata e misurata).
8. **Documentazione**: `AGENTS.md`, `README.md`, `mappa.html` (regole del repo) e `docs/cinema_db/`.

---------------------------------------------------------------------------------------------------

## 13. Rischi, limiti e decisioni che richiedono il tuo consenso

**Decisioni**
- **D1 — Dipendenza `sqlglot`** (puro Python, licenza MIT **[?: da riverificare]**): sì/no. Senza di essa la validazione sintattica sarebbe più debole. *Raccomandazione: sì, pin esatto in `requirements.txt`.*
- **D2 — SQL libero sulle viste vs operazioni fisse** (come `movie_db_search`). SQL libero dà flessibilità e −1 chiamata LLM; operazioni fisse sono più sicure ma ripropongono il collo di bottiglia del parser. *Raccomandazione: SQL sulle viste, con tutti i livelli di §6.*
- **D3 — Snapshot MovieLens nel nuovo DB** (solo `movie_id, imdb_id, avg_rating, n_ratings`, ricostruibile): permette "film con premi e voto alto" in una sola query. MovieLens non viene toccato, ma i suoi dati sono duplicati (licenza: no redistribuzione, il DB resta locale). *Raccomandazione: no nella prima versione; join applicativo in una fase successiva.*
- **D4 — Rete per B2** (~3–5 k richieste mirate a Wikidata, nessun dump): sì/no, e quando.
- **D5 — IMDb Non-Commercial Datasets**: *(rivisto dal proprietario, vedi §15: fonte integrativa e selettiva, non primaria.)*
- **D6 — Policy "official information"** per `cinema_sql` e per i premi (§8.2).
- **D7 — Parallelismo** del ciclo del planner: ora o dopo.

**Rischi e limiti**
- **Copertura dei premi e degli incassi su Wikidata è incompleta e disomogenea** (nello snapshot: P166 su 44/721 entità, P1411 su 71, P2142 su 66, P2130 su 74 — **campione di 40 blocchi, non l'intero dataset**): le risposte devono dire "nei dati disponibili", e un esito vuoto non prova l'assenza (follow-up verso Wikipedia/Wikidata). Nessun dataset aperto affidabile per il box office storico **[V]**.
- **Valori di incasso/budget** con valute e anni diversi: nessuna conversione inflattiva, mai confronti tra film senza avvertenza.
- **Copertura recente** del catalogo film (< 2019 completo, dopo no: 188 film nel 2026) — le uscite recenti restano a TMDb; il DB non si fa passare per aggiornato.
- **SQL scritto dal modello**: errori di schema, query lente o plausibili ma sbagliate; mitigazioni: viste semplici, esempi, una correzione guidata per turno, risultati con le colonne e l'SQL mostrati nella trace. La correttezza semantica di un SELECT valido **non** è garantita dal validatore.
- **Prompt injection nei dati** (nomi/titoli da Wikidata): trattati come dati; resta una difesa a livello di modello, non dimostrabile offline.
- **Licenze**: il testo Wikipedia è CC BY-SA 4.0: i soli fatti sono usati, ma l'attribuzione per riga resta; la questione ShareAlike sul testo generato è aperta come per TVmaze. Termini ufficiali di WDQS (limiti verificati sopra), IMDb (solo la pagina breve letta) e il testo integrale di CC BY-SA non sono stati letti per esteso.
- **Schema che evolve**: le viste isolano il prompt dalle tabelle base; ogni cambio rigenera `schema.html` e fallisce un test se il prompt diverge.
- **Costo di manutenzione** della build (B2 dipende da API Wikidata che cambiano — il backend di WDQS è in migrazione 2026-27 **[V]**).
- **Limite di Python 3.11**: `sqlite3.Connection.setconfig` (DBCONFIG: `DEFENSIVE`, `TRUSTED_SCHEMA`) non è disponibile prima della 3.12; si usano `PRAGMA trusted_schema=OFF` e l'authorizer **[?]** da provare in fase 1.
- Non verificato in questo piano: la presenza di FTS5 nel SQLite locale; l'esistenza dell'infobox nell'harvest della Phase 0; i conteggi complessivi di premi/incassi sull'intero snapshot (solo campione).

---------------------------------------------------------------------------------------------------

## 14. Cosa è stato fatto in questa fase
Letti: `AGENTS.md`, `orchestrator.py` (ciclo seriale), `app.py` (CONFIG), `tool/movie_db/` (guard, connection, queries, modelli), `movie_db/schema.py`, `tool/wikidata/{queries,models}.py`, `preferences/behavior.py`, `tool/tvmaze/settings.py`, catalogo `films.v3.jsonl` (campi, copertura), snapshot Wikidata (40 blocchi), PROGRESS di film e serie. Verificate online: pagina Wikidata:Database download (130,5 GiB, CC0), manuale WDQS (limiti), pagina IMDb Non-Commercial Datasets (file, uso non commerciale), ricerca su dataset Oscar/box office (nessuna fonte aperta verificata per incassi). **Nessun file di codice, nessun database, nessun test creato; MovieLens, tool e RAG intatti; nessun commit; nessuna chiamata a pagamento.** Unico file creato: questo.

---------------------------------------------------------------------------------------------------

## 15. Decisioni del proprietario (2026-11-05) e fasi

| | Decisione | Note di attuazione |
|---|---|---|
| D1 | sì a `sqlglot`, dopo aver verificato licenza e versione | **MIT**, nessuna dipendenza a runtime (solo extra), Python ≥ 3.9; fissata **30.24.0** (pubblicata il 2026-10-20, oltre due settimane prima). In `requirements.txt` |
| D2 | SQL libero **solo sulle viste approvate**, con tutte le difese; niente operazioni fisse con parser LLM | fase 1 |
| D3 | **nessuna** copia dei dati MovieLens; resta separato e invariato | il nuovo DB non contiene voti MovieLens; join solo applicativo, se mai, in una fase successiva |
| D4 | sì alle richieste gratuite mirate a Wikidata (persone, premi, cerimonie) **dopo** la prima build offline verificata; prima quantificare entità e richieste | fase 4; snapshot, cache e manifest separati, con ripresa |
| D5 | **IMDb solo come fonte integrativa e selettiva**: usata solo quando Wikidata, Wikipedia e le fonti già integrate non danno il dato; priorità a opere, persone, cast, registi, sceneggiatori, date e ID mancanti; mai importazione indiscriminata, nessuna duplicazione; provenienza, data di acquisizione e condizioni d'uso sempre registrate; misurare l'aumento reale di copertura | **da fare in fase 3/4, con una verifica a parte delle condizioni d'uso** (la pagina ufficiale letta il 2026-11-05 dice «personal and non-commercial use»: i termini completi sul riuso non sono stati letti). Se una categoria di dati non risulta utilizzabile, si cerca una fonte alternativa. Nessun voto IMDb (già in OMDb e MovieLens) |
| D6 | `cinema_sql` appartiene a `official information` | `SOURCE_TOOLS["cinema_sql"] = "official information"`, fase 5, con il test del conflitto |
| D7 | parallelismo rimandato; prima ottimizzare identificazione, passaggio degli ID e numero di chiamate | vedi la correzione di §8.1: l'ottimizzazione è soprattutto la sostituzione di interi tool |

Fasi: 0 misura · 1 sicurezza SQL (solo fixture) · 2 schema e `schema.html`/`schema.mmd` · 3 prima build offline · 4 arricchimento Wikidata (e IMDb selettivo) · 5 tool e routing (spento di default). Ogni fase termina con un checkpoint e un commit a sé.

---------------------------------------------------------------------------------------------------

## 16. Fase 2: revisione dello schema e decisioni (2026-11-05)

Lo schema reale è `cinema_db/schema.py`; la documentazione navigabile è `docs/cinema_db/schema.html` (e `schema.mmd`), generata dal file SQLite. Qui sono le decisioni e le correzioni rispetto allo schema preliminare di §3.

### Problemi strutturali trovati nello schema preliminare e corretti ora
| Lacuna di §3 | Correzione | Perché costava aggiungerla dopo |
|---|---|---|
| Titoli alternativi, omonimi e alias solo come colonne (`title_it`, `title_en`, `original_title`) | tabella `entity_name` (tipo, lingua, `is_primary` unico per entità) per opere, persone, aziende, franchise e premi | ogni ricerca per titolo e ogni vista dipenderebbero dalle colonne |
| Serie, stagioni ed episodi come tabelle separate e anche come `work.kind` (duplicazione) | **un solo `work`** con `parent_work_id`, `season_number`, `episode_number`; vincoli CHECK (un episodio ha un padre, il numero di episodio solo agli episodi) | crediti, ID e relazioni avrebbero avuto due strade |
| Identificativi come colonne (`imdb_id`, `tmdb_id`) | tabella `external_id` + `id_scheme` (IMDb, TMDb film/serie/persona, TVmaze, Wikidata, pagine Wikipedia it/en, EIDR…), `UNIQUE(scheme, value)` | ID multipli (TMDb film e serie si sovrappongono) e nuove fonti senza cambiare lo schema |
| Provenienza solo per riga | `source_id`+`source_ref` su ogni riga di fatti **più** `field_provenance` (origine di UNA colonna quando diversa da quella della riga: serve ai buchi riempiti da IMDb, D5) | la decisione D5 non era realizzabile col solo livello di riga |
| Opere d'origine non cinematografiche in una tabella a parte (`related_entity`) | romanzi, fumetti, videogiochi, opere teatrali sono `work` con `kind` e `medium` diversi (`work_kind`): le relazioni sono sempre `work → work` con FK vere; le viste di default non li confondono (`medium`) | «da quale libro è tratto», «chi è l'autore dell'opera d'origine» richiedono crediti e nomi anche per queste opere |
| Premi: una sola tabella `award_result` con categoria testuale | `award` → `award_category` (con `scope`: opera, persona, persona per un'opera) → `ceremony` (anno, edizione) → `award_result` (esito `won`/`nominated`, opera e/o persona) | «chi è stato candidato come miglior regista per quale film» |
| Nessuna data di uscita per paese | `work_release` (paese, data ISO parziale, tipo) | «quando è uscito in Italia» |
| Incassi e budget in tabelle separate, con ambiguità di scala | `work_financial` unica (`kind`, `scope`, paese, importo, valuta ISO, anno di riferimento); nessuna conversione né inflazione | evita confronti scorretti tra valute e anni |
| Relazioni con `related_qid` per opere fuori dal DB | solo `work_relation(work_id, related_work_id, relation)` con direzione canonica; `v_work_relation` mostra **entrambe** le direzioni con la formulazione di ciascuna | una sola query per «cosa è tratto da X» e «da cosa è tratto X» |
| Ruoli come CHECK | `role_type` (vocabolario con reparto e `is_cast`) | nuovi ruoli senza modificare le tabelle |

### Struttura risultante (misurata dal file SQLite; era lo schema v1: dopo §17 è **v2 con 32 tabelle, l'indice FTS5 e 20 viste**)
30 tabelle, 64 chiavi esterne reali, 17 viste pubbliche, 8 relazioni molti-a-molti (6 tabelle ponte più `credit` e `award_result` tra opere e persone), tutte le tabelle `STRICT`, nessuna colonna JSON, `PRAGMA foreign_key_check` vuoto. Supertipo `entity` (opere, persone, aziende, franchise, premi) con FK composta `(id, entity_type)` che impedisce a un'opera di appoggiarsi a una persona. Vocabolari di definizione (nessun dato sui film): 12 tipi di opera, 16 ruoli, 4 relazioni, 11 schemi di identificativo.

### Cosa è volutamente rimandato (aggiungere dopo costa poco)
Classifiche e liste (nuove tabelle, nessuna modifica), personaggi come entità (`credit.character_id` nullable), temi/parole chiave e luoghi di ripresa (nuove giunzioni), flag per adulti (colonna), ricerca full-text FTS5 (disponibile nel SQLite locale; si aggiunge sulle stesse tabelle, ma gli oggetti virtuali non passano dal validatore e richiedono una vista dedicata: decisione aperta). Lo schema è stato scritto perché ognuna di queste aggiunte sia **additiva**.

### Viste pubbliche (le uniche leggibili da `cinema_sql`)
`v_work`, `v_person`, `v_name`, `v_external_id`, `v_credit`, `v_work_genre`, `v_work_country`, `v_work_language`, `v_work_release`, `v_work_company`, `v_work_relation`, `v_franchise`, `v_award_result`, `v_work_financial`, `v_genre`, `v_role_type`, `v_source`. Ogni vista nomina la fonte (`source`) dove il dato è un fatto citabile. Colonne interne (`source_ref`, `snapshot_sha256`, `field_provenance`) non sono esposte. La policy (`tool/cinema_db/approved_views.py`) è **generata** dal file SQLite e verificata a ogni apertura.

### Decisioni ancora aperte
1. **FTS5** per i titoli: sì/no e con quale vista (finora la ricerca è `name_norm` con LIKE/uguaglianza, indicizzata).
2. **Generi**: restano testo libero dalle fonti (`genre`); una normalizzazione in una tassonomia chiusa è una decisione di fase 3.
3. **Date di uscita per paese**: Wikidata ha `P577` con qualificatore di luogo; la copertura reale si misura in fase 3.
4. **IMDb (D5)**: il modello è pronto (`field_provenance`, `source.usage_scope`); l'uso resta subordinato alla lettura dei termini completi.
5. `work.is_adult`, personaggi come entità, classifiche: rimandati (vedi sopra).
6. **Nome del file del database**: `cinema_db/data/cinema.sqlite3` (cartella ignorata da git) e politica di sostituzione atomica per le release: da confermare in fase 3.

### Limiti della verifica
`schema.html` è stato aperto e controllato visivamente con Chrome headless (tabella selezionata, vista selezionata, gruppi, pannello dettaglio); non è stato provato su altri browser. `schema.mmd` è stato verificato dal parser dei test (stesse tabelle, colonne, chiavi e relazioni dello schema reale) ma **non** dalla libreria Mermaid: il controllo con la libreria da CDN è stato negato dal sistema di autorizzazione e non è stato aggirato. Le prestazioni su 60.000 crediti sintetici (da 4 a 132 ms) non sono quelle dei dati reali.

---------------------------------------------------------------------------------------------------

## 17. Decisioni strutturali chiuse prima della fase 3 (2026-11-05) e indagine

### FTS5 per titoli e alias (decisione chiusa)
- **Disponibilità verificata** nell'ambiente effettivo: Python 3.11, SQLite 3.53.4 compilata con `ENABLE_FTS5` (`PRAGMA compile_options`), `STRICT` incluso.
- **Struttura**: tabella virtuale `entity_name_fts` (FTS5, **contenuto esterno** `entity_name`: nessuna copia del testo; tokenizzatore `unicode61 remove_diacritics 2`; indici di prefisso 2 e 3), **nessun trigger** (il database è di sola lettura e si ricostruisce per intero: l'indice si riempie con `rebuild_fts` a fine build e `check_fts` ne verifica integrità e conteggio). Vista pubblica **`v_title_search`** (`entity_id`, `entity_type`, `name`, `name_kind`, `language`, `is_primary`, `work_kind`, `work_year`, `rank`, `search`): si interroga con `WHERE search MATCH 'padri*' ORDER BY rank` e si unisce a `v_work`/`v_person` su `entity_id`.
- **La ricerca esatta resta** e non è sostituita: `v_external_id` (IMDb, TMDb, Wikidata, pagina Wikipedia…) e `v_name.name_norm`. **Non è una ricerca semantica** e non sostituisce il RAG: abbina parole e prefissi (accenti e maiuscole ignorati), non il significato; titoli non latini (giapponese, cinese) si abbinano per sequenza di caratteri, non per parola.
- **Sicurezza** (provata da test): il modello non può nominare `entity_name_fts` né le sue tabelle d'ombra, né `bm25`/`highlight`/`snippet`; non può scrivere né riconfigurare l'indice (`INSERT ... VALUES('rebuild')`, `DELETE`, `DROP` rifiutati a ogni livello). All'authorizer (solo a lui) si concede ciò che FTS5 stesso richiede quando una vista legge la tabella virtuale: le funzioni interne `match` e `bm25`, il pragma di sola lettura `data_version` (e nessun altro pragma, mai con argomento), le tabelle d'ombra e le colonne del contenuto esterno. Costo di questa scelta: l'authorizer da solo non distingue la lettura interna di FTS5 da una lettura al livello superiore di quelle tabelle (contengono solo testo dei nomi, già pubblico in `v_name`); il validatore le vieta comunque.
- Una query FTS5 malformata dà un errore generico senza il testo del motore.

### Generi normalizzati (decisione chiusa)
- **Tre livelli**: `genre_label` (le etichette come le fonti le danno, una riga per voce Wikidata o per testo di catalogo, in italiano e/o inglese, **mai riscritte**, con fonte), `genre_label_map` (quale/i genere/i canonico/i significa ogni etichetta: `exact`, `synonym`, `specific`, con l'identificativo della regola) e `genre` (vocabolario canonico di 38 generi con genere più ampio, es. commedia romantica → commedia). `work_genre` lega l'opera all'**etichetta** che una fonte le ha dato, non al genere canonico: il genere canonico si raggiunge solo attraverso l'etichetta, quindi l'informazione originale e la provenienza non si perdono.
- **Viste**: `v_work_genre` (genere canonico, una riga per opera e genere anche se più etichette portano allo stesso), `v_work_genre_label` (le etichette originali con il genere cui portano, vuoto se non mappate), `v_genre_label` (il vocabolario delle etichette), `v_genre`.
- **Sinonimi e differenze terminologiche**: le regole confrontano il «nucleo» dell'etichetta (senza «film», «cinema», preposizioni) con forme esatte e sinonimi in italiano **e** inglese, e con parole chiave per le etichette più specifiche («psychological thriller» → thriller, `specific`). «Film giallo» (etichetta inglese «crime film») porta a poliziesco e mistero. Una voce con due significati porta a più generi; una voce che nessuna regola riconosce **resta non mappata** (leggibile, mai forzata).
- **Misura su dati reali**: 591 etichette distinte nei film; il vocabolario e le regole ne mappano 339 e coprono il **95,3%** delle 82.207 asserzioni (`docs/cinema_db/BUILD_REPORT.md` riporta la misura sul database finito). Etichette frequenti non mappate di proposito: «buddy film», «film indipendente», «film d'essai», «found footage», «film collettivo» (non sono generi chiari). «Film muto» è un formato e «a tematica LGBT» un tema: sono nel vocabolario (`silent`, `lgbtq`) con la descrizione che lo dice, perché le fonti li elencano tra i generi.
- Il vocabolario è scritto per questo progetto (`cinema_db/harness/build/genres.py`): la sua licenza è una decisione del proprietario (registrata come `unverified` nel registro delle fonti).

### IMDb (D5): condizioni d'uso verificate, ostacolo
La pagina ufficiale di IMDb sull'uso dei dati (letta il 2026-11-05) consente un uso «limitato, personale e non commerciale» dei soli dataset pubblicati, con la dicitura «Information courtesy of IMDb (https://www.imdb.com). Used with permission.», e **vieta di alterare, ripubblicare, rivendere o riutilizzare i dati «per creare qualsiasi tipo di database online o offline», salvo uso personale individuale**; IMDb può ritirare il permesso in qualsiasi momento. Non dice nulla su indicizzazione, opere derivate, software o IA. Conclusione: **importare righe dei dataset IMDb in un database interrogato da un'applicazione non rientra in modo verificabile in queste condizioni** (è un database di informazioni sui film costruito con dati IMDb, e il progetto ha un backend e un frontend, non è un uso strettamente individuale). Per D5, che chiede di verificare e, se una categoria non è utilizzabile, di cercare un'alternativa:
- **non si importa alcuna riga IMDb**; gli ID IMDb che già stanno nel database vengono da Wikidata (proprietà P345, CC0) e dal catalogo, non dai dataset IMDb;
- i buchi (durata, cast, titolo originale, regia mancanti) si colmano con alternative con condizioni verificabili: **Wikidata** (fase 4, CC0), **Wikipedia** (infobox e liste, CC BY-SA) e, per chi accetta i limiti, i tool online già presenti (TMDb, OMDb) a runtime e non copiati;
- la **copertura reale che IMDb aggiungerebbe non è misurabile** senza scaricare i file (vietato in questa fase); il limite superiore è in `SURVEY.md` §8 (ad esempio 3.293 film con durata mancante e un ID IMDb agganciabile) e va letto come tetto teorico, non come stima;
- se il proprietario ottenesse un permesso scritto o una licenza commerciale di IMDb, il modello è pronto (`field_provenance`, `source.usage_scope`, `source.terms_note`): si importerebbe solo il dato mancante, con provenienza e data.
**Decisione aperta per il proprietario**: confermare l'esclusione di IMDb (consigliata) o procurarsi un permesso esplicito.

### Indagine sulle fonti locali (`SURVEY.md`)
Snapshot film: 41.395 entità, 149.026 etichette, 1.676 richieste originali; snapshot serie: 32.412 entità. Numeri, copertura dei campi, persone per ruolo, vocabolari, relazioni, premi, incassi e fabbisogno stimato della fase 4 (**stima**: da 1.031 a 3.119 richieste, a 50 id per richiesta, circa un'ora a una richiesta al secondo) sono in `docs/cinema_db/SURVEY.md`. Sorprese utili: il 100% dei premi manca di nome (1.685 voci senza etichetta nello snapshot: i premi non si possono importare offline); soltanto 100 società su 4.398 e 48 franchise su 887 hanno un nome; di sceneggiatori, compositori e fotografi quasi nessuno ha un nome offline; le persone con nome sono 91.906 su 119.539.

---------------------------------------------------------------------------------------------------

## 18. Fase 3 completata: prima build offline (2026-11-05)
Risultati, problemi trovati e corretti, lacune e fabbisogno della fase 4 sono in `docs/cinema_db/PROGRESS.md` e nel rapporto generato `docs/cinema_db/BUILD_REPORT.md`; l'indagine preliminare è in `SURVEY.md`. Decisioni di progetto prese durante la build:
- **Un fatto si importa solo se le fonti locali lo dicono E nominano a cosa si riferisce.** Nessun nome, codice (ISO di paesi, valute diverse da USD) o tipo di uscita è inventato: restano vuoti o `unspecified` e sono lacune della fase 4 contate nel rapporto.
- **Opere in due cataloghi = una sola opera.** Il catalogo serie decide le opere televisive (kind, nome primario); quello film aggiunge nomi, identificativi, durata e i fatti di Wikidata. Le asserzioni ripetute da due fonti si registrano una volta (conteggiate). Due QID di Wikidata per lo stesso film **non** si fondono (240 conflitti riportati): decisione di curatela per il proprietario.
- **Le serie con identificativo non affidabile** (`ids_reliable = false`, 2.480 nel catalogo) non usano i fatti di Wikidata; le pagine miste manga/anime (2.032) non si importano di default.
- **La pagina di un elenco di episodi non identifica un episodio**: `wikipedia_it` si assegna solo agli episodi con pagina propria.
- **Persone**: solo quelle con un nome nei file locali (92.041); i crediti delle altre non si importano finché la fase 4 non ne legge il nome.
- **Ordine deterministico e digest del contenuto** (`build_info.content_sha256`): la build è riproducibile byte per byte nel contenuto (verificato con una seconda build completa); si scrive su un file temporaneo e si rinomina solo dopo i controlli; con `--force` il file precedente resta come `.previous`.
