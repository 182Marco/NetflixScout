# Nuova strategia di utilizzo del RAG (proposta, NON applicata)

Il RAG Wikipedia (`wikipedia_films_it_v2`) sostituisce il vecchio. Questo documento riparte dal catalogo e non dalle vecchie regole. Nulla qui è stato modificato nell'applicazione (`app.py`, orchestratore, `preferences/`, frontend, `web_api/` restano come sono).

## 1. Perché le vecchie regole esistono e quali non valgono più

Le regole attuali (`app.py`, `CONFIG["orchestrator"]["instructions"]`, regola 3; `data_coverage`; `final_instructions`; `tool_final_instructions`; `preferences/behavior.py`) nascono dai limiti del corpus CMU:

| Limite del vecchio RAG | Effetto sulle istruzioni | Con il nuovo catalogo |
|---|---|---|
| Dump del 2012, film solo fino al 2012 (`data_coverage.rag_search = 2012`) | «anno dopo il 2012 → mai rag_search» | 41.137 film fino al 1° nov 2026; copertura per anno nella sezione 2 |
| Trame e titoli in inglese; query riscritta in inglese | un titolo italiano o un nome non si abbinava | trame in italiano, `text-embedding-3-large` multilingue: si cerca con le parole dell'utente |
| Corpus rumoroso (216 punti non-trama, molti film poco noti) | «SOLO se non c'è titolo, persona o anno» | 284 pagine non film escluse, 65 non verificati marcati |
| Nessun regista/attore filtrabile in modo affidabile | «non usare per attori, registi» | `director_names` indicizzato (98,7% dei film), `actor_names` nel payload (90,7%) |
| Metadati poveri → ogni risultato passava da TMDb per titolo | `rag_enrichment` su 3 candidati | `imdb_id` sul 99,2% dei film: identità certa senza ricerca per titolo |
| Un riferimento a un titolo → `tmdb_search similar` | regola 3 (decisione del 2026-10-27) | un film citato diventa un esempio positivo (o negativo) della ricerca semantica |

Non valgono più: il divieto per titoli, persone e anni, il tetto 2012, la query in inglese e l'arricchimento TMDb automatico. Restano valide le parti non legate al corpus: nessun nome di tool/fonte nella risposta, traslitterazione dei nomi, regole sugli spoiler (la trama arriva al modello intera).

## 2. Cosa è davvero il nuovo RAG

È una **ricerca semantica sui film** (trama in italiano) con **filtri sui metadati** (anno, paese, genere, regista, durata, stato `unverified`). Non è una fonte di dati aggiornati né completa:
- **Solo film.** Nessuna serie TV (sezione 3).
- **Copertura per anno** (film con trama su it.wikipedia): ~700 all'anno nel 2010–2019, 500 nel 2020, 410 nel 2024, 374 nel 2025, 188 nel 2026 (fino a novembre). Dopo il 2019 il catalogo è meno completo: per «le novità», «in uscita», «ultimi film» la fonte resta TMDb.
- **Campi in ogni risultato:** titolo, titolo originale, anno, regia, cast (con personaggi, non sempre), durata, paese, lingua, generi, trama, IMDb, URL Wikipedia. Mancano: poster, streaming, trailer, voti, recensioni.
- **Non dà una garanzia di pertinenza:** somiglianza di embedding su trame intere, senza comprensione di negazioni (sezione 5).

## 3. Ruolo di ogni strumento

| Strumento | Ruolo futuro |
|---|---|
| **rag_search** (nuovo) | Fonte primaria per: raccomandazioni; ricerca per trama, tema, atmosfera, emozione, genere, ambientazione, epoca; «film come X» (X film); riconoscere un film dalla trama; ricerche semantiche combinate con regista/attore/anno/paese/genere; preferenze negative. Restituisce film con metadati del payload. |
| tmdb_search | Dati aggiornati o strutturati: streaming, trailer/immagini, voto del pubblico, cast completo, troupe, uscite e novità, filmografie complete e ordinate, trending, collezioni, serie TV (discover/ricerca/raccomandazioni di serie), film assenti dal catalogo. **Non** si chiama dopo il RAG per dati che il RAG ha già. |
| movie_db_search | Voti, classifiche, conteggi di voti, tag MovieLens (invariato). Attenzione: non distingue film e serie. |
| omdb_search | Punteggi (IMDb, Metascore, Rotten Tomatoes) di un titolo identificato; l'`imdb_id` del RAG evita la ricerca per titolo (1 richiesta invece di 2). |
| wikipedia_search | Prosa enciclopedica (storia, produzione, confronti film/romanzo, struttura): la pagina è già nota (`wikipedia_url`). |
| wikidata_search | Relazioni tra opere (remake, fonti, serie, franchise); ID: gli ID Wikidata del RAG (`wikidata_id`) la rendono diretta. |
| tvmaze_search | Dati strutturati di serie (stagioni, episodi, prossimi episodi): invariato. |
| youtube_search | Video su un film identificato: invariato. |

**Meno chiamate inutili.** Dopo `rag_search` non si chiama TMDb per titolo, regia, cast principale, anno, durata, paese, generi, sinossi: sono nel payload. Si chiama solo per ciò che il RAG non ha (streaming, trailer, voti, immagini, cast completo). Decisione da prendere: le schede della lista web (`web_lists`) oggi si basano sugli elementi TMDb (immagini, id) dei candidati; senza arricchimento TMDb le schede perdono il poster. Opzione: arricchimento leggero per `imdb_id` (una `/find` per film, nessuna ricerca per titolo) solo nei turni che producono le schede.

## 4. Film e serie TV

**Verifica sui dati (Fase 8):** `films.clean.jsonl` è un catalogo di **film** con queste eccezioni dichiarate: 65 record `unverified` (di cui circa 30 sono pagine di anime/manga/OVA o di opere TV dubbie, altri sono film veri come i live-action tratti da manga) e 31 record «verificati» con una classe Wikidata di serie accanto a quella di film (23 ibridi decisi come film, più film come *Tomie: Another Face*). Nei titoli rimangono solo 2 suffissi di serie/manga, entrambi `unverified` (*Fantaghirò (miniserie televisiva)*, *Orange (manga)*). **Il payload non contiene un campo «tipo di opera»**: l'unico segnale è `unverified` più il campo `genres` (testo libero di Wikidata: 366 etichette che citano TV, serie, anime o manga, per esempio «dramma televisivo» o «anime e manga fantasy», presenti anche su film veri). Non è sufficiente per filtrare per formato.

**Proposta:** aggiungere al payload (v3 o aggiornamento del payload, da approvare) `work_format` derivato dall'audit locale (`film`, `short`, `animated`, `tv_film`, `tv_special`, `silent`, `documentary`, `music_film`, `serial`, `video_film`, `unreleased`, `unknown`) e `format_confidence`. Con esso il filtro per formato diventa esplicito.

**Regole per l'agente:**

| Richiesta | Comportamento |
|---|---|
| Film (esplicito o dalla preferenza `film`) | RAG ammesso. |
| Serie TV (esplicita o preferenza `series`) | **RAG non usato come fonte di raccomandazione**, nemmeno se l'utente descrive trame, generi o atmosfere: TMDb `discover_tv`/`search`/raccomandazioni, TVmaze per i dati. |
| Richiesta mista («film e serie su…») | RAG per la parte film; TMDb per la parte serie (`parts` con i due tool). |
| Né film né serie («consigliami qualcosa di…») con preferenza `both` (default) | RAG per i film + TMDb `discover_tv` per le serie, senza mescolare nella stessa lista; la risposta dice quale lista è quale. |
| Preferenza `series` con descrizione di trama | niente RAG (la preferenza prevale sul tema); se l'utente chiede esplicitamente un film, l'intento esplicito prevale. |
| Titolo ambiguo film/serie | come oggi (`CONTENT_PLANNER`): la preferenza risolve l'ambiguità; il RAG si usa solo se il titolo è un film. |
| Record `unverified` nei risultati | ammessi per default ma dichiarati come «non verificato» solo se pertinente; filtro `unverified = false` quando l'utente chiede esplicitamente «solo film veri» o la preferenza è `film` e il record ha un formato dubbio. |

## 5. Preferenze negative

Vedi `PHASE8_REPORT.md` per i risultati locali. Strategia concreta:

1. **Parser.** Il planner/parser dei segnali restituisce `like` (titoli/descrizioni positive), `avoid_titles`, `avoid_genres` (da un vocabolario chiuso dei generi del catalogo) e `avoid_descriptions` (caratteristiche narrative da evitare **scritte in positivo**: «molti combattimenti», «trama intricata a più livelli», mai «senza combattimenti»). Un embedding non capisce la negazione: «senza cyberpunk» embeddato è vicino a *cyberpunk*.
2. **Esclusione per ID, sempre.** I titoli citati (positivi e negativi) non tornano mai tra i risultati (filtro `must_not` su id). Non basta: restano sequel, remake e spin-off del titolo da evitare.
3. **Esclusione semantica dei titoli da evitare.** Pool di 200 candidati per la query positiva; punteggio = `cos(r, P) − λ·max_i cos(r, N_i)` con **λ = 0,5** per ogni film negativo. È il comportamento migliore misurato: elimina i sequel vicini al negativo senza distruggere la rilevanza.
4. **Generi da evitare = filtro sui metadati.** Se il genere è nel vocabolario (`genres`), `must_not` in Qdrant: l'unica strategia che azzera davvero le violazioni (0 su 10; le strategie solo semantiche lasciano 2–3 su 10 per *cyberpunk* e 8–10 su 10 per *horror* con Alien). Se non è nel vocabolario si passa a (5).
5. **Caratteristiche narrative da evitare.** Si embedda la descrizione in positivo (una chiamata a costo trascurabile, circa 0,000001 USD) e la si usa come negativo del punto 3. È solo una penalità: **non garantisce** l'assenza. Il controllo vero lo fanno il reranker (query composta «must match») e lo stato dei vincoli già presente (`constraint_summary`, «contraddetto/non verificabile»).
6. **Non si usa** la sottrazione grezza a peso pieno (α = 1: la rilevanza crolla) né `recommend` con strategia `best_score` con negativi che sono concetti (risultati scollegati), né `average_vector` come unico meccanismo (è equivalente a `p − 0,5 n`, cioè al punto 3 ma senza il controllo del pool).
7. **Limiti dichiarati.** Titoli o generi che il catalogo non conosce; film citati non presenti (si usa la loro trama TMDb embeddata in memoria, **senza scrivere nella collezione**, a differenza del vecchio `reference_flow`); concetti vaghi («meno complicato», «diversi dai soliti blockbuster») non misurabili senza un giudizio: vanno al reranker/LLM e la risposta li dichiara non verificati.

## 6. Nuove istruzioni da dare al planner (bozze)

**Regola 3 (sostituisce quella attuale).**
> 3) rag_search è la ricerca semantica sui film: circa 41.000 film con la trama di Wikipedia in italiano, fino a novembre 2026 (meno completo dopo il 2019); solo film, mai serie TV. È il punto di partenza per: consigliare film; cercare per trama, temi, emozioni, atmosfera, genere, ambientazione, epoca o stile; «film come X», «simili a X», «con l'atmosfera di X» (X è un film: passalo in arguments.like con titolo e anno se certo); riconoscere un film dalla trama; ricerche semantiche con vincoli su regista, attore, anno, paese, genere o durata. Un titolo, una persona o un anno non escludono rag_search: sono riferimenti o filtri. Preferenze negative («ma non come Y», «senza Z», «diverso da…»): titoli da evitare in arguments.avoid_titles; generi da evitare in arguments.avoid_genres (solo generi del catalogo); caratteristiche da evitare in arguments.avoid_descriptions, descritte in positivo e mai negate. Imposta k_finale al numero di film chiesto. Non scegliere rag_search per: elenchi completi o filmografie ordinate, novità e uscite, voti e classifiche, dove vederlo in streaming, trailer, cast completo, dati ufficiali di un titolo specifico, serie TV. Dopo rag_search non chiamare tmdb_search per dati già nei risultati (titolo, anno, regia, cast principale, durata, paese, generi, trama): chiamalo solo per ciò che il RAG non ha.

**Modifiche collegate.**
- Regola 1: togliere il rimando «film come X → tmdb_search similar/recommendations» (resta per serie e per «consigliati dal pubblico»).
- Regola 1c/1d/1f: usare `wikipedia_url`, `imdb_id`, `wikidata_id` dei risultati del RAG come dati già disponibili «in un passo precedente del turno».
- `data_coverage`: `rag_search` non più «fermo al 2012»; nuova nota: copertura per anno misurata dal dataset locale (`data_coverage.py` va riscritto per leggere `films.clean.jsonl`).
- `final_instructions`: togliere le frasi su `tmdb_enrichment` e «ordine dei film del RAG»; i film vengono presentati dai dati del payload; i record `unverified` si dichiarano solo se serve.
- `CONTENT_PLANNER["series"]`: già dice di non usare il RAG per le serie; resta e si estende al caso «descrizione di trama».
- `SOURCE_TOOLS["rag_search"]`: oggi «official information»; è dato enciclopedico curato (Wikipedia), mantenere, con il rischio spoiler già noto (la trama intera arriva al modello).

## 7. Cosa NON è stato verificato
Qualità di questa strategia con un LLM e con query reali; routing con il planner reale; effetto delle nuove istruzioni sul numero di chiamate. Richiedono chiamate a pagamento (stima nel rapporto di Fase 8) e la tua approvazione.

---

## 8. Aggiornamento del 2026-11-04 (decisioni vincolanti, prevalgono sulle sezioni precedenti)

- **Serie**: con `content_type=series` il RAG non si usa mai, nemmeno se la richiesta descrive trama, atmosfera o temi (guardia deterministica, non solo prompt). Con `film` si bloccano gli strumenti per serie. `both` non confligge.
- **Precedenza**: un'impostazione persistente (default inclusi) prevale sempre su una richiesta esplicita in conflitto, per tutti i campi (spoiler, lunghezza, tono, approccio, tipo di contenuto; fonti solo se la richiesta chiede un'altra fonte). La prima frase della risposta dichiara il conflitto e quale impostazione prevale; poi si risponde alla parte compatibile o ci si ferma. Questo inverte la sezione 4 («l'intento esplicito prevale sulla preferenza») e la regola attuale di `preferences/` e `AGENTS.md`.
- **TMDb**: non dopo il RAG per dati già nel payload; solo `/find` per `imdb_id` sui film mostrati, per i poster.
- **Titolo, persone, anno**: si risolvono con filtri sul payload (`title_norm`, `director_names`, `actor_names`) nella stessa ricerca; il vettore ordina, il filtro vincola.
- **Lessicale**: BM25 non è eliminato; non esiste un secondo ranking né RRF. Parole rare di trama = vincolo full-text o candidati ordinati dal solo vettore; si sceglie con A/B live.
- **Aftershock** incluso; Anne Frank, Atomic Train, Attila l'unno esclusi e segnalati «non verificati».
- **Formato**: `work_format` e `format_confidence` in v3 sostituiscono la proposta della sezione 4.
- **Verifica**: batteria live autonoma e `run_routing_eval --live` a integrazione pronta (`INTEGRATION_PLAN.md` sezione 10.4).

## 9. Evidenze misurate (2026-11-04, `EVAL_REPORT.md`)
- Il RAG con titolo, persona o anno è migliore del vecchio: filtri su regista/attore/anno/paese 82–95% di film validi contro 11% (14 domande), quindi l'esclusione «titolo/persona/anno → niente RAG» non ha più motivo.
- Esclusioni: il solo id non basta; servono franchise per id e penalità semantica; per i tratti in linguaggio naturale il riordino LLM che conosce i film è il passo decisivo (violazioni 16%→6%), a ~10 s.
- Lessicale: filtro full-text nella stessa query (hit@5 1,00); nessuna fusione.
- Non misurato: serie/film con `content_type`, conflitti con le impostazioni, routing con le nuove istruzioni.

## 10. Applicata nell'applicazione (2026-11-05)
La strategia di questo documento è in produzione: regola 3 del planner riscritta (titolo, persona, anno e preferenze negative non escludono il RAG; serie e novità restano a TMDb), `final_instructions` senza il completamento TMDb per titolo, copertura temporale solo per MovieLens, arricchimento TMDb dei soli film restituiti per IMDb id, `content_type=series` che vieta il RAG con una guardia deterministica, precedenza delle impostazioni (default inclusi). Dettagli e file: `PROGRESS.md` §15 e `AGENTS.md`. Non ancora verificato dal vivo sull'applicazione intera (crediti OpenAI esauriti).
