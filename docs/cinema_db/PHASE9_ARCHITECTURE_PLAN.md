# Fase 9 — Architettura: il database cinematografico centrale (piano, NIENTE è implementato)

Legenda: **[V]** verificato ora in sola lettura · **[S]** stima · **[I]** ipotesi da confermare con l'audit · **[M]** misura delle fasi 0–8 (citata).
Stato: **analisi e pianificazione, in attesa di approvazione dell'implementazione** (2026-11-07). Questo documento non dichiara completata alcuna attività; nessun codice, database, dato o configurazione è stato modificato; nessuna chiamata di rete, API, OpenAI o Wikidata.

## Stato dell'esecuzione (checkpoint del 2026-11-08, ~16:30; sostituisce le versioni precedenti di questa tabella)
| Fase | Stato effettivo [V] |
|---|---|
| A0 audit locale in sola lettura | **FATTA** — `PHASE9_A0_AUDIT.md` |
| A1 acquisizione e audit esterno | **FATTA solo per IMDb**: sei dataset (`title.basics|crew|principals|ratings|episode`, `name.basics`) in `cinema_db/data/imdb_snapshot/2026-11-08/`; TMDb, OMDb, TVmaze, Wikidata **non** acquisiti — `PHASE9_A1_REPORT.md` |
| B progetto dello schema finale | **prototipo** (`cinema_db/schema_v3.py`, mappa `schema_v3.html` verificata sullo schema reale); non approvato come definitivo |
| C infrastruttura di ingestione | **fatta** (`cinema_db/harness/build/imdb_layer.py`, staging `audit/imdb_load.py`) |
| D1 catalogo e ID · D2 persone e crediti · D3 valutazioni | **fatte nel prototipo** `cinema_db/data/cinema.v3.sqlite3` (digest `8760f0fdbd003fdb…`); tag MovieLens non importati |
| D4 tipo di uscita, premi, paesi/lingue delle opere nuove | **non fatta** (fonti non autorizzate) |
| E riconciliazione | **solo classificazione e proposta** (`PHASE9_RECONCILIATION.md`); nessuna fusione |
| F interfaccia, viste, policy, routing | **non iniziata** |
| G benchmark live · H ritiro dei tool | **non iniziati** |
Il runtime (`cinema_db/data/cinema.sqlite3`, digest `c888ebd0f6cf953f…`, `cinema_db.enabled = False`) è invariato e il v3 non è letto dall'agente. Il punto di ripresa operativo è la sezione **NEXT SESSION** di `PROGRESS.md`. Avvertenza sui file: vedi `PROGRESS.md` §2 (iCloud ha già creato una copia di conflitto di un file v3).

**Decisioni del proprietario (2026-11-08)** che vincolano le fasi successive: IMDb in blocco al posto di Wikidata/TMDb per ID persone, ordine del cast, personaggi, regia e troupe; le pagine italiane scartate per trama breve possono entrare senza trama se la classificazione è affidabile (tre stati: identificata con trama / identificata senza trama / dubbia, mai inserita in automatico); nessuna soglia di rilevanza prima di B; le 88 perdite documentate, **non** corrette; nessun TMDb senza nuovo via libera.

**Cosa cambia nel piano per effetto di A1 (misurato, vedi `PHASE9_A1_REPORT.md`):**
- IMDb copre bene le opere (99,94 % degli ID di cinema esistono) e dà **ID persona per circa due terzi** delle persone (90.984 su 141.646); il resto sono comparse oltre i primi accreditati: per quelle serve un'altra fonte.
- **Ordine e personaggi**: recuperabili per i primi ~10 accreditati (237.291 crediti), non per l'intero cast. La tabella `credit` (colonne `billing_order`, `character_name`) basta; non serve una nuova tabella.
- **Catalogo**: dei 61.474 titoli MovieLens mancanti 48.197 sono lungometraggi IMDb; le pagine italiane identificate portano altre decine di migliaia (soprattutto film del muto e cortometraggi). L'unione dei lungometraggi nuovi è 57.264: la regola di ingresso (§4b) va decisa in B con le curve per soglia.
- **Perdite della build**: la correzione riguarda soprattutto il trattamento degli identificativi `ids_reliable` falsi nel catalogo serie (record importati senza ID); proposta nel rapporto §7, da decidere in B.
- **Identità**: oltre a `external_id` per `imdb_name`/`imdb_title`, servono per le opere i tre stati di affidabilità dell'identificazione (identificata con/senza trama, dubbia): in B va deciso se stanno in una colonna di stato di `work` o in `entity_claim`.
- **Valutazioni**: `title.ratings` di IMDb non è stato acquisito (non autorizzato): resta MovieLens la sola fonte locale.

## Decisioni approvate il 2026-11-08 (seconda tornata) e stato di esecuzione
**Decisioni** (non riaprire; testo completo in `PROGRESS.md`, sezione «strato v3»): ingresso di lungometraggi, cortometraggi e film TV identificati, qualunque numero di voti, film muti inclusi; video musicali/amatoriali/adulti/serie/episodi fuori ma documentati; pagine dubbie fuori dal catalogo principale con archivio dei candidati; persone senza ID IMDb conservate e distinguibili, mai ID inventati né fusioni sul solo nome; correzione dei record `ids_reliable=false` e ammissione di pagine miste solo con conferma IMDb di titolo, anno e tipologia; acquisizioni autorizzate = sei dataset IMDb e nient'altro; nessuna fusione automatica; priorità IMDb solo per tipologia, anno, durata (alternative conservate); versioni nuove sempre in file separati con `.previous`.
**Criteri di identificazione**: ID esterno dello stesso schema → titolo+anno+tipologia+regista (pagine) → regola «titolo unico entro un anno» (precisione misurata 99,24 %, marcata a parte). Persone: prova forte = due titoli concordi, oppure un titolo e anno di nascita uguale; il solo nome non basta; debole/conflitto/condiviso = candidato in `external_id_candidate`. **Criteri di fusione**: nessuno applicato; proposta in `PHASE9_RECONCILIATION.md`.
**Stato rispetto al piano a fasi**: A0, A1 fatte; B (schema v3) e C/D (strato e importazione) realizzate come **prototipo separato** `cinema.v3.sqlite3`; D1–D3 coperte (catalogo, persone/crediti, valutazioni), D4 solo in parte (tipo di uscita per paese, premi, paesi/lingue delle opere nuove richiedono fonti non autorizzate); E solo classificazione; F, G, H non iniziate. Il v3 non è consumato dall'agente.
**Dipendenze della prossima fase**: F richiede (1) approvazione del v3 e delle classi di riconciliazione, (2) rigenerazione di viste e policy da un file v3 definitivo, (3) estensione di `cinema_sql` (valutazioni, stato, ordine del cast) e della regola di routing, (4) test di sicurezza SQL sulle nuove viste; G richiede F e crediti OpenAI.

## Criterio fondamentale (decisione del proprietario, 2026-11-07)
**Costruire il database cinematografico più completo, accurato e utile possibile per l'agente.** Le fonti si valutano per utilità tecnica, copertura, qualità e facilità di integrazione. Nessun audit né esclusione per licenza. Si conservano sempre fonte, riferimento e data di acquisizione (servono ad aggiornamenti, conflitti, qualità). Questa decisione **supera D3** (MovieLens separato) e **D5** (IMDb non importato) di `PLAN.md`/`PROGRESS.md`; `AGENTS.md`/`PLAN.md` saranno allineati in implementazione. Restano invariate le regole operative: nessuna rete senza go esplicito per sorgente/fase, snapshot originali mai modificati, "nessun dato inventato" (un campo che nessuna fonte dà resta vuoto), build riproducibile con `.previous`.
Principi: **P1** il database si progetta intorno alle informazioni da rendere disponibili, non intorno ai tool; **P2** una sola interfaccia strutturata per il planner, API esterne solo per dati dinamici o non disponibili localmente; **P3** qualità e copertura prima di planner e latenza; **P4** si arricchisce ciò che c'è (FK pulite, `foreign_key_check` = 0 [V]); **P5** nessun benchmark live come prerequisito: audit → definizione → implementazione per onde → solo poi misure live.

## 0. Sintesi
- Oggi 9 tool registrati; `cinema_sql` spento; se acceso aggiunge ~10.000 caratteri al prompt (schema 4.180 + regola 1g 5.855) su istruzioni di 17.774 [V]. Dati nel database: 293.447 opere, 141.646 persone, 675.327 crediti, **nessun punteggio**.
- Il problema principale è la **copertura e profondità**, non la struttura: *Fight Club* (1999) manca da `cinema_db` e dal catalogo RAG v3 [V]; 4.058 film MovieLens con ≥50 voti non sono nel catalogo [V]; cast senza ordine (0 %) e con personaggio nel 12,6 %; persone con soli ID Wikidata; uscite tutte `unspecified`; nessun `birth_country`.
- Il modello relazionale esistente (entity + external_id come crosswalk + source/provenienza) regge l'unificazione: servono poche tabelle nuove (§5), non una riprogettazione.
- La premessa "il DB unico riduce passi e latenza" non è provata: fase 7 live = 51 coppie giudicate su 165, tempo +5 %, +29 passi con DB acceso, HTTP −48/−60 % [M]. Si misura solo a database finito.

## 1. Architettura attuale [V]
Git pulito (`main`, `06ba627`); nessun Qdrant/uvicorn attivo. Archivi persistenti:
| Archivio | Contenuto |
|---|---|
| `cinema_db/data/cinema.sqlite3` 405 MB (+`.previous`, `phase3/4/6`) | schema v2: 39 tabelle (32 STRICT+FTS5), 20 viste, 58 indici; digest `c888ebd0…`; `mode=ro`+`immutable`; ricostruibile in ~8–12 min |
| `movie_db/data/movielens32m.sqlite3` 1,3 GB | `movies` 87.585 · `links` (imdb/tmdb) 87.585 · `movie_stats` 84.432 · `ratings` 32.000.204 · `tags` 2.000.066 (131.620 distinti) · `movie_genres` 147.090 (19 generi) |
| Qdrant `wikipedia_films_it_v3` | 41.138 film (trama it + metadati con QID); catalogo `films.v3.jsonl` |
| `pipelines/wikipedia_series/data/s5` | catalogo serie, nessun embedding |
| `pipelines/wikipedia_films/data/raw` 4,1 GB (dump itwiki), `…/cache/wikidata`, `wikidata_phase4` | snapshot Wikidata e dump (input della build) |
| cache dei tool HTTP | solo in memoria; nessun file persistente |
Flusso: classificatore → planner (≈ 8,3 s per passo [M]) → tool → risposta. `cinema_sql`: 13 operazioni su 20 viste approvate, SQL validato, mediana 33 ms [M].

## 2. Inventario delle fonti
**Nel database [V]**: film 36.529 (IMDb 99,3 %, TMDb 96,7 %, regia 97,3 %, cast 86,1 %, generi 96,6 %); serie 11.764 (IMDb 89,7 %, TMDb 86,9 %, regia 27,5 %, cast 52 %); miniserie 1.901; film TV 2.817; corti 3.427; stagioni 14.176; episodi 222.415 (IMDb 76). Film per decennio: 1990s 3.428 · 2000s 5.511 · 2010s 6.557 · 2020s 2.911 (412 film del 1999). Cast medio 11,1; `billing_order` 0 %; personaggio 12,6 %. Persone: ID solo Wikidata (141.634); anno di nascita 113.171; `birth_country` 0. Crediti: cast 441.298, regia 52.097, sceneggiatura 51.217, produzione 37.061, musica 31.842, fotografia 25.440. Premi 26.136 risultati (film con premi 5.563); relazioni 15.311 (`based_on` 10.513, `follows` 4.798); franchise su 4.307 opere; società su 43.072; uscite per paese 51.028, **tutte** `unspecified`; importi 10.162 (USD 9.212). Schemi ID definiti ma **senza righe**: `imdb_name`, `tmdb_person`, `tvmaze_show`, `wikipedia_en`.
**Fonti non ancora nel database (cosa possono dare) [I salvo dove citato]**
| Fonte | Dati utili | Costo/forma |
|---|---|---|
| **MovieLens** locale [V] | `links` → ID IMDb/TMDb di 87.585 film; voto medio+n. voti (84.432); tag (131.620 distinti); generi; anno | locale, zero rete |
| **IMDb datasets** (TSV bulk, già valutati in PLAN §3: `title.basics/crew/principals/ratings/episode`, `name.basics`) | ID, tipo, anno, durata, generi; regia/sceneggiatura; **cast con ordine, categoria e personaggio**; **voto IMDb e n. voti**; episodi; persone con **ID nm**, nascita/morte, professioni | file gz ~1–1,5 GB [S], un download; filtrare per rilevanza |
| **TMDb** | ID persona TMDb, cast/troupe con ordine e personaggio, **tipo di uscita per paese**, collezioni, keyword, paesi/lingue, voto e n. voti, poster/backdrop (path), certificazioni | ≈1 richiesta per titolo con `append_to_response` [S]; export giornaliero degli ID gratuito [I] |
| **OMDb** | Metascore, **Rotten Tomatoes**, `Awards` (testo), `Rated`, `BoxOffice` | 1–2 richieste per titolo; la chiave gratuita ha 1.000/giorno → mirare ai titoli più rilevanti o piano a pagamento [S] |
| **TVmaze** | ID serie (lookup per IMDb), stato, rete, episodi con data, speciali | ≈1–3 richieste per serie |
| **Wikidata** (snapshot locali + nuove richieste mirate) | P345/P4985 (ID persona), premi, luogo di nascita, `film project`, relazioni | prima il survey degli snapshot locali; le nuove richieste, con go esplicito |
| **Wikipedia** | puntatori; prosa resta live | invariato |
Dinamici, **non** persistiti: provider streaming, trending/popolarità, uscite imminenti, prossimo episodio, video.

## 3. Matrice di integrazione campo per campo
① colonne esistenti/nuove · ② tabella nuova · ③ collegamento M:N · ④ separata con riferimento · ⑤ solo API (dinamico).
| Dato | Fonte primaria (priorità proposta) | Stato oggi | Soluzione | Aggiornamento |
|---|---|---|---|---|
| Catalogo opere mancanti (film noti assenti) | MovieLens links → IMDb basics → TMDb ID export; soglia di rilevanza (§4b) | 4.058 ML≥50 voti assenti | `work` + `external_id` (nuove righe, `source_id`) | a ogni build |
| Titoli, anno, durata, generi, tipo | Wikidata/itwiki (esistenti) poi IMDb basics/TMDb per i vuoti | durata 92 % film | ① campi esistenti; discordanze in `entity_claim` | build |
| ID persona (IMDb nm, TMDb) | IMDb name.basics + `principals`; TMDb credits; Wikidata P345/P4985 | 0 | ③ `external_id` (schemi già definiti) | build |
| Cast completo con ordine e personaggio | IMDb principals (ordine) + TMDb credits (personaggio, ID TMDb) | ordine 0 %, personaggio 12,6 % | ① `credit.billing_order`, `character_name` (già nello schema) | build |
| Regia, scrittura, troupe | Wikidata (esistente) + IMDb crew/principals | regia 97 % film, 27 % serie | `credit` | build |
| Valutazioni (pubblico) | IMDb ratings, TMDb vote, MovieLens mean/n | nessuna | ② **`work_rating`** (una riga per opera×fonte×metrica) | mensile |
| Valutazioni (critica) | OMDb: Metascore, Rotten Tomatoes | nessuna | ② `work_rating` (`audience`=critics) | trimestrale, mirato |
| Tag / parole chiave | MovieLens tag (soglia di frequenza), TMDb keywords | nessuno | ② **`work_tag`** | build |
| Premi | Wikidata (esistenti) + completamenti mirati; OMDb `Awards` come riepilogo di controllo | 26.136 risultati, nominato spesso assente | `award_result` esistente; ② `entity_claim` per le discordanze | build |
| Uscite per paese con tipo | TMDb `release_dates` | 100 % `unspecified` | ① `work_release.kind` (già ammette theatrical/streaming…) | build |
| Franchise/collezioni | Wikidata + TMDb collections | 4.307 opere | `franchise`, `work_franchise` | build |
| Società, paesi, lingue, budget/incassi | Wikidata + TMDb | parziale | tabelle esistenti | build |
| Poster/backdrop | TMDb (path) | assenti (oggi 1 `/find` per film mostrato) | ② **`work_artwork`** (opzionale, evita richieste) | trimestrale |
| Certificazioni (età) | TMDb | assenti | ② `work_certification` (opzionale) | build |
| Episodi (struttura e date) | catalogo s5 + IMDb episode + TVmaze | conteggi inaffidabili | `work` (season/episode) | build |
| Streaming, trending, popolarità, prossimo episodio, trailer, video | TMDb / TVmaze / YouTube | — | ⑤ API dietro l'interfaccia (§7) | live |
| Trama / prosa | Wikipedia + Qdrant | puntatore | ④ resta | live/RAG |
**Provenienza e conflitti**: ogni riga ha `source_id` (fonte), `source_ref` e data di acquisizione (`retrieved_at`/`as_of`). Priorità per campo (default proposto): identità = ID esterno; fatti anagrafici = Wikidata > IMDb > TMDb; ordine/personaggio del cast = IMDb/TMDb; punteggi = ciascuna fonte separata, mai fusi né convertiti. Valori discordanti non scelti si conservano in `entity_claim` (§5).

## 4. Audit offline e identità
**4a. Audit di lacune e sovrapposizioni (solo lettura).** Fase A0 (nessuna rete, solo file locali): copertura pesata sul catalogo rilevante per ogni dimensione; sovrapposizione cinema ↔ MovieLens ↔ RAG v3 ↔ catalogo serie ↔ snapshot Wikidata ↔ dump; cause dei buchi (*Fight Club*, i 4.058); presenza di P345/P4985/P2704 negli snapshot; classificazione dei doppioni. Fase A1 (dopo go esplicito per ciascuna acquisizione): scarico dei bulk esterni (IMDb TSV, export ID TMDb) in un archivio read-only e ripetizione dell'audit con le sovrapposizioni vere. Misure già note [V]:
- MovieLens ↔ cinema (join per ID): 26.111 film in comune su 87.585; ≥50 voti: 11.596 su 16.034 (72 %) in comune, **4.058 assenti** (4.045 con ID TMDb in ML; solo 14 già presenti con altro ID); per decennio 1980s 410 · 1990s 862 · 2000s 1.048 · 2010s 1.127; generi Drama 1.619, Comedy 1.547, Documentary 669; 1,43 M dei 31,5 M voti. Titoli noti: *Fight Club*, *This Is Spinal Tap*, *Caddyshack*, *Best in Show*, *A Christmas Story* — lacune del catalogo, non rumore.
- Doppioni: 58 opere con 2 ID IMDb, 357 con 2 ID TMDb, 240 film in due QID, 18 omonimi titolo+anno (film); persone: 33 coppie nome+nascita uguali, 139 nome uguale senza nascita, 1.962 nomi condivisi (in gran parte omonimi legittimi).
**4b. Come entrano le opere mancanti.** Regola di ingresso per rilevanza, non "tutto": un'opera entra se ha almeno un criterio (soglia da misurare nell'audit): voti MovieLens ≥ N, voti IMDb ≥ M, TMDb con voti ≥ K, pagina itwiki, o presenza in un franchise/relazione già registrata. Le opere entrano con ID (`imdb_title`, `tmdb_movie`) e dati base dalla fonte; i campi che nessuna fonte dà restano vuoti e il tool li dichiara `partial`. Le 61.000 e più voci ML con pochi voti restano fuori finché non servono (stima da misurare).
**4c. Sistema di identità.** Una sola `entity` per concetto, `external_id` come crosswalk. Scala: (1) ID dello stesso schema; (2) ID di schemi diversi concordi (IMDb↔TMDb↔QID↔EIDR); (3) titolo normalizzato + anno ±1 + regista/paese in comune (solo candidato, mai fusione automatica); (4) persone: ID, poi nome+nascita+opera in comune; mai il solo nome. Classi: **duplicato reale** (≥2 prove forti indipendenti) · **omonimo** · **stessa informazione da fonti diverse** (non duplicato: stessa riga arricchita, `source` registrata) · **discordanza** (alternative conservate). Strumenti: file/tabella `entity_merge_candidate` (audit, nessuna cancellazione); fusione solo in una build nuova con `canonical_entity_id` e controllo prima/dopo (FK, 100 interrogazioni campione, nessuna relazione persa); `.previous` sempre conservato. Ingresso di una fonte: *staging* (snapshot archiviato) → riconciliazione per ID → inserimento o arricchimento, mai due righe per la stessa opera.

## 5. Schema relazionale proposto (v3, additivo)
Restano le 39 tabelle e le 20 viste. Nuove (minime):
1. **`work_rating`**: `work_id`, `source_id` (FK `source`: imdb, tmdb, movielens, metacritic, rotten_tomatoes…), `metric`, `value`, `scale_max`, `vote_count`, `audience` (`audience`|`critics`), `as_of`, `source_ref`; PK (work_id, source_id, metric). Più valutazioni per opera, mai fuse né sovrascritte. Indice (source, metric, value) per le classifiche.
2. **`work_tag`**: `work_id`, `tag_norm`, `tag`, `weight` (n. utenti), `source_id`; PK (work_id, tag_norm, source_id).
3. **`entity_claim`**: `entity_id`, `field`, `value`, `source_id`, `retrieved_at`, `is_selected`: alternative discordanti (durata, data, titolo, anno…); il valore selezionato resta nella colonna principale.
4. **`entity_merge_candidate`** (audit dei duplicati).
5. Opzionali dopo l'audit: `work_artwork` (path poster/backdrop), `work_certification`, `refresh_log` (run, fonte, righe, data).
Estensioni senza nuove tabelle: `external_id` (ID persona), `credit` (ordine e personaggio, già nello schema), `work_release.kind` (tipo di uscita). Eventuale `source.kind` nuovi valori (`tmdb`,`omdb`,`movielens`,`tvmaze`) e `usage_scope` come semplice etichetta di provenienza. Indici: FK nuove, `work_rating(source_id,metric,value)`, `credit(person_id,role)` già presente. Ogni oggetto nuovo rigenera `approved_views.py` e passa i test di sicurezza SQL.
**Dimensioni [S]**: ~150–250 mila opere rilevanti (da misurare), cast limitato ai primi ~20–30 per opera → 2–5 M crediti; il file passerebbe da 405 MB a ~1–2 GB. Le interrogazioni vanno rimisurate (mediana attuale 33 ms [M]; `ANALYZE`, indici su `credit(work_id,billing_order)`).
**Mappa HTML**: il generatore esiste (`cinema_db/harness/schema/map_view.py`, `schema.generate`) e legge lo schema SQLite reale (tabelle, colonne, PK, FK, relazioni navigabili); per lo schema proposto si genera da un file prototipo in cartella temporanea (fase B), poi dal database ricostruito.

## 6. Mappa delle relazioni
```
entity 1─1 work|person|company|franchise|award   entity 1─* external_id(scheme,value)  (crosswalk IMDb/TMDb/QID/EIDR/TVmaze/nm)
work 1─* credit *─1 person (ordine, personaggio)  work 1─* work_rating *─1 source   work 1─* work_tag
work *─* work (work_relation)  work *─* franchise  work *─* genre_label *─* genre  work 1─* work_release(tipo, paese)
award 1─* ceremony 1─* award_result *─1 work|person  entity 1─* entity_claim  entity_merge_candidate → entity,entity
```

## 7. Interfaccia unica per il planner (conseguenza del database)
Proposta (decisione tua, §12): il planner vede **3–4 capacità**, non 9 tool:
1. **`cinema_sql`** (strutturato, sempre il primo passo): identità, filmografie, cast con ordine e personaggio, premi, relazioni, franchise, **punteggi di tutte le fonti**, classifiche, tag, uscite per paese, episodi. Ogni risposta riporta fonte, `as_of` e stato per campo (`verified|partial|uncertain|absent`, già in `reliability.py`).
2. **Facciata dinamica** (stessa famiglia, operazione `live`, adattatori interni TMDb/TVmaze/YouTube/OMDb): streaming, trending, uscite imminenti, prossimo episodio, video, punteggi più recenti di `as_of`. Riceve ID dal database: niente passi di identificazione.
3. `rag_search` (ricerca semantica per trama; non sostituibile da SQL) e `wikipedia_search` (prosa), eventualmente come operazioni di sfondo della stessa facciata.
Ritiro/assorbimento (da decidere a database finito, §11): `omdb_search`, `tvmaze_search`, `wikidata_search`, `movie_db_search`, `tmdb_search` diventano adattatori interni o script di aggiornamento; i client HTTP esistenti si riusano nei processi di aggiornamento offline (mai visibili al planner). Prompt: oggi schemi dei 9 tool ≈ 30.000 caratteri + regole 17.800+5.900 [S da misura parziale]; con 3–4 capacità la stima è molto inferiore, da misurare. Ricerca per il planner: deve conoscere capacità e limiti del database tramite le note per campo già esistenti.

## 8. Nuovo flusso di pianificazione
DB-first per tutto ciò che il database contiene con affidabilità sufficiente; API solo se il campo è `absent`/`partial` rilevante, più vecchio di `as_of` accettabile, o dinamico/esplicitamente "in tempo reale"; un solo passo per la richiesta composta quando possibile (il primo planner elenca le parti; i passi indipendenti non richiedono `_plan_next` — Intervento 3 di fase 8, −24 chiamate su 85 passi [S], richiede il core: decisione a parte); risposte che distinguono verificato/parziale/incerto/assente.

## 9. Benefici e limiti
Benefici attesi: più film noti rispondibili in locale; cast e punteggi senza richieste; classifiche con ogni fonte; meno identificazioni (ID dal DB); prompt più corto [I per il guadagno di latenza]. Limiti: dipendenza dalla qualità delle fonti bulk e dalla riconciliazione; dimensioni; costo di build e aggiornamento; dati recenti sempre in ritardo di un'acquisizione; punteggi con `as_of` che invecchiano. Ottimizzazioni reali da verificare: ratings locali (oggi 10 richieste OMDb per 5 candidati), poster senza `/find`, ID noti, prompt ridotto. Teoriche: parallelismo (D7 escluso).

## 10. Piano per fasi (ordine definitivo)
Ogni fase: input originali immutati, rollback = `.previous` o rimozione dell'archivio; ogni acquisizione di rete richiede go esplicito per sorgente; nessun benchmark live prima di G.
| Fase | Obiettivo | Componenti | Schema | Dati | Duplicati | Test | Rischi | Rollback | Risultato verificabile |
|---|---|---|---|---|---|---|---|---|---|
| **A0 Audit locale (sola lettura)** | lacune e sovrapposizioni fra cinema, MovieLens, RAG v3, serie s5, snapshot Wikidata, dump; cause dei buchi; ID persona negli snapshot | `cinema_db/harness/audit/` | nessuno | rapporti | candidati in file | test degli script | basso | cancellare rapporti | rapporto con copertura pesata e cause |
| **A1 Acquisizione e audit esterno** | scaricare IMDb TSV, export ID TMDb (e un campione TMDb/OMDb/TVmaze per misurare campi e copertura) in archivio read-only; audit di sovrapposizione | `cinema_db/harness/acquire/` (unico codice di rete, una sorgente alla volta) | nessuno | snapshot con `retrieved_at` e hash | candidati | test offline sui parser | volume, quote | cancellare l'archivio | tabella reale: cosa aggiunge ogni fonte |
| **B Progetto del database finale** | regola di ingresso nel catalogo, priorità per campo, politica conflitti, schema v3 su prototipo, mappa HTML | `schema.py`, `schema_notes.py`, `generate` | v3 (prototipo) | nessuno | regole di fusione | test schema/doc/sicurezza | viste/policy | non toccare il DB reale | documento + mappa HTML approvati |
| **C Infrastruttura di ingestione** | staging, crosswalk ID, regole di priorità, `entity_claim`, riproducibilità | `build/` | v3 | — | riconciliazione per scala §4c | test su miniature | complessità | build precedente | build v3 vuota riproducibile (digest) |
| **D1 Catalogo e ID** | opere mancanti (ML≥soglia, IMDb, TMDb), ID incrociati | stadio build | — | +opere, +`external_id` | per ID prima di inserire | confronto copertura prima/dopo, FK=0 | omonimi | `.previous` | copertura pesata ↑, 0 doppioni nuovi |
| **D2 Persone, cast, crediti** | ID nm/TMDb, ordine, personaggio, troupe | stadio build | — | +persone, `billing_order`, personaggi | regola persone | campione 100 film vs fonte | volume | `.previous` | cast ordinato per i film principali |
| **D3 Valutazioni e tag** | IMDb, TMDb, MovieLens, OMDb (mirato) in `work_rating`/`work_tag` | stadio build | `work_rating`, `work_tag` | righe con `as_of` | PK per fonte/metrica | confronto con valori della fonte | quota OMDb | `.previous` | classifiche per fonte coerenti |
| **D4 Dettagli TMDb/Wikidata** | tipo di uscita, collezioni, certificazioni, poster, luoghi di nascita, premi completati | stadio build | opzionali | righe | claim per discordanze | campioni | richieste | `.previous` | `unspecified` ↓, premi ↑ |
| **E Riconciliazione duplicati** | audit e fusione delle classi forti in build nuova | build | `canonical_entity_id` | — | audit FK | 100 interrogazioni prima/dopo | relazioni perse | `.previous` | 0 relazioni perse |
| **F Interfaccia e routing** | `cinema_sql` + facciata dinamica; regola di routing sulle capacità; fallback per campo | `tool/cinema_db`, `app.py` | — | — | — | test offline, dimensione prompt | regressioni | flag spento | prompt misurato prima/dopo |
| **G Benchmark live rappresentativo** | passi, HTTP, latenza, completezza; chiusura delle 114 coppie della fase 7 | `tool_eval/*` | — | — | — | giudice a ciechi (a pagamento, go) | costo | n/a | decisione su accensione |
| **H Ritiro graduale** | disattivare (non cancellare) i tool assorbiti; eventuale ottimizzazione orchestratore | `allowed_tools`, `orchestrator.py` | — | — | — | criteri §11 | perdita di copertura | riattivare | criteri soddisfatti |
Dipendenze: A0 → A1 → B → C → D1 → D2 → D3 → D4 → E → F → G → H (D3 può partire con i soli dati locali ML subito dopo D1).

## 11. Test e criteri di accettazione
Per ogni onda D: indicatore di copertura pesato prima/dopo (non il numero di righe), `foreign_key_check` = 0, `integrity_check`, nessun doppione per ID, riproducibilità del digest, confronto con la fonte su un campione stratificato, `schema.generate --check`, test di sicurezza SQL. Per F–H: insieme **rappresentativo e fisso** di domande (identità/omonimi, filmografie e cast, premi, relazioni, classifiche per fonte, punteggi, recenti, serie, composte, e domande che il DB non sa), stesse domande prima/dopo, misure di chiamate del planner, HTTP, tempo, token, errori; un tool si ritira se per le sue classi: nessun peggioramento di correttezza e completezza, passi e HTTP ≤ attuali, giudice a ciechi non peggiore. Niente test ripetitivi né correzioni per singole domande.

## 12. Rischi e decisioni da approvare
Approvazione di questo piano e dell'ordine A0→H; **A0 può partire subito** (solo lettura locale). Decisioni successive: (1) go per ciascuna acquisizione di rete in A1 (IMDb, TMDb, OMDb, TVmaze, Wikidata); (2) soglie di rilevanza per l'ingresso di nuove opere (§4b) dopo i numeri di A0/A1; (3) profondità del cast (quanti crediti per opera); (4) forma dell'interfaccia (una facciata o 3–4 capacità); (5) fusione dei duplicati: classi forti e firma; (6) disattivazione vs rimozione dei tool; (7) toccare il core per i passi indipendenti; (8) crediti OpenAI per G. Rischi: dimensione e tempi di build; omonimi e riconciliazione errata (mitigata da fusione solo in build nuova e `.previous`); quote OMDb (1.000/giorno) per l'import mirato; dati recenti incompleti; benefici di latenza non dimostrati finché non misurati.

## Verifica
Tutti i numeri marcati [V] sono riproducibili con `sqlite3 -readonly` su `cinema.sqlite3` e `movielens32m.sqlite3` (ATTACH solo in memoria) e con lettura di `films.v3.jsonl`. In questa fase nessun file del repository cambia tranne i due documenti sopra.

## Stato (2026-11-08, ~18:40): E riconciliazione APPLICATA nella v3 riconciliata
La fase E è stata eseguita con le regole approvate dal proprietario (doppi ID, 12 fusioni reversibili, 204 ID per nascita, 1.133 titoli rilasciati, stato `…_director_mismatch`, 90.824 episodi, 52.190 crediti recuperati): `cinema.v3.reconciled.sqlite3`, digest `044c35f8…`, rapporto `PHASE9_RECONCILED_REPORT.md`. La fase F (viste, policy, `cinema_sql` sul v3) **non è iniziata**; `cinema_db.enabled` resta `False` e il runtime usa il v2.

## Aggiornamento (2026-11-08, sera)
File corrente della v3: `cinema.v3.reconciled2.sqlite3` (`59b57598…`). Corretto il confronto dei titoli non latini, conservate le 3.272 opere incerte (vista `v_work_status`), persone per candidati deboli non fuse. Fase F ancora non iniziata; v2 resta runtime.

## Aggiornamento (2026-11-09): F realizzata (non attivata)
Viste, policy e `cinema_sql` sulla v3 sono implementati (`PHASE9_F_REPORT.md`); candidata di riferimento `cinema.v3.candidate.sqlite3` (`9db2c80d…`). G (benchmark live) e H (ritiro dei tool) non iniziate; l'attivazione richiede una decisione del proprietario.
