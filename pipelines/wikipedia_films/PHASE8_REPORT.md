# Fase 8: verifica finale, strategia d'uso del nuovo RAG, piano di sostituzione

Stato: **analisi, documentazione e strumenti di prova.** Nessuna chiamata API (nemmeno embedding), nessun commit. Dataset (`films.jsonl`, `films.clean.jsonl`, manifesto) e le tre collezioni (`netflix_scout`, `wikipedia_films_it`, `wikipedia_films_it_v2`) invariati; vecchio RAG, orchestratore, `app.py`, frontend e `web_api` non toccati. Ho eliminato un solo file, `INTEGRATION_PROPOSAL.md` (mio, della Fase 4: proponeva due retriever e fusione). Nuovi file: `RAG_USAGE_STRATEGY.md`, `INTEGRATION_PLAN.md`, `indexing/negative.py`, `indexing/negative_eval.py`, `audit/category_probe.py`, `audit/two_part_review.json`, `tests/test_negative.py`.

## 1. Decisioni delicate

| Controllo | Esito |
|---|---|
| 4 incerti reinseriti (*Another*, *Il vento dell'Amnesia*, *The Connection*, *Fantaghirò* 1991) | inclusi e `unverified` nel dataset e in Qdrant |
| 44 dubbi non riesaminati, 8 sospesi, 9 ibridi sospesi | inclusi e `unverified` (44 + 8 + 9 + 4 = **65**); il filtro Qdrant `unverified = true` ne trova 65, `false` 41.072 |
| Coerenza manifesto ↔ dataset ↔ Qdrant | 28 verificati e 65 non verificati del manifesto coincidono con lo stato dei record; i 284 esclusi non sono né nel dataset né nella collezione |

**I 7 film TV esclusi come miniserie.** Ho letto dal dump locale (nessuna rete) categorie, frase iniziale e intestazioni di ciascuna pagina (`audit/two_part_review.json`). Criterio: un unico film in due serate si include, una miniserie con episodi distinti si esclude, se non è determinabile non si cambia.

| Titolo | Cosa dice Wikipedia | Esito |
|---|---|---|
| Il processo di Norimberga | «miniserie televisiva»; sezioni «Prima puntata», «Seconda puntata»; categoria *Miniserie televisive* | **escluso, confermato** |
| Padre Pio – Tra cielo e terra | «miniserie televisiva»; sezioni «Primo episodio», «Secondo episodio» | **escluso, confermato** |
| I guardiani del cielo | «miniserie televisiva in due puntate»; categoria *Miniserie televisive basate su opere letterarie* | **escluso, confermato** (fiducia media) |
| **Aftershock – Terremoto a New York** | «è un **film TV** del 1999»; una sola «Trama», nessuna puntata, categorie di film | **da includere** (correzione proposta, **non applicata**) |
| La storia di Anne Frank | «miniserie televisiva… 20 e 21 maggio», ma anche «un film controverso»; una sola «Trama» | non determinabile: lasciato escluso |
| Atomic Train | «miniserie televisiva del 1999»; una sola «Trama»; solo categorie di film | non determinabile: lasciato escluso |
| Attila l'unno | «miniserie televisiva del 2001»; una sola «Trama»; categorie di film | non determinabile: lasciato escluso |

Non ho applicato nemmeno la correzione di *Aftershock*: richiede di aggiungere un punto alla v2, che mi hai vietato di modificare. Il vettore esiste già (si riusa, costo zero); con la correzione i film sarebbero 41.138. Le descrizioni «miniserie NBC in due parti» delle Fasi 6–7 per *Aftershock* venivano dalla mia memoria e sono smentite dalla pagina.

## 2. Collezione `wikipedia_films_it_v2` (letta, non modificata)

Configurazione: cosine, 1.536 dimensioni float32, 41.137 punti (uno per film, nessun chunk), stato green, tutti indicizzati; 4 segmenti, HNSW m=16, ef_construct=100, soglia di scansione completa 10.000, grafo in RAM; payload su disco; WAL 32 MB; nessuna quantizzazione. Indici di payload: `film_id`, `wikipedia_page_id`, `year`, `genres`, `country`, `language`, `director_names`, `imdb_id`, `title_norm`, `chunked`, `catalog_status`, `unverified` (i due ultimi nuovi). Payload: l'intero record del film (trama inclusa) più `unit_id`, `chunk_index`, `chunk_count`, `chunked`, `title_norm`, `director_names`, `actor_names`, `catalog_status`, `unverified`, `synopsis_original_sha256`. Rieseguito: 41.137 record = 41.137 punti, id attesi, nessun escluso, 65 non verificati filtrabili, 25 vettori nuovi corretti, vecchie collezioni con lo stesso digest.

**I 549 MB contro i 514 MB.** Sono due unità diverse: 549 è la dimensione della v2 in KB decimali (549.180 KB per `du`), 514 è la v1 in MiB (526.432 KB). A parità di unità e misurando lo spazio realmente allocato:

| MiB su disco | v1 (41.438 punti) | v2 (41.137 punti) | differenza |
|---|---|---|---|
| Vettori | 242,8 | 241,1 | −1,7 |
| Valori del payload | 102,9 | 106,7 | +3,8 |
| Indici di payload | 99,2 | 119,5 | **+20,3** |
| WAL (log di scrittura) | 64,0 | 64,0 | 0 |
| Indice vettoriale e id tracker | 5,1 | 5,0 | −0,1 |
| **Totale** | **514,1** | **536,3** | **+22,2 (+4,3%)** |

I vettori (41.137 × 1.536 × 4 byte = 241,1 MiB) calano con i punti. L'aumento viene dai due indici di payload aggiunti (`catalog_status`, `unverified`): un indice occupa circa 10 MiB perché ha una voce per punto, non per valore distinto (i 10 indici precedenti pesavano in media 9,9 MiB), e da tre campi in più nel payload. Il WAL (64 MiB, 12% del totale) è spazio di servizio costante, non dati; la «dimensione apparente» dei file (694 MiB) è più grande dello spazio allocato perché i file sono sparsi.

## 3. Cosa contiene davvero il dataset [verificato sui dati]

- **41.137 record**, tutti con trama; 99,9% con elemento Wikidata, 99,2% con IMDb, 98,7% con regista, 90,7% con cast, 91,7% con durata; 70 senza anno.
- **Serie TV:** non ho trovato serie TV evidenti tra i verificati. Restano: 70 record con una classe Wikidata di serie/anime/manga/OVA accanto a una di film (39 `unverified`, **31 verificati** — i 23 ibridi decisi come film e altri come *Tomie: Another Face*); due titoli con suffisso di serie o manga, entrambi `unverified` (*Fantaghirò (miniserie televisiva)*, *Orange (manga)*). Tra i 65 `unverified` circa 30 sono pagine di anime/manga/OVA o di opere TV dubbie, gli altri film veri.
- **Altri formati dichiarati dall'audit:** lungometraggi 35.113, corti 3.430, animazione 1.309, film TV 901, muti 209, speciali TV 29, home video 28, serial 7, documentari 3.
- **Casi ambigui o classificati male:** 65 `unverified`, i 3 non determinabili del punto 1 (esclusi), i casi di confine del campione (*Pasolini*, *Il giovane Mussolini*…) rimasti verificati.
- **Il campo «tipo di opera» non esiste** nel payload. `genres` è testo libero di Wikidata (366 etichette che citano TV/serie/anime/manga, presenti anche su film veri) e `unverified` copre solo i dubbi noti: **non basta** per filtrare per formato. Il formato dell'audit (`film/short/tv_film/…`) vive solo in `data/audit/classification.jsonl`, non in Qdrant. Proposta: `work_format` e `format_confidence` nel payload (v3 o aggiornamento del payload, da approvare; nessun nuovo embedding).

## 4. Nuova strategia d'uso del RAG
Documento completo con le bozze delle istruzioni: **`RAG_USAGE_STRATEGY.md`**. In sintesi:
- Il RAG diventa la **ricerca semantica sui film**: fonte primaria per raccomandazioni, ricerca per trama/tema/atmosfera/genere, «film come X» (X come esempio positivo), riconoscimento dalla trama, ricerche semantiche con vincoli su regista/attore/anno/paese/genere. Titoli, persone e anni **non lo escludono più**.
- Si mantengono ai loro strumenti: dati aggiornati (streaming, trailer, voti, immagini, cast completo, novità, filmografie complete) → TMDb; classifiche → MovieLens; punteggi → OMDb; prosa → Wikipedia; relazioni → Wikidata; serie → TMDb/TVmaze.
- **Meno chiamate:** dopo il RAG niente `tmdb_search` per titolo, regia, cast principale, anno, durata, paese, generi, sinossi (sono nel payload); `imdb_id`, `wikidata_id` e `wikipedia_url` dei risultati servono ai tool successivi.
- **Limite onesto:** copertura per anno ~700 film l'anno nel 2010–2019, poi 500 (2020), 410 (2024), 374 (2025), 188 (2026): per «novità» resta TMDb. Le schede della lista web oggi dipendono dall'arricchimento TMDb (poster): decisione aperta.

## 5. Preferenze negative: analisi e test locali

**Strumenti disponibili** (verificati su Qdrant 1.20): ricerca con vettore (posso passare qualunque vettore, anche un centroide); `recommend` con esempi positivi e negativi per id o per vettore, strategie `average_vector` (equivale a `2p − n`, cioè a `p − 0,5 n` di direzione) e `best_score`; filtri `must_not` su id e su payload; reranking sul pool con vettori. **Esclusione per ID ≠ semantica:** l'id toglie solo il titolo citato; sequel, remake e film vicini restano.

**Suite di scenari** (`python -m pipelines.wikipedia_films.indexing.negative_eval`, 11 scenari su film reali del catalogo, 8–10 strategie ciascuno, nessuna chiamata API): positiva senza esclusioni; titolo da evitare (*Star Wars*); più titoli (*Star Wars* e *Matrix*; *Harry Potter* e *Il Signore degli Anelli*); genere da evitare (*cyberpunk*; *horror*); caratteristica narrativa da evitare (combattimenti); più positivi e più negativi; «come *Interstellar* ma non come *Gravity*»; «come *Alien*, diverso da *Predator*»; «*Blade Runner* e *Terminator*, ma non *Matrix*». Gli esempi sono vettori reali dei film; i concetti («fantascienza», «horror», «combattimenti») sono centroidi di gruppi di film scelti sui metadati o sul testo: sostituiscono l'embedding del testo, che non potevo fare.

Medie sugli scenari (le colonne sono proxy oggettivi, **nessun giudice umano né LLM**): «perdite» = film del franchise o titoli citati nella top 10; «viol. genere/testo» = risultati con il genere o il tratto da evitare; «coseno positivo» = rilevanza (somiglianza ai positivi); «coseno negativo» = vicinanza a ciò che si voleva evitare.

| Strategia | Perdite | Viol. genere (su 10) | Viol. testo | Coseno positivo | Coseno negativo | Sovrapposizione col solo positivo |
|---|---|---|---|---|---|---|
| Solo positivo | 0,27 | 6,5 | 3 | 0,778 | 0,681 | 0,93 |
| Esclusione per id | 0,09 | 6,5 | 3 | 0,777 | 0,674 | 0,90 |
| Sottrazione 0,5 / `recommend` average | 0 | 6,0 | 3 | 0,759 / 0,761 | 0,605 / 0,608 | 0,51 |
| Sottrazione 1,0 | 0 | 3,5 | 3 | **0,633** | 0,433 | 0,24 |
| `recommend` best_score | 0 | 5,0 | 0* | 0,674 | 0,563 | 0,66 |
| Penalità sul pool λ=0,5 | 0 | 6,0 | 3 | 0,759 | 0,608 | 0,51 |
| Penalità sul pool λ=1,0 | 0 | 5,0 | 3 | 0,730 | 0,563 | 0,31 |
| **Filtro sui metadati del genere** | 0 | **0** | – | 0,673 | – | – |

\* `best_score` con un negativo che è un concetto restituisce film senza relazione (coseno positivo 0,15–0,19 negli scenari *cyberpunk* e *combattimenti*): lo «0» non è un successo.

Cosa mostrano i test:
1. **Per ID basta contro il titolo citato, non contro i suoi sequel**: con il positivo solo, *Gravity* torna nella top 10 di «come *Interstellar*»; con la sola esclusione per id, *Predator 2* resta in «come *Alien*, diverso da *Predator*».
2. **La penalità semantica (λ=0,5) toglie le perdite (0,27 → 0)** con una perdita di rilevanza piccola (coseno 0,778 → 0,759), ma **non elimina un genere**: in «come *Alien*, ma non horror» restano 10 film horror su 10 (8 con λ=1,0), perché la vicinanza di *Alien* ai film horror è la ragione stessa per cui è simile.
3. **Per un genere del vocabolario l'unico strumento che garantisce è il filtro sui metadati** (0 violazioni); costa un po' di rilevanza e dipende da `genres` (testo libero di Wikidata, incompleto).
4. **Sottrarre il vettore negativo a peso pieno rovina i risultati** (coseno positivo 0,633; in «come *Alien*, diverso da *Predator*» la top 5 diventa un elenco di fantascienza e commedie degli anni '50–'80 lontane da *Alien* (*Dark Star*, *L'aereo più pazzo del mondo*…)), come sospettavi: va pesato (≤ 0,5) o usato come penalità sul pool.
5. **Caratteristiche narrative** («senza combattimenti»): la penalità non le rimuove (3 film su 10 con almeno tre riferimenti ai combattimenti, anche con λ=1,0). L'embedding non rappresenta bene l'assenza di un tratto; serve il controllo del reranker/dei vincoli.
6. Contraddizioni insite nella richiesta («come *Blade Runner* ma senza cyberpunk», con *Blade Runner* stesso classificato cyberpunk) vanno segnalate all'utente.

**Strategia concreta:** `RAG_USAGE_STRATEGY.md` sezione 5 (id sempre; penalità λ=0,5 sul pool per i film da evitare; filtro `must_not` per i generi del vocabolario; descrizioni positive di ciò che si evita come negativo; verifica con vincoli e reranker; niente `best_score` con concetti né sottrazione piena).

**Cosa servirebbe per una valutazione completa e non l'ho fatto.** (a) Embedding di circa 20 testi brevi: le frasi dei 11 scenari in italiano e le descrizioni in positivo dei tratti da evitare (cyberpunk, horror, combattimenti, trama intricata, «blockbuster»): circa 600 token, **circa 0,0001 USD** con `text-embedding-3-large` (stima dal prezzo registrato di 0,13 USD per milione). (b) Un giudice LLM per la pertinenza delle top 10 (11 scenari × 6 strategie × 10 film ≈ 660 giudizi): **stimati 0,15–0,25 USD** con `gpt-5.6-luna` ai prezzi registrati in Fase 2 (stima mia, non misurata). Non ho fatto né l'una né l'altra.

## 6. Impostazioni utente e film/serie
Tabella completa in `RAG_USAGE_STRATEGY.md` sezione 4. Regole: richieste di film → RAG ammesso; richieste di serie (esplicite o con preferenza `series`) → **il RAG non si usa come fonte di raccomandazione, nemmeno se l'utente descrive trame, generi o atmosfere** (TMDb/TVmaze); richieste miste → RAG per la parte film, strumenti delle serie per il resto, in liste separate; né l'uno né l'altro con preferenza `both` → due liste distinte; l'intento esplicito prevale sulla preferenza (come oggi); i record `unverified` si dichiarano solo se pertinente. `preferences/behavior.py` già dice di non usare il RAG per le serie: la modifica proposta estende il caso «descrizione di trama».

## 7. Documentazione aggiornata
`README.md` (stato effettivo, sezione 7 rimpiazzata, sezione 13 corretta, nuova sezione 14 con dataset, collezione, film/serie, benchmark e limiti, decisioni non verificate, stato dell'integrazione), `PROGRESS.md` (Fase 8, voci obsolete corrette), `AUDIT_REPORT.md` e `PHASE6_REPORT.md` (riferimenti alla proposta eliminata), `RAG_USAGE_STRATEGY.md` e `INTEGRATION_PLAN.md` (nuovi). Rimosse le indicazioni su due RAG paralleli, facciata, fusione RRF, tabella di corrispondenza. Non ho toccato `AGENTS.md`, che descrive il vecchio RAG e andrà riscritto a integrazione fatta (è fuori dalla cartella consentita).

## 8. Piano di sostituzione
`INTEGRATION_PLAN.md`: file e componenti da modificare (collezione e modello, `vectorstore`/`models`/`retrieval`/`constraints`/`rerank`/`references`, rimozione del catalogo TMDb→Qdrant e dell'arricchimento per titolo, `tool_interface`, `data_coverage`), istruzioni da riscrivere, ruoli, preferenze negative, film/serie, sette fasi (la rimozione del vecchio RAG solo dopo la verifica nell'applicazione), test e **sette criteri oggettivi** di riuscita.

## 9. Test eseguiti
- `pipelines/wikipedia_films/tests`: **97 passati** (6 nuovi in `test_negative.py`: funzioni pure su vettori sintetici e due controlli di sola lettura sulla v2).
- Suite del progetto (comando di `AGENTS.md`): **2.067 passati**.
- `build_clean verify` OK; `pipeline verify` (Fase 1) OK; `indexing.v2 check` OK (41.137/41.137, 65 `unverified`, vecchie collezioni invariate).
- Scenari di preferenze negative: eseguiti (sezione 5).

## 10. Problemi aperti e decisioni che ti chiedo
1. **Aftershock:** includere (con rebuild della v2 o v3, nessun nuovo embedding)? E i tre non determinabili (*Anne Frank*, *Atomic Train*, *Attila*): lasciarli esclusi?
2. **`work_format`/`format_confidence`/`franchise_id` nel payload** (v3 senza nuovi embedding, o aggiornamento del payload della v2).
3. **Schede della lista web** senza arricchimento TMDb automatico: arricchimento leggero per `imdb_id` o schede senza poster?
4. **Rimozione di BM25** (`hybrid.py`) nella prima versione del nuovo retriever.
5. **RAG escluso con `content_type=series`** anche quando l'utente descrive la trama (la mia proposta: sì).
6. **Permesso a pagamento** (stime sopra): embedding di circa 20 testi per completare gli scenari (≈ 0,0001 USD), giudizio LLM sugli scenari (≈ 0,2 USD), poi valutazione di qualità nuovo-contro-vecchio e `run_routing_eval --live`: i costi di questi ultimi due non sono stati stimati e li stimerò prima di chiederli.
7. **Limiti noti:** copertura recente del catalogo; i test di preferenze negative usano proxy oggettivi, non giudizi di pertinenza; la strategia d'uso non è stata provata con un LLM; `AGENTS.md` ancora descrive il vecchio RAG.

Mi fermo qui: nessuna integrazione, nessun commit.
