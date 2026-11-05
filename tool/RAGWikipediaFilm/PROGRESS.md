# PROGRESS — RAG Wikipedia: documento di continuità (stato al 2026-11-04, fine Fase 8)

**Leggi questo file per primo.** Lo stato qui sotto è quello verificato a fine sessione. Convenzioni: **[V]** fatto verificato (misurato o riletto sui dati), **[P]** proposta non approvata, **[A]** decisione aperta che spetta all'utente, **[D]** decisione definitiva dell'utente. I rapporti di fase (`PHASE*.md`, `AUDIT_REPORT.md`) sono storici: dove contraddicono questo file, vale questo file (tabella delle correzioni nella sezione 12).

Lingua del progetto e dell'utente: italiano. Cartella di lavoro consentita: **solo `tool/RAGWikipediaFilm/`**.

## 0. In una pagina

- Il nuovo RAG si basa su Wikipedia italiana (dump `20261101`): **41.137 film** puliti, un punto Qdrant per film nella collezione **`wikipedia_films_it_v2`** (`text-embedding-3-large`, 1.536 dimensioni, cosine). Dataset e collezione sono verificati. **[V]**
- **Nessuna integrazione nell'applicazione è stata eseguita.** Vecchio RAG (`tool/rag/`, collezione `netflix_scout`), orchestratore, `app.py`, frontend e `web_api` non sono mai stati toccati. **[V]**
- **[D]** Il nuovo RAG **sostituirà completamente** il vecchio: un solo RAG attivo, niente retriever paralleli, niente RRF né fusione, niente ripiego al vecchio. Il vecchio resta intatto finché la sostituzione non è verificata nell'applicazione; solo dopo si elimina.
- **[D]** Le vecchie limitazioni date all'agente (non usare il RAG con titoli, persone, anni dopo il 2012) esistevano per la scarsa qualità del vecchio RAG e **non vanno ereditate**. La nuova strategia è in `RAG_USAGE_STRATEGY.md` (sezione 5 qui sotto).
- **Aggiornamento del 2026-11-04:** le sei decisioni della sezione 8 sono state **prese dall'utente** (sezione 0bis, vincolanti). Il piano è stato riscritto (`INTEGRATION_PLAN.md` sezione 10, `RAG_USAGE_STRATEGY.md` sezione 8). Nessuna implementazione è iniziata.
- Prossimo passo: Fase A del piano (dati v3), poi retriever standalone e test live, solo dopo l'integrazione.

## 0bis. Decisioni vincolanti dell'utente (2026-11-04) **[D]**

1. **Aftershock – Terremoto a New York incluso** (film: 41.138). *Anne Frank*, *Atomic Train*, *Attila l'unno* restano esclusi e segnalati «non verificati»; miniserie confermate escluse. Il suo vettore è **recuperabile a costo 0**: `Q2421745` è negli shard di Fase 3 (`Q2421745#0`, sinossi 5.387 caratteri) e non è tra le 25 trame corrette, quindi l'hash coincide con `v2.old_vectors()` (verificato in sola lettura).
2. **Schema v3**: `work_format`, `format_confidence`, `franchise_id` (+ indici `actor_names`, `work_format`, `franchise_id`, full-text su `synopsis`) in una **nuova collezione** `wikipedia_films_it_v3`; v2 non si modifica; vettori riusati. `franchise_id` da P179/P8345 dello snapshot (i claim ci sono, copertura parziale: ~6/50 in un campione).
3. **TMDb**: solo per i film effettivamente mostrati (`/find` per `imdb_id`, poster), mai massivo, mai per titolo.
4. **BM25 non si elimina ancora.** Un solo retriever denso; il lessicale è un vincolo (filtro full-text/payload) o un insieme di candidati ordinato dal solo vettore, mai un secondo ranking, mai RRF. A/B nel live.
5. **Precedenza delle impostazioni persistenti**: regola prioritaria, prevale sempre l'impostazione; prima frase = conflitto e impostazione che prevale; poi lettura compatibile. **Anche i default sono vincolanti**; per `preferred_sources` conflitto solo se la richiesta chiede un'altra fonte. Dettagli in `INTEGRATION_PLAN.md` sezione 10. Inverte la regola attuale di `AGENTS.md` e dei test «intento vince».
6. **`content_type=series` esclude il RAG** anche con descrizione di trama; guardia deterministica; stessa precedenza per tutti i campi.
7. **Test live autorizzati** senza richieste preventive, quando l'architettura è pronta (batteria in `INTEGRATION_PLAN.md` sezione 10), incluso `run_routing_eval --live`. Esclusi gli usi di YouTube (quota 100/giorno); Cohere trial: pause.

8. **Batteria live obbligatoria** (62 domande A–H, `eval/battery.json`) eseguita su **entrambi** i RAG con giudice cieco e A/B randomizzato, strategie di esclusione applicate a entrambi per separare dataset e algoritmo; criterio centrale: un risultato con la caratteristica negativa (es. soprannaturale) è una violazione anche se il titolo escluso manca. Protocollo in `INTEGRATION_PLAN.md` 10.6. Non ancora eseguita.

## 1. Vincoli assoluti (da rispettare sempre) **[D]**

1. **Nessuna chiamata API a pagamento senza autorizzazione esplicita**: né LLM, né embedding, né rerank, nemmeno una query di test. Se serve, descrivere cosa e quanto costa e **fermarsi prima**.
2. **Nessun commit** (né push) senza richiesta esplicita. Stato git: HEAD `28889cc` ("reso più marcato il tono Homie"); `tool/RAGWikipediaFilm/` è tutta non tracciata (`git status`: `?? tool/RAGWikipediaFilm/`).
3. **Non modificare le collezioni** `netflix_scout` (42.522 punti, vecchio RAG), `wikipedia_films_it` (v1, 41.438 punti) e `wikipedia_films_it_v2` (41.137 punti) senza autorizzazione. `indexing/settings.py: assert_own_collection` ammette solo v1, v2 e le collezioni `test_wikipedia_*`.
4. **Non reindicizzare né ricalcolare embedding** senza necessità e autorizzazione. I vettori verificati si riusano per `film_id` e hash del testo.
5. **Non integrare due RAG** (niente facciata, RRF, crosswalk, doppia fonte, fallback al vecchio).
6. **Non modificare frontend, orchestratore (`orchestrator.py`), `app.py`, `web_api/`, `preferences/`, `presenters/`, `tool/rag/`** prima della fase prevista e senza approvazione. Ogni modifica a prompt/istruzioni del planner cambia il comportamento del prodotto.
7. **Preservare i dati originali e la ricostruibilità**: `data/processed/films.jsonl` (SHA-256 `684959213d86f0167c4fc08deacc7bda8da1c7504b4726d3b5c094557004949d`) e lo snapshot Wikidata non si modificano; ogni correzione è derivata, riproducibile e reversibile.
8. **Non leggere, stampare né modificare `.env`.** Gli script di embedding usano `python-dotenv` dentro la libreria; la chiave non va mai in log o in output.
9. `AGENTS.md` (root) richiede: aggiungere/aggiornare test per ogni modifica di logica, eseguire il comando di test elencato prima di chiudere un task, non lanciare script a pagamento senza permesso, non toccare `buildSemanticDb.py`/`dbVettoriale/`/`dataset/` senza permesso, non cambiare modelli/versioni/prompt di sistema senza permesso. `AGENTS.md` descrive ancora il vecchio RAG ed è fuori dalla cartella consentita: va riscritto solo a integrazione fatta.
10. Non eliminare nulla di quanto non sia già deciso (il vecchio RAG si elimina solo in Fase 6 del piano, dopo conferma).

## 2. Stato del progetto: cosa è stato fatto (Fasi 1–8) **[V]**

| Fase | Contenuto | Esito |
|---|---|---|
| 1 | Dump Wikipedia `20261101` → `films.jsonl` con metadati Wikidata, riproducibile | 4.154.227 pagine lette, **41.421 film con trama**; arricchimento 829/829 blocchi, 0 rifiutati; ricostruzione offline a rete bloccata identica byte per byte (0 richieste); `pipeline verify` OK |
| 2 | Benchmark (token, strategie A/B/C, `small` vs `large`, retrieval, costi) | `PHASE2_BENCHMARK.md`; scelta: trama integrale + `text-embedding-3-large` a 1.536 dim; costo 3,07 USD |
| 3 | Embedding completi + collezione `wikipedia_films_it` (v1) | 41.438 unità (5 trame oltre 8.191 token spezzate in 17 chunk aggiuntivi), 3,1105 USD, 326 shard |
| 4 | Audit dell'intero catalogo | 41.091 film, 259 non film, 71 dubbi; difetto di estrazione in 25 trame; anomalie dei metadati |
| 5 | Campionamento dei 1.319 film a confidenza non alta; revisione dei 71 dubbi | tasso di falsi positivi ≈ 1%; errore sistematico: miniserie classificate film TV |
| 6 | Rilettura di 27 dubbi, 46 ibridi, 259 esclusioni, 25 trame; script di pulizia | 8 esclusioni da rivedere; `build_clean` deterministico e reversibile |
| 7 | Riconciliazione, dataset pulito, collezione v2 | 41.137 film; 25 embedding nuovi (0,003492 USD); 41.137 punti verificati uno per uno |
| 8 | Verifica finale, strategia d'uso, preferenze negative, piano di sostituzione | `RAG_USAGE_STRATEGY.md`, `INTEGRATION_PLAN.md`, `indexing/negative*.py`; nessuna modifica all'applicazione |

### 2.1 Dataset **[V]**

| | Originale | Pulito |
|---|---|---|
| File | `data/processed/films.jsonl` | `data/clean/films.clean.jsonl` |
| Record | 41.421 | **41.137** |
| Byte / SHA-256 | 130.333.071 / `684959213d86f0167c4fc08deacc7bda8da1c7504b4726d3b5c094557004949d` | 131.526.398 / `a22ae050cace8231e9c7c0733b1bf6123a8295cd6776ddac14e15eb98f5860db` |

Altri file in `data/clean/`: `excluded.jsonl` (284 esclusi interi, SHA-256 `c7ab7216…9dca`), `excluded_list.json` (motivi), `unverified.json` (65), `corrections.json` (25 trame con hash dell'originale e del nuovo testo), `category_counts.json`, `clean_manifest.json` (conteggi e SHA-256 di tutte le entrate e uscite). Entrate fisse: `audit/exclusions.json` (SHA `bef91023…038b`), `data/audit/section_fix.jsonl` (SHA `f296c4c0…9e14`), `audit/plan_overrides.json` (SHA `2d04723c…5ed3`).

Decisioni applicate (`audit/decisions_manifest.json`, 377 record, una decisione per `film_id`, sovrapposizioni tra le liste tutte vuote):
- **Esclusi 284** = 251 delle 259 non film certi (63 miniserie, 63 manga, 25 voci di genere, ecc.) + 18 dubbi (serie anime/miniserie/progetti non realizzati) + 14 ibridi serie/film + 1 fumetto (*Lobo Paramilitary Christmas Special*, non nell'elenco approvato: derivato dalla regola «opere non cinematografiche»).
- **Inclusi verificati decisi 28**: 4 film reinseriti dalle 259 (*Tsumi no yohaku*, *Kurai tokoro de machiawase*, *Gli amori di Suzanna Andler*, *Jesus Christ Superstar Live in Concert*), *Dive!!*, 23 ibridi film.
- **Inclusi `unverified` 65** (campo `catalog_status = "unverified"`, `unverified = true` nel payload): 44 dubbi non riesaminati + 8 dubbi in sospeso + 9 ibridi in sospeso + 4 incerti reinseriti (*Another*, *Il vento dell'Amnesia*, *The Connection*, *Fantaghirò (miniserie televisiva)*). Interpretazione mia di «mantieni i 4 incerti… contrassegnandoli come non verificati» = inclusi e non verificati; per escluderli togliere gli id da `reinstate` in `reconcile.py`/`plan_overrides.json`.
- **25 trame corrette**: sezioni estranee (produzione, personaggi, accoglienza…) tolte; eccezione manuale *Nero-Fumo e i sette nani neri* (sezione «Trama» di 2.030 caratteri, la Fase 1 aveva preso «Storia»); *Final Fantasy* tiene «Temi affrontati»; ripulite `<ref>`, `''`. Nessuna trama supera 8.191 token (massimo 7.761). *Il re leone* e *Quinto potere* ora sono un solo punto.
- Categorie incluse (audit): lungometraggi 35.113, corti 3.430, animazione 1.309, film TV 901, muti 209, speciali TV 29, home video 28, serial 7, documentari 3, non rilasciati 14, musicali 7, sconosciuti 26, dubbi 53, altro 8 (i 65 `unverified` sono distribuiti in queste categorie).
- Copertura metadati: Wikidata 99,9%, IMDb 99,2%, regista 98,7%, cast 90,7%, durata 91,7%; 70 senza anno. Film per anno: ~700 all'anno nel 2010–2019, 500 (2020), 410 (2024), 374 (2025), 188 (2026): copertura recente incompleta.

### 2.2 Collezioni Qdrant (server 1.20.0 su `127.0.0.1:6333`, `./scripts/start_qdrant.sh`) **[V]**

| Collezione | Funzione | Punti | Disco | Stato |
|---|---|---|---|---|
| `netflix_scout` | **vecchio RAG** (CMU 2012, `text-embedding-3-small`), usato dall'app | 42.522 (216 non sono trame) | ≈ 480 MiB | intatta; digest SHA-256 degli id `e664e24febc30fb2486fd5aca89a0cc0e0e6357db28a711f471859ca99cf2600` |
| `wikipedia_films_it` (v1) | prima collezione Wikipedia, 41.421 film + 17 chunk, **contiene ancora i 284 esclusi** | 41.438 | 514,1 MiB | intatta; digest SHA-256 degli id `2f4d5dcd38355050cf05cd965e0e5d54cac5e97334b023f38a26164d3996796c`; da non usare, eliminabile solo con autorizzazione |
| **`wikipedia_films_it_v2`** | **collezione definitiva** del nuovo RAG | **41.137** (uno per film, nessun chunk) | 536,3 MiB | green; creata e verificata |

v2: cosine, 1.536 dimensioni float32, HNSW m=16 ef_construct=100, payload su disco, WAL 32 MB, nessuna quantizzazione; id punto `uuid5(namespace, "<film_id>:0")`; indici di payload: `film_id`, `wikipedia_page_id`, `year`, `genres`, `country`, `language`, `director_names`, `imdb_id`, `title_norm`, `chunked`, `catalog_status`, `unverified`. Payload = intero record del film (trama, regia, cast con personaggi, durata, paese, lingua, generi, IMDb, Wikidata, URL Wikipedia, `synopsis_original_sha256`) + `unit_id`, `chunk_index`, `chunk_count`, `title_norm`, `director_names`, `actor_names`, `catalog_status`, `unverified`. **Non esiste un campo "tipo di opera".** Ripartizione disco v2 vs v1 (MiB): vettori 241,1 vs 242,8; payload 106,7 vs 102,9; indici di payload 119,5 vs 99,2 (+20,3 per i due indici nuovi); WAL 64 (costante, non sono dati). I «549 MB» erano KB decimali della v2, i «514 MB» MiB della v1.

Verifiche di Fase 7 (ripetute in Fase 8): punti = record = 41.137; ogni punto confrontato con il suo record (vettore, titolo, anno, trama, stato): 0 errori; 0 esclusi presenti; 25 vettori nuovi corrispondono ai nuovi testi; filtro `unverified=true` → 65, `false` → 41.072.

### 2.3 Embedding e costi **[V]**
Modello `text-embedding-3-large`, parametro API `dimensions=1536` (equivale a troncare e rinormalizzare, coseno 0,9997–1,0). Limite input 8.191 token. Costi sostenuti in tutto il progetto: Fase 2 benchmark **3,07 USD** (budget 5), Fase 3 embedding **3,1105 USD** (23.927.168 token, 1.810 s) + giudice LLM **0,105 USD**, Fase 7 **0,003492 USD** (26.864 token, 1 richiesta, 4,3 s); Fase 8: **0**. Totale ≈ **6,29 USD**. Vettori in `data/embeddings/itwiki-20261101-large1536/shards/` (326 shard, 246 MB, manifest `manifests/embeddings_manifest.json`, plan hash `1a7b22fa…79e`) e i 25 nuovi in `data/embeddings/itwiki-20261101-large1536-v2/new_vectors.npz` (richiesta `req_a21c768a9a4747a480a0ad093c43101b`).

### 2.4 Benchmark della v2 **[V]**
72 query di Fase 2 (embedding in cache `data/embeddings/…/queries/phase2_queries_large1536.npy`) contro il film sorgente: v2 Hit@5/Hit@10/MRR@10 = 0,167/0,181/0,106 (v1: 0,153/0,181/0,105); sovrapposizione top 10 v1–v2 99,4%; non film nella top 10: 4/720 (v1) → 0 (v2). Valori assoluti bassi per costruzione (41× più distrattori del pool di Fase 2); i giudizi LLM coprono solo il 3% delle top 10, quindi non misurano la qualità reale. Le query di genere/formato **con testo nuovo non sono state rilanciate** (embedding a pagamento); come proxy, usando come query i vettori di 236 pagine escluse: v1 20,7% di risultati esclusi nella top 10 (489/2.360), v2 0. I 25 testi corretti sono recuperati al primo posto dal proprio nuovo vettore (coseno vecchio→nuovo: minimo 0,61, mediana 0,80).

### 2.5 Test **[V]**
- `python -m pytest tool/RAGWikipediaFilm/tests -q` → **97 passati** (pipeline Fase 1, indicizzazione, audit, `build_clean`, riconciliazione/v2, `negative`; i test su server reale sono in sola lettura e saltano senza server).
- Suite del progetto (comando di `AGENTS.md` §4) → **2.067 passati**.
- `pipeline verify` (Fase 1) OK; `audit.build_clean verify` OK; `indexing.v2 check` OK.

### 2.6 Stato effettivo della pipeline **[V]**
Fase 1 completa e verificata (`pipeline verify`: «the build matches the manifest»). Nulla è in esecuzione. Il Qdrant locale è acceso; per riaccenderlo: `./scripts/start_qdrant.sh` dalla radice. Python: `.venv` del progetto (3.11), con `mwparserfromhell==0.7.2`, `tiktoken` (`tool/RAGWikipediaFilm/indexing/requirements.txt`), `numpy`, `qdrant-client==1.20.0`.

## 3. Comandi (dalla radice del repository, `source .venv/bin/activate`)

```bash
# verifiche gratuite e offline
python -m tool.RAGWikipediaFilm.pipeline verify
python -m tool.RAGWikipediaFilm.audit.reconcile                  # riscrive audit/decisions_manifest.json e plan_overrides.json
python -m tool.RAGWikipediaFilm.audit.build_clean build          # genera data/clean/* (6 s, nessuna rete)
python -m tool.RAGWikipediaFilm.audit.build_clean verify         # ricostruzione byte per byte + reversibilità
python -m tool.RAGWikipediaFilm.indexing.v2 plan                 # cosa si riusa e cosa va embeddato (nessuna API)
python -m tool.RAGWikipediaFilm.indexing.v2 check                # solo lettura su Qdrant
python -m tool.RAGWikipediaFilm.indexing.v2_eval                 # 41.137 punti contro i record + 72 query (cache), nessuna API
python -m tool.RAGWikipediaFilm.indexing.negative_eval           # 11 scenari di preferenze negative, nessuna API
python -m pytest tool/RAGWikipediaFilm/tests -q
# a pagamento / scrivono: SOLO con autorizzazione esplicita
python -m tool.RAGWikipediaFilm.indexing.v2 embed                # embedda solo i testi nuovi (tetto 0,01 USD nel codice)
python -m tool.RAGWikipediaFilm.indexing.v2 index                # crea wikipedia_films_it_v2 (rifiuta se esiste)
```
Scansioni del dump locale (nessuna rete, 12–20 min ciascuna): `audit.section_scan`, `audit.section_detail`, `audit.category_probe`.

## 4. Decisioni architetturali definitive **[D]**
1. Un solo RAG attivo: Wikipedia v2. Nessun retriever parallelo, nessuna fusione (RRF), nessuna tabella di corrispondenza tra dataset, nessun ripiego al vecchio.
2. Il vecchio RAG (`tool/rag/`, `netflix_scout`, `dataset/MovieSummaries`, `buildSemanticDb.py`) resta intatto fino alla verifica nell'applicazione; si elimina solo dopo una migrazione riuscita (Fase 6 del piano) e con conferma.
3. Nessuna integrazione è stata eseguita; la collezione v2 non è letta dall'app.
4. `films.jsonl` non si modifica mai; il catalogo definitivo è derivato (`data/clean/`).
5. I casi non verificati restano nel dataset con un campo esplicito filtrabile (`unverified`).
6. Regole di contenuto: cortometraggi, documentari, animazione, film TV e muti si mantengono; serie, miniserie, manga, anime-serie e opere non cinematografiche si escludono; i film TV in due serate sono inclusi solo se sono un'unica opera, le miniserie con episodi distinti sono escluse; le pagine anime la cui trama descrive la serie e non il film collegato sono escluse; nessun film si elimina per anomalie di anno, titolo o sinossi.

## 5. Nuova strategia di utilizzo del RAG **[P — documento completo: `RAG_USAGE_STRATEGY.md`; nulla è ancora applicato]**

**Principio [D]:** non ereditare le limitazioni del vecchio RAG. Le regole attuali (`app.py`, `CONFIG["orchestrator"]["instructions"]` regola 3: «corpus vecchio, fermo al 2012… SOLO se la richiesta non contiene titolo, regista, attore, periodo dopo il 2012»; `data_coverage.rag_search = 2012`; `rag_enrichment` TMDb su 3 candidati; query riscritta in inglese; `fallback_tool = rag_search`) vanno ripensate, non rattoppate con eccezioni.

**Cosa è il nuovo RAG [V]:** ricerca semantica su 41.137 film (trama in italiano) con filtri sui metadati (anno, paese, genere, regista, durata, `unverified`); solo film; non è fonte di dati aggiornati o completa (copertura recente ridotta); campi per ogni risultato: titolo, titolo originale, anno, regia, cast (con personaggi, non sempre), durata, paese, lingua, generi, trama, IMDb, Wikidata, URL Wikipedia; mancano poster, streaming, trailer, voti, recensioni.

**Quando usarlo [P]:** raccomandazioni; ricerca per trama, tema, emozione, atmosfera, genere, ambientazione, epoca, stile; «film come X» / «simili a X» (X film → esempio positivo, non più solo `tmdb_search similar`); riconoscere un film dalla trama; ricerche semantiche con vincoli su regista, attore (`actor_names` nel payload ma **non indicizzato**), anno, paese, genere, durata; preferenze negative. Un titolo, una persona o un anno **non lo escludono più**.

**Quando NON usarlo [P]:** elenchi completi o filmografie ordinate; novità, uscite, «ultimi film»; voti e classifiche; dove vederlo; trailer; cast completo; dati ufficiali di un titolo specifico; punteggi; **qualunque richiesta di serie TV**.

**Ruolo degli altri strumenti [P]:** TMDb per dati aggiornati/strutturati (streaming, trailer, immagini, voto del pubblico, cast completo, uscite, trending, filmografie, collezioni, **serie**, film assenti dal catalogo) — **non** richiamato dopo il RAG per titolo/regia/cast principale/anno/durata/paese/generi/sinossi, che sono nel payload; movie_db_search (voti, classifiche; non distingue film e serie); omdb_search (punteggi; l'`imdb_id` del RAG evita la ricerca per titolo); wikipedia_search (prosa; `wikipedia_url` già noto); wikidata_search (relazioni; `wikidata_id` già noto); tvmaze_search (dati di serie); youtube_search (video). Le sezioni da riscrivere (regola 3, richiamo nella regola 1, `data_coverage`, `final_instructions`, `CONTENT_PLANNER`, `SOURCE_TOOLS`) hanno bozze in `RAG_USAGE_STRATEGY.md` sezione 6.

**Meno chiamate:** niente `tmdb_search` inutile dopo il RAG; decisione aperta sulle schede web (punto 3 della sezione 8).

**Limiti e problemi ancora da risolvere:** catalogo meno completo dopo il 2019; assenza di `work_format`; `genres` è testo libero di Wikidata (anche «anime e manga…» su film veri); le schede della lista web (`web_lists`) dipendono dall'arricchimento TMDb (poster); la strategia **non è stata provata con un LLM**; `AGENTS.md` descrive ancora il vecchio RAG.

### 5.1 Film e serie TV **[V sui dati, P sulle regole]**
- Il dataset è un catalogo di **film**. Non ho trovato serie TV evidenti tra i verificati. Restano **70 record con classi Wikidata miste** (una classe di serie/miniserie/anime/manga/OVA accanto a una di film): 39 `unverified` e **31 verificati** (i 23 ibridi decisi come film più altri come *Tomie: Another Face*; elenco in `audit/series_class_hybrids.json` per i 46 ibridi, decisioni in `audit/decisions.json`). Due titoli con suffisso di serie/manga, entrambi `unverified` (*Fantaghirò (miniserie televisiva)*, *Orange (manga)*). Circa 30 dei 65 `unverified` sono pagine di anime/manga/OVA o opere TV dubbie, gli altri film veri (live-action da manga ecc.).
- **Il formato non è filtrabile in modo affidabile oggi:** nel payload c'è solo `genres` (366 etichette che citano TV/serie/anime/manga, presenti anche su film veri) e `unverified`. Il formato dell'audit (`film/short/tv_film/animated/…`) sta solo in `data/audit/classification.jsonl`, non in Qdrant. **Serve distinguere chiaramente i formati** → proposta `work_format` + `format_confidence` + `franchise_id` (decisione 2 della sezione 8).
- Pagine anime con infobox «Film» di un film collegato ma trama della serie (es. *Digimon*, *Marmalade Boy*, *Hana yori dango*, *Tsurune*, *Baldios*) sono escluse (~9): i film collegati non esistono come voci autonome (limite dell'estrazione di Fase 1, non risolto).
- **Regole [P, da confermare con le decisioni 5 e 3]:** richieste di film → RAG ammesso; **richieste esclusivamente di serie → il RAG cinematografico non si usa mai come fonte di raccomandazione, nemmeno se l'utente descrive trama, genere o atmosfera, né con impostazioni persistenti (`content_type = series` in `preferences/`) che chiedono solo serie**; richieste miste → RAG per la parte film e TMDb/TVmaze per le serie, liste separate; né film né serie con `both` (default) → due liste distinte; l'intento esplicito prevale sulla preferenza (come oggi); titolo ambiguo → la preferenza risolve, RAG solo se è un film. `preferences/behavior.py` già dice di non usare `rag_search` per le serie; va esteso al caso «descrizione di trama». I record `unverified` si dichiarano solo se pertinente.

### 5.2 Preferenze positive e negative **[P — implementazione di prova in `indexing/negative.py`; risultati in sezione 6]**
1. Il parser produce `like`, `avoid_titles`, `avoid_genres` (vocabolario chiuso del catalogo), `avoid_descriptions` (tratti narrativi da evitare **scritti in positivo**: «molti combattimenti», mai «senza combattimenti»: l'embedding non capisce la negazione) e filtri.
2. Esclusione per ID sempre (titoli citati, positivi e negativi). Non basta: restano sequel e remake.
3. Penalità semantica sul pool: 200 candidati per il positivo, punteggio `cos(r, P) − λ·max_i cos(r, N_i)` con **λ = 0,5** per film da evitare.
4. Generi da evitare = filtro `must_not` su `genres` (l'unico che azzera le violazioni).
5. Tratti narrativi: negativo da descrizione positiva (embedding di una frase breve, costo trascurabile) come penalità; la verifica spetta a reranker e vincoli (`constraint_summary`, «contraddetto/non verificabile»).
6. Da evitare: sottrazione a peso pieno (α=1), `recommend best_score` con negativi che sono concetti, `average_vector` come unico meccanismo.
7. Un film citato assente dal catalogo: trama TMDb embeddata **in memoria**, mai scritta nella collezione (il vecchio `reference_flow` scriveva punti `tmdb:`).

## 6. Test sulle preferenze negative eseguiti (nessuna chiamata API) **[V]**
`python -m tool.RAGWikipediaFilm.indexing.negative_eval` (codice `indexing/negative_eval.py`, libreria `indexing/negative.py`, risultati in `data/embeddings/itwiki-20261101-large1536-v2/negative_eval.json`, 6 test in `tests/test_negative.py`). 11 scenari su film reali; esempi e concetti sono vettori di film reali o centroidi di gruppi di film scelti su metadati/testo (sostituiscono l'embedding del testo, che non si poteva fare). Metriche = proxy oggettivi, **nessun giudice umano né LLM**.

Scenari: (1) fantascienza senza esclusioni; (2) fantascienza diversa da *Star Wars*; (3) diversa da *Star Wars* e *Matrix*; (4) fantasy senza *Harry Potter* né *Il Signore degli Anelli*; (5) come *Blade Runner* senza cyberpunk; (6) come *Alien* ma non horror; (7) come *Matrix* senza combattimenti; (8) come *Interstellar* ma non come *Gravity*; (9) *Interstellar* e *Inception*, non *Gravity* né *Star Wars*; (10) come *Alien*, diverso da *Predator*; (11) *Blade Runner* e *Terminator*, non *Matrix*.

| Strategia (medie su 11 scenari) | Perdite (franchise/titoli citati) | Violaz. genere /10 | Violaz. testo | Coseno positivo | Coseno negativo |
|---|---|---|---|---|---|
| Solo positivo | 0,27 | 6,5 | 3 | 0,778 | 0,681 |
| Esclusione per id | 0,09 | 6,5 | 3 | 0,777 | 0,674 |
| Sottrazione 0,5 ≈ `recommend` average | 0 | 6,0 | 3 | 0,759 | 0,605 |
| Sottrazione 1,0 | 0 | 3,5 | 3 | **0,633** | 0,433 |
| `recommend` best_score | 0 | 5,0 | 0* | 0,674 | 0,563 |
| Penalità sul pool λ=0,5 | 0 | 6,0 | 3 | 0,759 | 0,608 |
| Penalità λ=1,0 | 0 | 5,0 | 3 | 0,730 | 0,563 |
| Filtro sui metadati del genere (2 scenari) | 0 | **0** | – | 0,673 | – |

\* con negativi-concetto restituisce film scollegati (coseno positivo 0,15–0,19): non è un successo.

Esempi concreti: «come *Interstellar* ma non *Gravity*»: il solo positivo restituisce *Gravity* nella top 3; penalità 0,5 lo sostituisce con *Inception*; penalità 1,0 allontana troppo (*Chaos Walking*, *Ritorno al futuro III*). «Come *Alien*, diverso da *Predator*»: con la sola esclusione per id compare ancora *Predator 2*; penalità 0,5 lo toglie, penalità 1,0 produce fantascienza lontana (*Dark Star*, *L'aereo più pazzo del mondo*). «Come *Alien*, ma non horror»: 10 horror su 10 anche con la penalità 0,5 (8 con 1,0): *Alien* è simile ai film horror proprio perché lo è; con il filtro sui metadati 0 violazioni (*The Black Hole*, *Species III*…). «Come *Blade Runner* senza cyberpunk»: il filtro toglie *Blade Runner 2049* (cyberpunk), la penalità no; la richiesta è in parte contraddittoria e va segnalata. «Come *Matrix* senza combattimenti»: 3 film su 10 con almeno tre riferimenti a combattimenti anche con λ=1,0.

**Problemi individuati:** la penalità non elimina un genere; l'assenza di un tratto narrativo non è rappresentata bene dagli embedding; la sottrazione piena rovina la rilevanza; «fantascienza» e «fantasy» sono stati proxy con centroidi di genere, quindi gli scenari 1–4 non discriminano molto (la perdita di *Star Wars* non compare nemmeno nel baseline).

**Esperimenti ancora necessari (a pagamento, non eseguiti):** (a) embedding di ~20 frasi brevi in italiano (scenari e descrizioni in positivo dei tratti da evitare), ~600 token, **≈ 0,0001 USD** [stima]; (b) giudice LLM sulla pertinenza della top 10 (11 scenari × 6 strategie × 10 film ≈ 660 giudizi), **≈ 0,15–0,25 USD** con `gpt-5.6-luna` [stima mia dai prezzi di Fase 2, non misurata]; (c) valutazione di qualità nuovo-contro-vecchio RAG e `run_routing_eval --live`: **costo ancora da stimare** (da stimare prima di chiedere il permesso).

## 7. Il piano di sostituzione: file coinvolti (`INTEGRATION_PLAN.md`) **[P]**

| Componente | Cambio previsto |
|---|---|
| `store/settings.py`, `CONFIG["rag"]["vectorstore"|"embedding"]` (`app.py`) | collezione `wikipedia_films_it_v2` (poi alias), `text-embedding-3-large`, `dimensions=1536`; `ensure_collection_ready` |
| `embeddings.py` | parametro `dimensions`; cache della query |
| `store/collection.py`, `vectorstore.py`, `models.py` (`RagChunk`) | payload nuovo, un punto per film, campi regia/cast/durata/paese/ID/`unverified` |
| `retrieval.py` | niente query in inglese: si embedda il testo dell'utente; parser con `like`, `avoid_titles`, `avoid_genres`, `avoid_descriptions`, filtri; via `genre_boost` e mappa generi CMU |
| `constraints.py`, `rerank.py` | vincoli sui metadati reali; parole chiave italiane; documento per il reranker dal payload (Cohere v3.5 è multilingue) |
| `references.py`, `reference_flow.py` | risoluzione nella v2 per `title_norm`/anno/`imdb_id`; film assente → trama TMDb embeddata in memoria, mai scritta |
| `store/catalog.py`, `catalog_enricher.py`, `CONFIG["catalog"]`, `app.build_catalog_enricher`, `tool/tmdb/film_record.py` | **rimozione** (scrivevano punti `tmdb:` nella collezione) |
| `hybrid.py` (BM25) | rimosso nella prima versione (decisione 4) |
| `tool_interface.py` (`RagToolInput`) | argomenti `like`, `avoid_*`, `filters`, `k_finale`; schema < 3.500 caratteri |
| `tool/tmdb/enrich.py` (`TmdbRagEnricher`) | solo su richiesta e per `imdb_id` (`/find`), non per titolo (decisione 3) |
| `indexing/negative.py` | promosso a modulo del retrieval |
| `data_coverage.py`, `tests/test_data_coverage.py` | misura da `films.clean.jsonl` |
| Istruzioni (`app.py`), `preferences/behavior.py`, `routing_cases.py` | riscritte (bozze in `RAG_USAGE_STRATEGY.md`) |
| Test da adattare | `test_retrieval`, `test_rag_constraints`, `test_rerank_query`, `test_rerank_avoid`, `test_answer_constraints`, `test_reference_*`, `test_qdrant_*`, `test_tool_contract`, `test_data_coverage`, `test_tmdb_enrich`, `test_orchestrator`, `test_presenters`, `test_movie_db_routing_eval`, `web_lists/…` |
| Da rimuovere in Fase 6 | `tool/rag/EmbeddingProcess/`, `buildSemanticDb.py`, `movie_metadata.py`, `dataset/MovieSummaries`, `docs/qdrant_migration/`, `tests/test_build_semantic_db.py`, test del catalogo TMDb→Qdrant, collezione `netflix_scout` (backup e conferma) |

## 8. Decisioni (STORICO: **risolte il 2026-11-04**, vedi sezione 0bis)

1. **[A] Aftershock e i tre non determinabili.** Dal dump locale (`audit/two_part_review.json`): *Il processo di Norimberga* («miniserie», sezioni «Prima/Seconda puntata»), *Padre Pio – Tra cielo e terra* («miniserie», «Primo/Secondo episodio») e *I guardiani del cielo* («miniserie in due puntate», categoria miniserie) restano **esclusi, confermati**. *Aftershock – Terremoto a New York*: la pagina dice «film TV», una sola «Trama» → **da includere** (correzione proposta, non applicata: richiede di aggiungere un punto a v2/v3, vettore già disponibile, costo 0; film 41.138). *La storia di Anne Frank* («miniserie… 20 e 21 maggio» ma anche «un film controverso»), *Atomic Train* e *Attila l'unno* (lead «miniserie», una sola «Trama», categorie di film): **non determinabili**, lasciati esclusi e segnalati. Domanda: includere *Aftershock*? Lasciare esclusi gli altri tre?
2. **[A] `work_format`, `format_confidence`, `franchise_id` nel payload:** nuova collezione v3 (costruita con `build_clean` esteso, vettori riusati, nessun nuovo embedding) oppure aggiornamento del solo payload della v2? Serve per distinguere formati e per escludere sequel/franchise. (`franchise_id` da Wikidata P179/P8345 già nello snapshot.)
3. **[A] Arricchimento TMDb per `imdb_id` e poster:** le schede della lista web (`web_lists`) oggi usano gli elementi TMDb dei candidati; senza arricchimento perdono il poster. Arricchimento leggero per `imdb_id` (una `/find` per film) solo nei turni che producono schede, oppure schede senza poster?
4. **[A] Rimozione di BM25 (`hybrid.py`)** nella prima versione del nuovo retriever (la ricerca per parole concrete passerebbe, se serve, da un filtro testuale Qdrant).
5. **[A] Esclusione del RAG per `content_type=series`**, anche quando l'utente descrive trama, genere o atmosfera (proposta: sì; l'intento esplicito dell'utente prevale sulla preferenza).
6. **[A] Autorizzazione ai test a pagamento della strategia.** Stime: embedding dei test **≈ 0,0001 USD**; giudice LLM **≈ 0,15–0,25 USD**; confronto di qualità nuovo/vecchio RAG e `run_routing_eval --live`: **da stimare** (la stima va preparata e presentata prima di chiedere il permesso).

Altre scelte mie da tenere d'occhio **[P]**: i 4 incerti reinseriti come `unverified`; *Lobo* escluso; i casi di confine del campionamento rimasti verificati (*La notte quando è morto Pasolini*, *Il giovane Mussolini*, *Vette di libertà*, *2 Girls 1 Cup*, *Rabbits*, *Grachi Sweet 16*).

## 9. Piano delle fasi (`INTEGRATION_PLAN.md`, sezioni 7–8) **[P — nessuna fase avviata]**

| Fase | Contenuto | Dipende da | Criterio di uscita |
|---|---|---|---|
| **0** | Eventuale alias `wikipedia_films_it` → v2; chiusura delle decisioni aperte (sezione 8) | decisioni utente | approvazione |
| **1** | Retriever nuovo dietro un flag (`rag.backend = "wikipedia"`), **unica fonte attiva** quando acceso (il vecchio codice resta inattivo, non esistono due retriever); test offline adattati (mock) | Fase 0 | test offline verdi |
| **2** | Parser dei segnali (`like`, `avoid_*`, filtri), vincoli sul payload, reranker; test degli scenari negativi | Fase 1 | scenari superati |
| **3** | Nuove istruzioni del planner e `RagToolInput`; `routing_cases.py`; `run_routing_eval --live` (a pagamento, permesso) | Fase 2, decisioni 3–5, 6 | routing ≥ baseline attuale (23/23 + nuovi casi RAG) |
| **4** | Valutazione di qualità nuovo-contro-vecchio su richieste reali fisse (giudice LLM, a pagamento) | Fase 3, decisione 6 | criteri qui sotto |
| **5** | Spegnere il vecchio RAG (flag), verifica nell'applicazione (terminale e web) | Fase 4 | nessuna regressione |
| **6** | Rimozione del vecchio RAG (codice, test, CMU, `netflix_scout` previo backup e conferma), pulizia di `AGENTS.md`, `README.md`, `mappa.html` | Fase 5 + conferma utente | suite completa verde |

**Criteri oggettivi di riuscita:** (1) 72 query: Hit@5/@10/MRR non inferiori a 0,167/0,181/0,106 e precisione@5 della v2 ≥ vecchio RAG sulle stesse richieste (giudizi LLM); (2) scenari di preferenze negative: 0 violazioni per titoli e generi esclusi, rilevanza al positivo non inferiore di più di 0,03 di coseno medio al solo positivo; (3) routing: tutti i casi esistenti più nuovi (film simili con titolo, persona + tema, serie con trama descritta → niente RAG) corretti; (4) 0 serie TV tra le raccomandazioni di film su un set fissato e 0 chiamate al RAG con `content_type=series`; (5) chiamate esterne medie per turno di raccomandazione non superiori alle attuali; (6) `netflix_scout` e `wikipedia_films_it` non scritte dall'applicazione, `check` della v2 verde; (7) latenza di una ricerca entro il valore attuale. **Integrazione riuscita** quando 1–7 sono soddisfatti nell'applicazione reale (terminale e web) e nessun percorso attivo importa più il vecchio RAG.

## 10. Cosa fare nella prossima sessione (STORICO; il piano vigente è `INTEGRATION_PLAN.md` sezione 10)
1. Leggere questo file, `PHASE8_REPORT.md`, `RAG_USAGE_STRATEGY.md`, `INTEGRATION_PLAN.md`. Verificare: `git status` (solo `?? tool/RAGWikipediaFilm/`), Qdrant acceso (`curl http://127.0.0.1:6333/collections` → tre collezioni), `python -m tool.RAGWikipediaFilm.audit.build_clean verify`, `python -m tool.RAGWikipediaFilm.indexing.v2 check`.
2. **Presentare all'utente le sei decisioni della sezione 8** (nell'ordine 1, 2, 3, 5, 4, 6) e aspettare le risposte. Non iniziare l'integrazione prima.
3. Con le risposte: applicare la decisione 1 (e 2 se approvata) modificando `reconcile.py`/`plan_overrides.json`, `build_clean build` + `verify`, costruire la nuova collezione solo su autorizzazione (nome da concordare: v3 o aggiornamento payload), poi la Fase 0 del piano.
4. Preparare e presentare la stima dei costi del confronto di qualità e del routing eval live prima di chiedere il permesso a pagamento.
5. Mantenere la regola: ogni passo si ferma e si presenta all'utente prima di toccare l'applicazione.

## 11. Mappa dei file (in `tool/RAGWikipediaFilm/`)

| Percorso | Contenuto |
|---|---|
| `README.md` | istruzioni della pipeline Fase 1, riproducibilità, sezioni 12 (Fase 3), 13 (audit), 14 (Fasi 5–8) |
| `PROGRESS.md` | **questo file** |
| `PHASE2_BENCHMARK.md`, `AUDIT_REPORT.md`, `AUDIT_NOYEAR_246.md`, `PHASE5_REPORT.md`, `PHASE6_REPORT.md`, `PHASE7_REPORT.md`, `PHASE8_REPORT.md` | rapporti storici di fase |
| `RAG_USAGE_STRATEGY.md`, `INTEGRATION_PLAN.md` | strategia d'uso e piano di sostituzione (proposte) |
| `pipeline.py`, `download.py`, `extract_films.py`, `clean_plot.py`, `wikidata_client.py`, `enrich_metadata.py`, `manifest.py`, `schema.py`, `config.yaml` | pipeline Fase 1 (non modificare; `config.yaml` ha uno SHA nel manifest) |
| `indexing/` | `settings.py` (modello, collezioni ammesse), `units.py`, `embed_run.py`, `shardio.py`, `verify_embeddings.py`, `qdrant_index.py`, `wiki_search.py` (Fase 3); `v2.py`, `v2_eval.py` (Fase 7); `negative.py`, `negative_eval.py` (Fase 8) |
| `audit/` | `classify.py`, `features.py`, `manual_review.py`, `run_audit.py`, `anomalies.py`, `section_scan.py`, `section_detail.py`, `category_probe.py`, `sample_review.py`, `sample_findings.py`, `doubtful_review.py`, `decisions.py`, `reconcile.py`, `build_clean.py`; dati: `exclusions.json`, `review_needed.json`, `synopsis_contamination.json`, `anomalies.json`, `series_class_hybrids.json`, `doubtful_review.json`, `decisions.json`, **`decisions_manifest.json`**, **`plan_overrides.json`** (in vigore), `two_part_review.json`, `sample_findings.json` |
| `benchmark/` | Fase 2 (risultati in `benchmark/results/`, ignorata da git) |
| `tests/` | 97 test |
| `data/` (ignorata da git) | `raw/` dump, `cache/wikidata/` snapshot, `processed/` (`films.jsonl`, `candidates.jsonl`), `audit/`, `clean/`, `embeddings/` |
| `manifests/` | `build_manifest.json` (Fase 1), `embeddings_manifest.json` (Fase 3), `build_manifest.example.json` |

Fuori dalla cartella e **da non toccare** senza approvazione: `tool/rag/`, `app.py`, `orchestrator.py`, `preferences/`, `presenters/`, `web_api/`, `web_lists/`, `data_coverage.py`, `catalog_enricher.py`, `tool/tmdb/enrich.py`, `scripts/start_qdrant.sh`, `AGENTS.md`, `dbVettoriale/`.

## 12. Correzioni ai rapporti storici (per evitare contraddizioni)

| Affermazione nei rapporti | Stato reale |
|---|---|
| Fase 3: 41.438 punti, «3 dei 5 film oltre il limite sono articoli di argomento» | vera per la v1; la v2 non li contiene e nessuna trama supera 8.191 token |
| Fase 4/5: «259 non film certi» | solo 251 reggono; 8 riesaminati (4 reinseriti verificati, 4 reinseriti `unverified`) |
| Fase 5: «Digimon & co.: errore di pagina»; «il `<ref>` di Final Fantasy sparisce col taglio» | l'infobox è di un film collegato mentre la trama è della serie; il `<ref>` non spariva: lo toglie `tidy()` in `build_clean` |
| Fase 5/6: «41.149» / «41.133» record | superati: **41.137** |
| Fase 6/7: *Aftershock* «miniserie NBC in due parti» | smentita dalla pagina («film TV»): vedi decisione 1 |
| `INTEGRATION_PROPOSAL.md` (facciata, RRF, crosswalk) | eliminato; vale `INTEGRATION_PLAN.md` |
| `audit/plan_overrides.proposed.json` (scenario consigliato di Fase 6) | eliminato; vale `audit/plan_overrides.json` |
| Fase 1 (storia): «arricchimento incompleto», «manifest obsoleto» | superati: arricchimento 829/829, manifest rigenerato e `verify` OK |

## 13. Storia tecnica della Fase 1 (ancora valida)

Esito: 4.154.227 pagine in ≈ 34,5 min, 41.421 film; arricchimento in 807 blocchi online, 17.642 s, 1.154 richieste (errori recuperati: 502, 429 con `Retry-After`, JSON non valido, timeout, un `IncompleteRead` ora trattato come transitorio); `films.jsonl` 130.333.071 byte; snapshot `itwiki-20261101-a` con 1.676 risposte (2,30 GB non compressi, 344 MB su disco, `content_sha256` `9aa29c98…df37`); ricostruzione offline con socket disabilitati: 0 richieste di rete, 4 min 53 s, identica. Dump `itwiki-20261101-pages-articles.xml.bz2` 4.286.436.387 byte, SHA-1 ufficiale `53d757d92a4f3956880586074008f08a08760641`. Termini del Query Service rispettati (una richiesta alla volta, ≥ 1 s, User-Agent, POST).

Modifiche tecniche principali: download con controllo di `Content-Length` e ripresa; prefiltro sul testo grezzo (estrazione 7× più veloce); etichette Wikidata via SPARQL (blocco ≈ 17 s invece di ≈ 100 s); date/durate segnaposto di Wikidata ignorate (fuori da 1850–2100 / 1–2000 minuti); checkpoint di `enrich` con impronta dell'input e `DERIVATION_VERSION = 2`; `verify` controlla ogni corpo dello snapshot. Limiti noti: soglie di trama 400 caratteri / 60 parole arbitrarie (38.424 pagine scartate); personaggi del cast presenti per pochi attori; riconoscimento per infobox `{{Film}}` (un'infobox Film in una sezione di una pagina di serie fa includere la pagina: origine del problema delle pagine anime); etichette miste italiano/inglese. Per riprendere/ricostruire da zero vedere `README.md` sezioni 6, 11 e 12; `RAGWIKI_WIKIDATA_CONTACT` va impostata per l'accesso online a Wikidata.

## 14. Esecuzione autonoma (2026-11-04) — Fasi A, B e C completate (integrazione NON eseguita)

**Fase A (dati e v3) — COMPLETATA [V].**
- `audit/reconcile_v3.py` → `audit/decisions_manifest_v3.json`, `audit/plan_overrides_v3.json` (file separati: il piano di v2 non è stato riscritto e `build_clean verify` resta valido). Aftershock incluso; Anne Frank, Atomic Train, Attila l'unno esclusi e segnalati «non verificati»; esclusi totali 283.
- `audit/franchise.py` (offline, dallo snapshot Wikidata; P8345, P179 con gruppi di 2–60 film, catene P155/P156): 4.049 film su 41.138 con `franchise_id`. Le liste grandi (Looney Tunes 222, Disney 158, registro cinematografico 94) non sono franchise e sono scartate; Alien e Predator risultano gruppi separati (Alien vs. Predator in entrambi); Rocky 9, Matrix 5, Scream 7, John Wick 5, Il padrino 3.
- `audit/build_v3.py` → `data/clean_v3/films.v3.jsonl` (41.138 film; `build_v3 verify` OK: ricostruzione byte per byte, differenza da `data/clean/` = solo Aftershock e i campi nuovi). Campi nuovi: `work_format`, `format_confidence`, `franchise_id`, `franchise_ids`, `franchise_size`, `franchise_basis`, `actor_names_norm`, `director_names_norm`, `original_title_norm`, `genres_norm`. `work_format`: feature 35.118, short 3.430, animated 1.309, tv_film 914, silent 209, tv_special 31, tv_related 32, video_film 28, unknown 28, unreleased 14, other 8, music_film 7, serial 7, documentary 3. Confidenza: high 39.770, medium 1.283, low 69, manual 16.
- `indexing/v3.py` → collezione **`wikipedia_films_it_v3`**: 41.138 punti, green, 0 chiamate di embedding (41.113 vettori dagli shard di Fase 3, 25 dal file di Fase 7; Aftershock riusato). Indici di payload in più: `actor_names`, `actor_names_norm`, `director_names_norm`, `original_title_norm`, `genres_norm`, `work_format`, `format_confidence`, `franchise_id`, `franchise_ids`, `catalog_status`, `unverified` e indice full-text (parola, minuscole, ascii folding) su `synopsis`. `indexing.v3 check`: ogni punto confrontato col record (vettore, titolo, anno, trama, campi nuovi): 0 errori, 0 mancanti, 0 esclusi presenti, Aftershock presente, filtri `unverified` 65, `work_format=feature` 35.118, franchise 4.049; **netflix_scout, v1 e v2 con lo stesso conteggio e digest degli id di prima**.
- Test: `tests/test_v3_data.py` (3). Suite RAGWikipediaFilm: 100 passati.

**Fase B (retriever autonomo) — `retrieval/`**: `models.py` (`Signals`), `llm.py` (cache su disco di LLM ed embedding), `parser.py` (una sola analisi della richiesta, uguale per i due corpus), `corpus.py` (accesso a v3 e a `netflix_scout` in sola lettura), `strategies.py` (S0, S1, S2n, S2f, S3, S3b, S4, S5, S6, vedi docstring). Non importato dall'applicazione.
- **Componente lessicale** (`eval/lexical.py`, `eval/results/LEXICAL_REPORT.md`, 40 domande da termini presenti in al più 2 trame; un solo ranking denso in ogni variante): solo denso hit@5 0,47; **filtro full-text di Qdrant + ordine denso hit@5 1,00 (hit@1 0,95)**; insieme di candidati BM25 ordinato dal denso hit@5 0,68; BM25 da solo 0,78. Decisione supportata dai dati: il lessicale entra come **filtro** (L1). Limite: il test dà il termine esatto; in produzione deve estrarlo il parser (`rare_terms`), non misurato. BM25/`hybrid.py` non servono e si rimuoveranno in Fase F.

**Fase C (confronto A/B live) — COMPLETATA [V]**, rapporto: `EVAL_REPORT.md` (dati grezzi in `eval/results/`, batteria originale `eval/battery.json` intatta, supplementare `eval/battery_extra.json`).
- Domande A–G (280 film per sistema): **NEW-S6 4% violazioni / 80% validi** contro **OLD-NATIVE 10% / 66%** (OLD-S6 4% / 70%; NEW-S0 47% / 35%; OLD-S0 37% / 29%). Risposte (giudice cieco, 2 passaggi): NEW-S6 vs OLD-NATIVE 96/27/1. L'algoritmo conta più del dataset (S0→S6: +44 contro +41 punti), il dataset aggiunge riferimenti presenti (41/41 contro 25/41), filtri su persone/anno/paese (82–95% validi contro 11%) e franchise per id.
- Migliore gestione delle preferenze negative: **S6 (combinata + riordino LLM)**; senza LLM **S5**; filtro franchise per id > per nome > solo id; penalità sul pool ≥ sottrazione di vettori (non adottata); i filtri di genere non servono per i tratti.
- Il vecchio recupera meglio nella categoria D (positivi+negativi con più riferimenti) e leggermente in C e H a livello di film; pool 50 chiude in parte il divario.
- `retrieval/retriever.py` (`WikipediaRetriever`, S6f / S5f) è il retriever da integrare. Test: 105 passati in `tests/`.
- Routing live dell'applicazione attuale: 67/72 (baseline); il routing con il nuovo RAG richiede l'integrazione.
- Stato finale delle collezioni: `netflix_scout`, v1, v2 con conteggio e digest degli id invariati dopo tutti i test (`indexing.v3 check` OK).

## 15. Integrazione nell'applicazione (2026-11-05) — eseguita; verifiche live dell'app interrotte dai crediti OpenAI

**Stato in una riga.** Il film index (`wikipedia_films_it_v3`) è il RAG attivo dell'applicazione (terminale e web); il vecchio RAG resta nel codice solo per il rollback (`RAG_BACKEND=legacy`); la precedenza delle impostazioni è applicata nell'orchestratore; la suite offline è verde (**2.566 test passati**, 22 saltati, compresi i 105 di `tool/RAGWikipediaFilm/tests`). Le verifiche live sull'applicazione intera (76 domande, 24 casi di conflitto, routing, giudice indipendente) **non sono state eseguite**: durante il lavoro l'account OpenAI ha risposto `credit_balance_exhausted` (HTTP 429, anche per embedding e gpt-4o-mini). Gli script sono pronti (`AGENTS.md`, sezione Comandi).

### Implementato
| Cosa | Dove |
|---|---|
| Retriever di produzione (parser, indice in sola lettura, ricerca, riordino, adapter) | `tool/rag/FromQueryEmbeddingToRes/film_index/{models,parser,index,search,service,adapter}.py` |
| Smistamento su `rag.backend` (nessun ripiego), schema del tool per backend, `metadata.films`/`search_notes`, campi nuovi di `RagChunk` (IMDb, regia, paesi, durata…), `FilmIndexToolInput` | `pipeline.py`, `tool_interface.py`, `models.py` |
| Configurazione: backend, collezione v3, embedding large 1.536, parametri del film index, riordino (gpt-5.6-sol senza ragionamento, 40 candidati, 1.500 caratteri) | `app.py` (`CONFIG["rag"]`), `ensure_collection_ready` |
| Rollback senza due retriever: `LEGACY_RAG_OVERRIDES` (backend, indice, embedding, regola 3 e regole di risposta di prima, copertura 2012), `RAG_BACKEND=legacy` | `app.py`, `legacy_rag_prompts.py` |
| Istruzioni: regola 3 riscritta (titolo, persona, anno, preferenze negative NON escludono il RAG; niente `tmdb_search` dopo il RAG per dati già presenti), regole di risposta (`Metadata.films`, esclusioni, `search_notes`), copertura temporale solo per MovieLens | `app.py` |
| Arricchimento TMDb solo dei film restituiti, per IMDb id, una `/find` ciascuno, mai per titolo né sul pool, nessuna scrittura | `tool/tmdb/enrich.py` (`by_imdb_only`) |
| **Precedenza delle impostazioni**: `SettingsPolicy` (guardia deterministica su `content_type`, frase di conflitto fissa it/en/de, nota per la risposta), `conflicts` dichiarati dal planner nella stessa chiamata, `CONFLICT_ONLY`, passi vietati con ripianificazione, prefisso della risposta emesso per primo | `preferences/policy.py`, `preferences/behavior.py`, `preferences/compose.py`, `orchestrator.py`, `app.py`, `turn.py`, `presenters/story_view.py` |
| Routing eval: 5 casi RAG nuovi (esclusioni, persone, anni), 4 casi spostati da TMDb al RAG, nessun `search_mode` atteso | `movie_db/harness/evaluation/routing_cases.py` |
| Documentazione | `AGENTS.md`, `README.md`, `mappa.html`, questo file, `INTEGRATION_PLAN.md`, `RAG_USAGE_STRATEGY.md`, `EVAL_REPORT.md`, `eval/results/{OPTIMIZATION,PARSER,CONFLICTS,TMDB_ENRICH_LIVE}*.md` |

### Test aggiornati o aggiunti
Nuovi: `tests/test_film_index.py` (10), `tests/test_settings_precedence.py` (9), `tests/test_tmdb_enrich_imdb.py` (5). Aggiornati perché codificavano il vecchio comportamento: `test_data_coverage.py` (niente anno limite per il RAG), `test_tmdb_app.py`, `test_youtube_answer.py`, `test_answer_provenance_rules.py` (regole di risposta), `test_tvmaze_app.py`/`test_preferences.py` (testi delle impostazioni, vincolanti), `test_movie_db_routing_eval.py` (conteggio dei casi), `test_catalog_*`, `test_reference_pipeline.py`, `test_qdrant_app_integration.py` (partono dal backend legacy), `web_api_support.py` e i finti orchestratori (accettano `settings_policy`).

### Misurato dal vivo prima dell'esaurimento dei crediti
- **Ottimizzazione del riordino** (`eval/results/OPTIMIZATION_REPORT.md`, giudice gpt-5.5): riordino da ~6–10 s a ~3 s con 2,5% di violazioni (era 3,6–4,6%) e 84,6% di film validi (era 81%): gpt-5.6-sol senza ragionamento, 40 candidati, 1.500 caratteri di trama. Più testo di trama aiuta (450→700→1.500: violazioni 5,0→3,6→2,5%); il pool oltre 40 non aiuta; i modelli piccoli e Cohere peggiorano.
- **Parser** (`eval/results/PARSER_REPORT.md`): 69–73 domande su 76 senza problemi con gpt-5.6-luna; `none` 67, gpt-5.4-mini 65; i filtri di genere troppo ampi sono scartati dal codice di ricerca prima di arrivare a Qdrant.
- **Applicazione reale, 4 turni** (con il riordino precedente, prima della modifica finale): ricerca dei film con esclusioni corretta, locandine presenti, `series` → il RAG non gira e la risposta apre con la frase di conflitto, `spoiler` → frase fissa, lunghezza e approccio → frasi fisse; difetti trovati e corretti: con «Come finisce Se7en?» non partiva nessun tool (ora il planner sa che la parte compatibile esiste) e il modello obbediva alla richiesta invece che alle impostazioni (ora la risposta riceve una nota che dice di ignorare la parte in conflitto). Latenza del turno: 22–27 s prima, ~18 s attesi dopo (non rimisurata).
- **Arricchimento TMDb** (`eval/results/TMDB_ENRICH_LIVE.md`, nessun uso di OpenAI): 28/30 film trovati, 28/28 locandine, 0 ricerche per titolo, 0 scritture, ~5 chiamate per 5 film, 0,8 s.

### Non eseguito (richiede i crediti OpenAI) — comandi in AGENTS.md
Le 62+14 domande attraverso l'applicazione reale, nuovo e legacy, con il giudice gpt-5.5 (`eval/app_run.py`); i 24 casi di conflitto (`eval/conflicts.py`); `run_routing_eval --live` con le nuove istruzioni (baseline dell'app precedente: 67/72 nel routing, poi 72/77 attese dopo gli spostamenti dei casi); la misura della latenza del turno intero; il confronto delle strategie di esclusione dentro l'app (già misurato sul recupero: `EVAL_REPORT.md`).

### Componenti del vecchio RAG che si possono rimuovere dopo la verifica di stabilità (nulla è stato eliminato)
`tool/rag/EmbeddingProcess/`, `buildSemanticDb.py`, `movie_metadata.py`, `dataset/MovieSummaries`, `docs/qdrant_migration/`, `tests/test_build_semantic_db.py`; `retrieval.py`, `rerank.py` (Cohere), `hybrid.py` (BM25/RRF), `constraints.py`, `references.py`, `reference_flow.py`, `store/` (catalogo TMDb→Qdrant, scritture), `vectorstore.py`, `catalog_enricher.py`, `film_record.py`, `legacy_rag_prompts.py`, la collezione `netflix_scout` (previo backup) e i test legacy corrispondenti. Eliminarli rende impossibile il rollback: farlo solo dopo le verifiche live e con la tua conferma.
