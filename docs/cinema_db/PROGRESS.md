# Cinema DB — PROGRESS (punto di ripresa)

Aprire una sessione nuova: leggere `AGENTS.md`, `docs/cinema_db/PLAN.md` (§15 per le decisioni) e questo file.
Ultimo aggiornamento: 2026-11-05 (fase 4 completata, fermo prima della fase 5). Legenda: **[V]** verificato con il comando indicato · **[S]** stima · **[P]** solo progettato.

## Stato
| Fase | Stato |
|---|---|
| 0 Misura (baseline offline) | **fatta [V]** |
| 1 Sicurezza SQL (solo fixture) | **fatta [V]** — 168 test del nucleo (`tests/test_cinema_sql_security.py`), suite richiesta verde |
| 2 Schema + `schema.html`/`schema.mmd` | **fatta [V]**, schema v2 (generi normalizzati, FTS5): 32 tabelle STRICT più l'indice FTS5, 20 viste approvate |
| 3 Prima build offline | **fatta [V]** — 333 MB, 293.447 opere, riproducibile, 0 differenze su 400 film (vedi sotto e `BUILD_REPORT.md`) |
| 4 Arricchimento Wikidata (IMDb escluso, D5) | **fatta [V]** — 1.129 richieste, 0 fallite; +142.823 crediti, +27.751 risultati di premio, date di vita 113.171 persone, importi in 37 valute, ISO su 179 paesi; rapporto `PHASE4_REPORT.md`, digest `b3b0de51…` |
| 5 Tool `cinema_sql` e routing | da fare; **non registrato** in `app.py` né in `allowed_tools` |

## HANDOFF PER NUOVA CONVERSAZIONE (checkpoint del 2026-11-05, fine fase 3)

**Nota sul percorso**: questo è l'unico PROGRESS del progetto, `docs/cinema_db/PROGRESS.md` (non esiste `tool/cinema_db/PROGRESS.md`: non crearlo).

### 1. Dove siamo, in una riga
Fasi 0–4 **fatte e verificate**; il database locale `cinema_db/data/cinema.sqlite3` (405 MB, schema v2 **invariato**, 301.860 opere, 141.645 persone, 675.327 crediti, 27.751 risultati di premio) è la build della fase 4, riproducibile; il tool `cinema_sql` **non è registrato** nell'agente (fase 5 da decidere con il proprietario). Le richieste di rete della fase 4 sono finite (snapshot `cinema_db/data/wikidata_phase4/`, 1.129 richieste); **nessuna ulteriore richiesta di rete senza nuova autorizzazione**. Il database della fase 3 (digest `d9d475d7…`) resta in `cinema_db/data/cinema.phase3.sqlite3` e si ricostruisce con `build --no-phase4`.

### 2. Da leggere, in quest'ordine
1. `AGENTS.md` (regole del repository; la sezione «Database cinematografico locale» riassume lo stato; è lungo: leggere in particolare §1 e §4).
2. Questo file (stato, handoff, risultati).
3. `docs/cinema_db/PLAN.md`: §15 (decisioni D1–D7), §16 (schema e revisione), §17 (FTS5, generi, IMDb, indagine), §18 (decisioni della build). Le sezioni 1–14 sono il piano originale, in parte superato dalle successive.
4. `docs/cinema_db/BUILD_REPORT.md` (copertura, lacune, interrogazioni reali) e `docs/cinema_db/SURVEY.md` (fabbisogno stimato della fase 4, tetto teorico di IMDb).
5. Codice: `cinema_db/schema.py` (DDL, viste, vocabolari), `cinema_db/schema_notes.py`, `cinema_db/harness/build/{build,extract,snapshot,genres,common,sources,survey,verify}.py`, `tool/cinema_db/{validator,connection,executor,policy,approved_views}.py`. Documentazione navigabile: `docs/cinema_db/schema.html` (aprire nel browser).

### 3. Comandi per verificare lo stato (tutti offline e gratuiti, nessuno modifica il database)
```bash
cd /Users/filippo.milzagmail.com/Desktop/NetflixScout && source .venv/bin/activate
git status --short            # atteso: vuoto
git log --oneline -8          # in cima i commit della fase 4 (fetcher, build, confronto, documentazione)
python -m cinema_db.harness.schema.generate --check        # atteso: exit 0 (schema.html, schema.mmd, approved_views.py aggiornati)
python -m pytest tests/test_cinema_sql_security.py tests/test_cinema_schema.py tests/test_cinema_schema_doc.py tests/test_cinema_views_security.py tests/test_cinema_build.py -q   # atteso: 349 passed
python -c "import sqlite3;d=sqlite3.connect('file:cinema_db/data/cinema.sqlite3?mode=ro',uri=True);print(dict(d.execute('select key,value from build_info')))"   # fase 4: content_sha256 che inizia con b3b0de51, schema_version 2, builder cinema_db.harness.build.build/2 (la fase 3, con --no-phase4, dà d9d475d78874901b…)
python -m cinema_db.harness.enrich.fetch status          # atteso: ogni categoria done = requests (offline)
ls -l movie_db/data/movielens32m.sqlite3                  # atteso: 1323962368 byte, 20 Ott 23:40 (MovieLens mai toccato)
```
Suite completa richiesta da `AGENTS.md` §4 (elenco nel file): atteso **2.440 passed** (circa 45–90 s). Hash (primi 16 caratteri) degli input, già registrati in `source.snapshot_sha256` e in `build_info`: catalogo film `films.v3.jsonl` `d5a78e4d1e3327fb`; indice snapshot film `79d40ea98e8b068f`; indice snapshot serie `957d41179d293203`; `data/s5/manifest.json` `dd8ac9f7601c0659` (`shasum -a 256 <file>`).

### 4. Stato dei dati e come ricostruirli
- **Ignorati da git** (`.gitignore`: `cinema_db/data/`; tutto sotto `tool/RAGWikipedia*/data/`): `cinema_db/data/cinema.sqlite3` (333.148.160 byte), `cinema.build_report.json`, `build.log`, `verify.log`; gli snapshot Wikidata originali **non vanno mai modificati**: film `tool/RAGWikipediaFilm/data/cache/wikidata/itwiki-20261101-a` (1.676 richieste), serie `tool/RAGWikipediaSeries/data/cache/wikidata/itwiki-20261101-series-a` (1.388 corpi); cataloghi `tool/RAGWikipediaFilm/data/clean_v3/films.v3.jsonl` e `tool/RAGWikipediaSeries/data/s5/`; dump `tool/RAGWikipediaFilm/data/raw/itwiki-20261101-pages-articles.xml.bz2` (4,3 GB, non letto dalla build).
- **Versionati**: tutto il codice, i test, `docs/cinema_db/*` (compresi `schema.html`, `schema.mmd`, `BUILD_REPORT.*`, `SURVEY.*`, `BASELINE.*`) e `tool/cinema_db/approved_views.py` (generato).
- **Ricostruzione**: `python -u -m cinema_db.harness.build.build --force` (8–12 minuti; in background con `nohup … > cinema_db/data/build.log`, aspettare con Monitor perché `sleep` in foreground è bloccato); scrive su un `.building` e rinomina solo a controlli passati; il vecchio file resta come `cinema.sqlite3.previous`. Poi `python -u -m cinema_db.harness.build.verify [--reproduce]` (la seconda build per il digest costa altri ~8–10 minuti) riscrive `BUILD_REPORT.*`. Se si cambia lo schema: aggiornare `schema_notes.py`, `python -m cinema_db.harness.schema.generate`, **ricostruire** il database.
- **Sorgente di verità della struttura**: il file SQLite; `schema.html`, `schema.mmd` e `approved_views.py` sono generati da lì e i test falliscono se sono obsoleti.

### 5. Numeri esatti della build (BUILD_REPORT, digest `d9d475d7…`)
333 MB; 293.447 opere = film 36.529, corti 3.427, film TV 2.817, serie 11.764, miniserie 1.901, stagioni 14.176, episodi 222.557, altre 276; persone 92.041; crediti 532.504 (cast 416.981, regia 48.704, sceneggiatura 30.240, produzione 16.051, musica 7.457, fotografia 5.335, montaggio 3.757, ideatori 1.946, scenografia 1.277, costumi 756); nomi 739.048; identificativi 369.683 (wikidata 148.096, wikipedia_it 67.212, imdb 54.673, tmdb film 40.568, tmdb serie 11.596, eidr 36.445, tvdb 11.093); generi: 1.069 etichette (563 mappate), 123.995 asserzioni (92,1 % mappate); relazioni 4.703 (based_on 1.638, follows 3.065); uscite per paese 50.740; importi USD 9.212; società 1.109; franchise 86; paesi 183; lingue 246. Opere unite tra i due cataloghi: 911. Build 707 s, seconda build 492,5 s, **digest identico**; campione di 400 film: **0 differenze**; `foreign_key_check` 0, `integrity_check` ok, FTS5 coerente, nessun trigger.

### 6. Decisioni già prese (non riaprire senza motivo)
D1 sqlglot 30.24.0 (MIT) · D2 SQL libero solo sulle viste approvate, con tutte le difese · D3 nessuna copia di MovieLens (resta separato) · D4 richieste mirate a Wikidata solo dopo la build offline verificata, con quantificazione prima · D5 IMDb **non importato** (le condizioni vietano di costruire un database con i suoi dati; il modello `field_provenance`/`source.usage_scope` è pronto se arrivasse un permesso scritto) · D6 `cinema_sql` ↔ `official information` · D7 niente parallelismo del planner. In più: FTS5 a contenuto esterno senza trigger con `v_title_search`; generi in tre livelli (etichetta originale → mappa → vocabolario canonico di 38); un fatto si importa solo se le fonti locali lo dicono E nominano a cosa si riferisce (mai nomi, codici o tipi inventati); il catalogo serie decide le opere televisive e quello film vi aggiunge; due QID Wikidata dello stesso film restano due opere; serie con `ids_reliable=false` non usano i fatti di Wikidata; la pagina di un elenco di episodi non identifica un episodio.

### 7. Decisioni ancora aperte (per il proprietario)
1. **Fase 5** (tool `cinema_sql`, routing): non iniziata, serve il via.
2. Confermare l'esclusione di IMDb o procurare un permesso scritto (D5).
3. Licenza del vocabolario dei generi (registrato `unverified`).
4. Fusione dei duplicati di Wikidata (184 conflitti di QID rimasti; 240 film in due QID): curatela manuale o regola.
5. Rappresentare i crediti `producer` verso organizzazioni (370 QID, oggi non importati come persone) come relazione con la società.
6. Snapshot di aggiornamento della fase 4 (richiede autorizzazione) e se proseguire con date di vita o luoghi di nascita (`birth_country_id` è ancora vuoto).
7. Se esporre le 28 omonimie titolo+anno come candidate duplicate; ricerca di titoli non latini (tokenizzatore `trigram`).

### 8. Prossime attività, in ordine di priorità
1. **Fase 5** (solo con l'ok): tool `cinema_sql` (`tool/cinema_db/tool.py` con `planner_schema`, risposta finale, trace/presenter/serializer web come gli altri tool, `CONFIG["cinema_db"]`, registrazione in `build_app` e `allowed_tools` **spenta di default**, `SOURCE_TOOLS["cinema_sql"] = "official information"`, regola di routing senza rinumerare, test del conflitto con le preferenze, test offline di routing; `tests/test_tool_package.py` richiede `cinema_db` in `TOOLS` e l'eccezione per la cartella radice come per `movie_db`). Le viste v_* ora hanno premi, importi non USD, ISO e date di vita da interrogare; le descrizioni in `schema_notes.py` vanno riviste per i dati nuovi.
2. Curatela: duplicati di Wikidata, omonimie, vista delle candidate duplicate.
3. Misurare in modo reale (con crediti, solo se autorizzato) il guadagno di richieste del routing.

### 9. Vincoli e abitudini da non dimenticare
- **Mai**: modificare MovieLens (`movie_db/`, `tool/movie_db/`), i RAG film e serie, gli altri tool o il planner; usare crediti OpenAI o embedding; importare dati IMDb; inventare dati nel database di prodotto; fare richieste di rete senza permesso; scrivere o modificare `.env`; eliminare dati originali o snapshot.
- **Git**: commit brevi in inglese, minuscolo, una responsabilità ciascuno, con la riga `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`; **mai** reset, clean, rebase, amend, stash; commit solo a blocco verificato.
- **Documentazione**: a ogni cambio aggiornare `PROGRESS.md`, `PLAN.md`, `AGENTS.md`, `README.md`, `mappa.html` (controllare la sintassi con `node`).
- **Sicurezza SQL**: il modello legge solo le viste `v_*`; si esegue il testo rigenerato dall'AST; ogni nuova funzione o vista passa dalla policy generata e dai test di `tests/test_cinema_views_security.py`.
- **Lezioni operative**: `.gitignore` ignora `build/` (la cartella `cinema_db/harness/build/` è riammessa con `!`); `python -I` ignora PYTHONPATH; le build lunghe vanno in background con `python -u` e si attendono con Monitor (niente `sleep` in foreground); Chrome headless (`--screenshot`, `--virtual-time-budget`) serve per verificare l'HTML; il controllo di Mermaid con la libreria da CDN è stato negato dal sistema e non va aggirato (`schema.mmd` è verificato solo da un parser di test).
- **Limiti da dichiarare sempre**: la baseline di richieste è una stima; le prestazioni sono misurate su dati sintetici e sul database reale locale, non in produzione; la copertura riguarda il catalogo locale (recente incompleto); il rispetto delle istruzioni da parte del modello non è dimostrabile offline.

## Vincoli permanenti
Nessuna chiamata OpenAI a pagamento, nessun embedding, MovieLens e RAG film/serie intatti (verificato: `movie_db/data/movielens32m.sqlite3` stesso size e mtime di prima, aperto solo `mode=ro`), nessun input originale modificato, nessun parallelismo del planner.

## Fase 0 — baseline [V per le richieste, S per sequenze e latenze]
`python -m cinema_db.harness.baseline.run_baseline` → `docs/cinema_db/BASELINE.md` e `baseline.json` (offline, gratis).
- **Misurato**: richieste HTTP inviate dal codice reale dei tool contro i transport finti dei test; latenza di query SQL reali su MovieLens (sola lettura).
- **Stimato**: sequenza dei tool per domanda (il planner LLM non è stato eseguito), chiamate del planner, latenze di rete (dalle note live di AGENTS.md), costo delle operazioni senza fixture.
- Risultato sulle 30 domande (18 cambiano sequenza): richieste HTTP **96 → 49**, passi con tool esterno **39 → 22**, chiamate del planner **44 → 42** (stima), latenza **~192 → ~133 s** (stima).
- **Correzione del piano**: passare l'ID risparmia 1 richiesta solo a OMDb (e a TMDb solo col `tmdb_id`), a Wikidata 0. Il guadagno vero è sostituire interi tool con SQL locale e alimentare catene (OMDb per 5 candidati: 10 → 5). Dettaglio in BASELINE §5 e PLAN §8.1.
- SQL locale MovieLens (misurato): top-rated 0,2 ms p50, by_title 0,04 ms, aggregazione per genere 90 ms.

## Fase 1 — nucleo di sicurezza [V]
Codice: `tool/cinema_db/` (`validator.py`, `policy.py`, `connection.py`, `executor.py`, `errors.py`, `settings.py`). Test: `tests/test_cinema_sql_security.py` (171) con `tests/cinema_sql_support.py` (DB fixture con colonne «segrete» non esposte). Dipendenza: `sqlglot==30.24.0` (MIT).
Livelli (ognuno da solo impedisce le scritture, provato da test indipendenti):
1. **Validatore AST**: una sola SELECT (anche tra commenti), niente DDL/DML/PRAGMA/ATTACH/EXPLAIN/VACUUM, niente CTE ricorsive né con il nome di una tabella, niente funzioni tabella, whitelist di viste, colonne (qualificazione sqlglot) e funzioni, join con condizione che lega due tabelle, parametri solo posizionali, LIMIT/OFFSET letterali e forzati. **Si esegue il testo rigenerato**, senza commenti, e viene ricontrollato.
2. **Connessione**: `mode=ro` + `immutable=1`, `query_only`, `trusted_schema=OFF`, estensioni disattivate, limiti SQLite (`setlimit`), `ATTACH` a 0; la policy è verificata contro il DB reale (viste, colonne, colonne base, nessun trigger) prima di usare la connessione.
3. **Authorizer** con negazione predefinita: solo SELECT, lettura delle colonne delle viste dal livello superiore, lettura delle colonne base dichiarate **solo per conto di una vista** (chiude il trucco della CTE col nome di una vista), funzioni in lista. Test: ogni codice azione da 0 a 199 è negato tranne SELECT/READ/FUNCTION.
4. **Executor**: scadenza (progress handler + `interrupt`), tetto di righe (con una riga in più per segnalare il taglio), di byte e di caratteri per cella, controllo del piano (`SCAN` di tabelle grandi con ordinamento/raggruppamento), errori tipizzati senza il testo di SQLite.
Trovato dai test e corretto: (a) sqlglot conserva i commenti nel testo rigenerato (ora `comments=False`); (b) `JOIN` senza `ON` diventa `ON TRUE` (ora rifiutato, condizione obbligatoria su due tavole).
Non coperto/limiti noti: la correttezza *semantica* di una SELECT valida non è verificata dal validatore; i nomi di funzione dipendono dal rendering di sqlglot (test sulle funzioni ammesse e vietate); il controllo del piano usa solo tabelle dichiarate `large_tables` (nessuna ancora: arrivano con lo schema reale in fase 2); `Python 3.11` non ha `Connection.setconfig` (DBCONFIG DEFENSIVE): compensato da authorizer e `trusted_schema=OFF`.

## Fase 2 — schema, viste e documentazione generata [V] (misure dello schema v1; lo schema attuale è v2, vedi Fase 2b)
- **Schema** `cinema_db/schema.py` (DDL, indici, viste, vocabolari di definizione); `create_database(path)` crea il file e rifiuta di sovrascrivere. Decisioni e correzioni rispetto al piano: PLAN §16.
- **Misure dal file reale**: 30 tabelle STRICT, 64 FK, 17 viste pubbliche, 8 molti-a-molti, 11 schemi di ID, 16 ruoli, 12 tipi di opera, 4 relazioni; DB solo-schema 372 KB; `foreign_key_check` e `integrity_check` vuoti/ok; nessun JSON.
- **Documentazione**: `python -m cinema_db.harness.schema.generate` scrive `docs/cinema_db/schema.html` (autonomo, nessuna libreria, ricerca, filtro per gruppo, relazioni tracciate, pannello con colonne/chiavi/indici/check/DDL/viste), `schema.mmd` e `tool/cinema_db/approved_views.py`; con `--db FILE` mostra conteggi e fonti reali; `--check` esce con 1 se qualcosa è obsoleto. Fallisce se manca la descrizione di una tabella, vista o colonna, o se ne esiste una per qualcosa che non c'è (`cinema_db/schema_notes.py`).
- **Policy generata** `tool/cinema_db/approved_views.py`: viste, colonne e colonne base lette dal file; verificata a ogni apertura (`verify_policy`); un DB manomesso (vista con una colonna in più, trigger, vista mancante) è rifiutato.
- **Test** (tutti offline): `tests/test_cinema_schema.py` (14: integrità, STRICT, niente JSON, fonte su ogni fatto, indici sulle FK, vincoli, sottotipo, unicità, viste su domande vere), `tests/test_cinema_schema_doc.py` (10: note complete, file aggiornati, HTML = struttura reale, JS valido con node, Mermaid = struttura reale, digest), `tests/test_cinema_views_security.py` (87: 17 domande reali, 30 query vietate, authorizer da solo, scritture, DB manomesso, 60.000 crediti, fuzz di 1.200 casi) e i 168 della fase 1. I dati dei test sono invenzioni in cartelle temporanee.
- **Modifica al nucleo di sicurezza**: il controllo del piano ora rifiuta solo **due o più scansioni complete** di tabelle grandi nella stessa istruzione (join o sottoquery senza indice); una scansione lineare con GROUP BY è consentita (prima avrebbe respinto «chi ha più crediti»). SQLite crea da sé un indice automatico per i join di uguaglianza, quindi questi non sono quadratici.
- **Verifica visiva** dell'HTML con Chrome headless (stato iniziale, tabella `work` selezionata con le relazioni tracciate, vista `v_credit`): corretti l'ordine dei gruppi, l'elenco delle tabelle lette dalla vista e la larghezza del pannello. **Non verificato**: Mermaid con la sua libreria (controllo da CDN negato dall'autorizzazione), altri browser.
- **Decisioni aperte**: PLAN §16 (FTS5, generi, date per paese, IMDb, nome/posizione del file DB).

## Fase 2b — decisioni strutturali chiuse prima della build [V] (PLAN §17)
- **FTS5**: disponibile (SQLite 3.53.4, `ENABLE_FTS5`); `entity_name_fts` a contenuto esterno senza trigger, vista pubblica `v_title_search` (`WHERE search MATCH 'padri*' ORDER BY rank`), ricerca esatta per ID e per nome normalizzato invariata, non sostituisce il RAG semantico. All'authorizer (solo a lui) si concedono le funzioni interne `match`/`bm25`, il pragma `data_version`, le tabelle d'ombra e le colonne del contenuto esterno; il modello non può nominarle (validatore) né scrivere l'indice (test a ogni livello).
- **Generi**: `genre` (38 canonici), `genre_label` (etichette originali con fonte, mai riscritte), `genre_label_map` (exact/synonym/specific + regola), `work_genre` (opera → etichetta). Viste `v_work_genre`, `v_work_genre_label`, `v_genre_label`, `v_genre`. Copertura misurata sui dati reali: 92,1 % delle asserzioni mappate (114.162 su 123.995; 95,3 % nei soli film), le altre restano leggibili.
- **IMDb (D5)**: la pagina ufficiale vieta di riutilizzare i dati «per creare qualsiasi tipo di database online o offline» salvo uso personale individuale: **nessuna riga IMDb importata**, decisione aperta per il proprietario (PLAN §17).

## Fase 3 — prima build offline [V]
- **Comandi**: `python -m cinema_db.harness.build.survey` (indagine), `python -m cinema_db.harness.build.build [--force]` (build, ~8–12 min, scrive `cinema_db/data/cinema.sqlite3`, ignorato da git), `python -m cinema_db.harness.build.verify [--reproduce]` (rapporto in `docs/cinema_db/BUILD_REPORT.md`). Solo fonti locali, nessuna rete, nessun credito, nessun embedding; gli input non vengono modificati (test).
- **Risultato** (BUILD_REPORT): 333 MB; 293.447 opere (36.529 film, 3.427 corti, 2.817 film TV, 13.665 serie e miniserie, 14.176 stagioni, 222.557 episodi, 276 altre), 92.041 persone, 532.504 crediti, 739.048 nomi, 369.683 identificativi, 123.995 asserzioni di genere, 4.703 relazioni, 50.740 uscite per paese, 9.212 importi USD. Controlli: `foreign_key_check` 0, `integrity_check` ok, FTS5 coerente, un solo nome primario per entità, nessun trigger, policy delle viste accettata.
- **Riproducibilità [V]**: una seconda build completa dà lo stesso digest del contenuto (`d9d475d7…`).
- **Verifica indipendente [V]**: 400 film a caso (seme fisso) ricalcolati dal catalogo e dallo snapshot (titolo, anno, durata, IMDb, QID, registi, paesi): **0 differenze**.
- **Copertura sui 40.227 film** (BUILD_REPORT §3): anno 99,9 %, durata 92,2 %, titolo originale 94,4 %, IMDb 99,3 %, TMDb 94,3 %, EIDR 87,1 %, regista 96,4 %, cast 81,9 %, generi 94,6 %, paesi 99,6 %, lingue 81,0 %, uscite per paese 34,9 %, incassi/budget USD 12,5 %; società **0,7 %**, franchise **0,2 %**, relazioni 6,6 % (mancano i nomi: fase 4).
- **Problemi trovati dalla verifica e corretti**: (1) film e serie si sovrapponevano (miniserie classificate come film TV, film TV in entrambi i cataloghi): **911 opere unite** (il catalogo serie decide le opere televisive, quello film aggiunge ciò che sa; omonimie titolo+anno scese da 812 a 28, residuo = versioni diverse legittime); (2) la pagina di un elenco «Episodi di X» veniva attaccata a un episodio a caso: ora solo gli episodi con pagina propria (106) hanno `wikipedia_it`; (3) la ricerca per ID IMDb su `v_work` costava 296 ms (sottoquery per riga): ora join su un identificativo preferito unico, 5 ms; (4) «Stati Uniti d'America», «USA», «Gran Bretagna» non si risolvevano (alias espliciti); (5) conflitti di identificativi 16.457 → 240 (i restanti sono duplicati veri di Wikidata, riportati nel rapporto); (6) un genere fatto di sola punteggiatura bloccava la build.
- **Cosa NON è stato importato e perché** (BUILD_REPORT §6): 144.630 crediti senza nome nei file locali (sceneggiatori, compositori, fotografi, montatori, produttori hanno quasi tutti solo il QID: nessun nome inventato), 96.508 asserzioni di società e 5.129 di franchise senza nome, 11.056 relazioni verso opere senza etichetta, 26.577 premi e candidature (nessuno dei 1.685 premi ha un nome offline), 962 importi in valute diverse da USD (codice ISO non verificabile offline), 6.394 date di uscita con un luogo che non è un paese noto, 2.032 pagine miste manga/anime (non ammesse di default). Paesi senza codice ISO (0 su 183) e persone senza date di vita: sono lacune dichiarate, non valori indovinati.
- **Interrogazioni reali** attraverso validatore e authorizer (BUILD_REPORT §7): 16 domande tipo da 3 a 255 ms (registi con più film 254 ms, conteggio per decennio 206 ms, episodi di una stagione 246 ms). Due danno 0 righe per lacune di dati e non per errori: «tratto da» di un titolo (relazioni verso opere senza nome) e un franchise (solo 86 franchise con nome).
- **Limiti**: i numeri di copertura riguardano il catalogo locale, non il cinema mondiale (copertura recente incompleta già nota); i dati delle serie sono quelli del catalogo s5 (episodi numerati solo per titolo esatto, titoli nella lingua della pagina); le date di uscita per paese non distinguono il tipo (`unspecified`); un'opera in due QID di Wikidata resta due opere (240 conflitti riportati, non fusi); i test usano dati inventati in cartelle temporanee, il database reale non contiene dati inventati.
- **Test** (tutti offline): 168 (sicurezza SQL del nucleo) + 17 (schema) + 10 (documentazione generata) + 108 (sicurezza sulle viste reali, FTS5 inclusa) + 46 (build su miniatura: opere, ID, crediti, generi, unione, riproducibilità, input invariati, nessuna rete, build fallita senza residui). Suite completa richiesta: 2.440 test verdi.

## Fase 4 — arricchimento mirato da Wikidata [V] (rapporto completo e numeri: `PHASE4_REPORT.md`)
- **Codice** (`cinema_db/harness/enrich/`): `targets.py` (quali QID servono, offline, dai soli dati locali), `builders.py` (richieste da frammenti costanti e id validati `Q…`), `client.py` (UNICO punto di rete: allowlist di due endpoint, User-Agent col repository e senza e-mail, una richiesta alla volta ≥1,2 s, `maxlag=5`, `Retry-After`, ritentativi limitati, interruttore dopo 4 fallimenti), `store.py` (archivio a sola aggiunta nel formato degli snapshot: `requests.jsonl` + `bodies/<sha256>.json.gz`, chiave per richiesta = ripresa senza ripetizioni, errori in `errors.jsonl`, mai come dati), `fetch.py` (`plan`, `status`, `run --category … [--limit N]`), `compare.py` (confronto prima/dopo di due database). Lettura nella build: `build/phase4.py`, opzionale (`Inputs(phase4=…)`, `build` la usa se la cartella esiste, `--no-phase4` la esclude: allora il digest è quello della fase 3).
- **Richieste**: 1.129 (persone 712, premi 56+4, società 118, relazioni 174, franchise 21, luoghi 22, paesi 4, lingue 6, valute 1, elementi persona/società 11), 0 fallite, 20 ritentate; piano in `cinema_db/data/wikidata_phase4/plan.json`.
- **Problemi trovati e corretti**: organizzazioni accreditate come produttori erano persone con lo stesso QID di una società (180 → 439 conflitti): regola organizzazione/persona con la classe P31 (164 di 534 sono davvero persone); categoria di premio senza risultati; chiave di unicità delle cerimonie.
- **Non fatto, per scelta**: tipo di uscita per paese (Wikidata non lo dà: P437 sull'1,3 % delle date, nessun tipo), nessuna modifica allo schema; fusione dei duplicati di QID; luoghi festival/città come paesi.
- **Dopo**: la fase 5 può iniziare solo con l'ok del proprietario; ogni ricostruzione deve passare `verify --reproduce --report-name PHASE4_BUILD_REPORT` (il `BUILD_REPORT.md` della fase 3 non si sovrascrive).

## Fabbisogno stimato della fase 4 (STIMA, nulla richiesto; SURVEY.md §7) — fatto, vedi sopra
Richieste a 50 id: persone senza nome 983; premi e cerimonie 47; valute 1; bersagli di relazioni 121; società 86; franchise 17; luoghi 22; paesi/lingue per i codici ISO (non nella stima di SURVEY, circa 9 per 426 voci); tutto, comprese le date di vita di ogni persona (2.824): **circa 3.100–3.130** richieste, circa un'ora a una richiesta al secondo. Minimo utile (nomi mancanti, premi, valute): 1.031. IMDb non fa parte del piano (vedi sopra).

## Prossimo passo
Fermo prima della fase 5. Da decidere con il proprietario: avvio del tool `cinema_sql` (§8), fusione dei duplicati di Wikidata, crediti verso organizzazioni, esclusione di IMDb, licenza dei generi.
