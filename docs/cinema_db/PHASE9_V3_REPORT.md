# Fase 9 — Strato v3: costruzione separata, copertura e verifiche (rapporto)

Generato da `python -m cinema_db.harness.audit.run_a1 v3report`. Il database runtime `cinema_db/data/cinema.sqlite3` **non è stato modificato** (digest `c888ebd0…`). Il file nuovo è `cinema_db/data/cinema.v3.sqlite3`, costruito da una copia con `python -m cinema_db.harness.build.imdb_layer`; non è letto dall'agente finché non si rigenerano la policy e le viste (fase F).

## 1. Cosa è stato fatto
Ordine fisso e deterministico: (1) tabelle v3 e due nuove fonti; (2) recupero degli ID dei record con `ids_reliable=false` solo se IMDb conferma titolo, anno e tipologia; (3) ID IMDb delle persone solo con prova forte; (4) priorità IMDb per tipologia, anno, durata (il valore perdente resta in `entity_claim`); (5) valutazioni per fonte; (6) episodi collegati a IMDb con prove forti; (7) opere nuove; (8) stato, FTS, controlli di integrità.

## 2. Copertura prima e dopo

| misura | v2 (runtime) | v3 |
|---|---|---|
| opere | 301.718 | 384.300 |
| persone | 141.646 | 532.138 |
| crediti | 675.327 | 1.861.764 |
| crediti con ordine (`billing_order`) | 0 | 1.585.363 |
| crediti di cast con personaggio | 55.430 (12.56 %) | 858.946 (79.41 %) |
| opere con ID IMDb | 54.612 | 305.059 |
| opere (film, corti, TV, serie) senza ID IMDb | 1.912 | 1.676 |
| persone con ID IMDb | 0 | 460.876 |
| episodi con ID IMDb | 76 | 167.705 |
| film con durata | 34.697 | 91.498 |
| valutazioni (righe) | 0 | 328.597 |
| opere con due o più valutazioni di fonti diverse | 0 | 80.600 |
| gruppi di film con stesso titolo e anno | 18 | 103 |
| dimensione del file | 405 MB | 964 MB |

Opere per tipo: film 36.529 → 93.696; short 3.427 → 23.143; tv_film 2.817 → 8.835; series 11.764 → 11.534; miniseries 1.901 → 1.812; episode 222.415 → 222.415; season 14.176 → 14.176; other 8.689 → 8.689.

Copertura dei film di MovieLens in `cinema_db` (per numero minimo di voti):

| voti ≥ | film MovieLens | in v2 | % v2 | in v3 | % v3 |
|---|---|---|---|---|---|
| 1 | 84.432 | 25.626 | 30.35 | 80.826 | 95.73 |
| 10 | 31.961 | 17.677 | 55.31 | 31.089 | 97.27 |
| 100 | 12.191 | 9.878 | 81.03 | 12.074 | 99.04 |
| 1000 | 4.397 | 4.149 | 94.36 | 4.387 | 99.77 |
| 50 | 16.034 | 11.976 | 74.69 | 15.818 | 98.65 |

## 3. Opere nuove: regola di ingresso e vie

| via | tipo | opere nuove |
|---|---|---|
| imdb_itwiki_page_rule | film | 1.381 |
| imdb_itwiki_page_rule | short | 5.022 |
| imdb_itwiki_page_rule | tv_film | 21 |
| imdb_itwiki_page | film | 16.725 |
| imdb_itwiki_page | short | 10.188 |
| imdb_itwiki_page | tv_film | 165 |
| imdb_movielens | film | 39.565 |
| imdb_movielens | short | 3.982 |
| imdb_movielens | tv_film | 5.533 |

Affidabilità dell'identificazione (`work_status.identification`): catalogue 301.718, imdb_id_given_by_movielens 49.080, imdb_title_year_director_confirmed 27.078, imdb_title_year_unique 6.424. Completezza delle opere audiovisive: basic 40.655, rich 98.267, skeleton 98 (`rich` = regia, cast, genere e durata; `basic` = almeno uno; `skeleton` = nessuno).

**Non entrate nel catalogo principale** (archivio separato `cinema_db/data/cinema.v3.separate/not_entered.jsonl`, con motivo): outside_entry_rule:video 2.206, reconciliation_hold_same_title_and_year_in_cinema 1.656, outside_entry_rule:tvEpisode 720, outside_entry_rule:tvMiniSeries 333, not_identifiable_via_imdb 208, flagged_adult 118, outside_entry_rule:tvSeries 90, no_year 11, outside_entry_rule:videoGame 2. I tipi fuori regola sono video (musicali o direct-to-video), serie, episodi e altro; gli adulti e le coppie titolo+anno già presenti (*reconciliation hold*) restano fuori finché non c'è una decisione.
- **Pagine italiane dubbie** (8.842): 6.823 risolte con i dati IMDb già acquisiti da una regola (un solo titolo IMDb entro un anno, con l'anno esatto della pagina), la cui precisione sulle pagine con ID noto è 99.24 % (3.007 giusti, 23 sbagliati su 3.030; soglia che mi sono dato: 99.0 %). Sono marcate `imdb_itwiki_page_rule` / `imdb_title_year_unique`, quindi distinguibili e ritirabili. Restano nell'archivio separato 2.019 pagine con candidati e motivo: director on page matches no candidate 3.852, no director on page 3.780, only candidates with year off by one 1.199, several candidates with a matching director 11 (conteggi sulle 8.842).

## 4. Correzione dei record con `ids_reliable=false`
Candidati (record del catalogo serie importati senza ID, con IMDb non ancora in cinema): 398. **Recuperati: 237** (con QID: 230). Non confermati: imdb_id_unknown_to_imdb 21, title_differs 82, type_not_television 23, year_differs_or_missing 35. I non confermati con un record IMDb restano come candidati `ids_reliable_false_unconfirmed`.
Criterio: titolo uguale (anche senza qualificatore tra parentesi), anno entro uno, tipo IMDb televisivo (`tvSeries`, `tvMiniSeries`, `tvMovie`, `tvSpecial`). Tipi dei recuperati: tvMiniSeries 89, tvMovie 86, tvSeries 60, tvSpecial 2. Elenco completo in `cinema.v3.separate/recovered_identifiers.jsonl`.
**Pagine miste manga/anime**: 338 con un ID IMDb; tipo IMDb: tvSeries 272, tvMiniSeries 46, video 7, (assente) 6, movie 4, tvMovie 2, short 1. Solo 7 sono di un tipo cinematografico e **nessuna** supera la conferma di titolo e anno: ne è entrata 0. Le 318 serie non entrano (decisione del proprietario).

## 5. Priorità tra fonti: tipologia, anno, durata
- Tipologia cambiata (IMDb `titleType`): 2.043 opere; valore precedente in `entity_claim` (2.043). Tipi IMDb non mappabili (video, videogioco, episodio, pilot) o opere con figli: kind invariato e tipo IMDb registrato come claim `imdb_title_type` (1.132).
- Anno (IMDb `startYear`): cambiato su 6.096 opere (valore precedente conservato), compilato su 5.397; data di uscita incompatibile spostata in `entity_claim`: 5.387.
- Durata (IMDb `runtimeMinutes`): cambiata su 13.667, compilata su 152.719 (in gran parte episodi). Dove IMDb non ha il dato resta quello di `cinema_db`.

## 6. Persone e crediti
- ID IMDb attaccati con prova forte: 70.384. Candidati non attaccati (`external_id_candidate`): conflict_birth_year 2.544, conflict_several_candidates 849, episode_number_only 3.576, ids_reliable_false_unconfirmed 140, name_and_birth_year_only 10.506, weak_single_title 17.639.
- Persone create dalle opere nuove (ognuna con il suo ID IMDb): 390.492. Crediti aggiunti alle opere nuove: 1.186.437. **Crediti trattenuti** perché la persona IMDb è un candidato di una persona esistente (nessun duplicato creato): 52.655; categorie non mappate (`casting_director`): 29.668.
- Crediti già esistenti che hanno ricevuto l'ordine: 411.666; il personaggio: 207.115 (mai sovrascritto).
- Le persone di `cinema_db` senza ID IMDb restano distinguibili: nessuna riga `imdb_name` in `external_id` (con candidati dove esistono). Persone senza ID IMDb nel v3: 71.262.

## 7. Valutazioni ed episodi
- Valutazioni per fonte: imdb-datasets 247.906, movielens-32m-aggregates 80.691 (IMDb: 117.292 opere + 130.648 episodi). Ogni riga ha scala, voti e data (`as_of`); nessuna media né conversione.
- Episodi: 220.487 episodi di cinema appartengono a serie con ID IMDb; collegati con prove forti 167.630 (numero + anno 144.658, numero + titolo 600, titolo unico 22.372); solo-numero (candidati) 3.576. Episodi presenti in IMDb ma **non** in cinema per le stesse serie: 95.806 (non inseriti: decisione aperta).

## 8. Duplicati: controlli
- Coppie nuovo-vecchio con stesso titolo e anno: 0 (devono essere poche e spiegate: un titolo nuovo non può coincidere con un'opera esistente senza essere trattenuto).
- Gruppi di film con lo stesso titolo e anno: 18 → 103. Quasi tutti sono omonimi legittimi (registi diversi in IMDb): la verifica per regista dà la distribuzione nel rapporto di riconciliazione.
- Verifica per regista dei gruppi con stesso titolo e anno (opere audiovisive): {'different_directors_homonyms': 149, 'director_unknown': 26, 'same_director_probable_duplicate': 4}.
- Titoli MovieLens/pagine con lo stesso titolo e anno di un'opera esistente, **trattenuti**: 1.656; per regista: stesso regista 26 (probabilmente lo stesso film; in 6 casi l'opera esistente non ha ID IMDb: l'ID si potrebbe attaccare), registi diversi 719 (probabili omonimi), regista ignoto 911. ID IMDb di MovieLens attaccati come alias non primari tramite lo stesso ID TMDb: 25.
- `foreign_key_check`, `integrity_check`, coerenza FTS e invarianti della build: superati (la costruzione si interrompe altrimenti). Riproducibilità: due costruzioni con gli stessi input danno lo stesso digest (test `tests/test_cinema_imdb_layer.py`).

## 9. Dimensioni degli archivi

| archivio | dimensione |
|---|---|
| cinema.sqlite3 (runtime, invariato) | 405 MB |
| cinema.v3.sqlite3 | 964 MB |
| archivi separati v3 | 2 MB |
| imdb_snapshot (6 dataset .gz originali) | 1.481 MB |
| audit_a1 (file di analisi IMDb e candidati) | 1.286 MB |
| audit_a0 | 40 MB |
| movielens32m.sqlite3 (invariato) | 1.324 MB |

## 10. Stato di verifica (checkpoint del 2026-11-08)
**Verificato [V] su questo file** (`cinema_db/data/cinema.v3.sqlite3`, digest `8760f0fdbd003fdb…`, 963.887.104 byte, schema 3, `builder = imdb_layer/1`): `foreign_key_check` vuoto, `integrity_check` ok, coerenza FTS e invarianti (la costruzione si ferma altrimenti); due costruzioni consecutive con gli stessi input hanno lo stesso digest; la mappa `docs/cinema_db/schema_v3.html` coincide con lo schema SQLite reale (36 tabelle più la virtuale FTS, 20 viste, 76 gruppi di chiavi esterne, 65 indici, colonne, chiavi primarie e conteggi); il file runtime `cinema.sqlite3` (digest `c888ebd0f6cf953f…`) è invariato; suite richiesta da AGENTS.md: 2.661 passati, 1 saltato.
**Stime [S]**: l'errore atteso della regola «titolo unico» (circa 0,8 % su 6.424 opere) è la stima da una misura su pagine di ID noto; la distribuzione omonimi/duplicati per regista confronta nomi normalizzati e può sbagliare con traslitterazioni.
**Ipotesi [I]**: i 719 titoli trattenuti con registi diversi sono omonimi (non verificato); i 3.576 episodi «solo numero» sono probabilmente gli stessi episodi con anno diverso (non verificato); l'effetto di `name.basics` più vecchio di un giorno è trascurabile.
**Non verificato**: l'uso del v3 da parte di `cinema_sql` (viste e policy non rigenerate); la qualità semantica dei personaggi IMDb rispetto a quelli italiani (differiscono nel 18 % dei casi con entrambi); i dati delle opere nuove contro una fonte indipendente (nessun campione a mano).
**Difetto noto non corretto**: per le 58 opere con due ID IMDb la priorità su tipologia, anno e durata è stata applicata a entrambi gli ID in ordine alfabetico, quindi vale l'ultimo ID elaborato (l'altro valore finisce in `entity_claim`). Va applicata al solo ID primario: da correggere in `imdb_layer.py` prima di una ricostruzione definitiva.
**Attenzione ai file**: la cartella del progetto è sul Desktop con iCloud attivo. Dopo la costruzione finale il sistema ha rinominato il file corretto in `cinema.v3 2.sqlite3` e lasciato come `cinema.v3.sqlite3` la prima costruzione (digest `54629e6e66218d15…`, 384.708 opere, codice precedente). Sono stati rinominati: la prima costruzione è ora `cinema.v3.first_build.sqlite3` (superata, non usare) e il file corretto è tornato `cinema.v3.sqlite3`. **Dopo ogni costruzione verificare il digest** (`python -m cinema_db.harness.build.imdb_layer` lo scrive anche in `cinema.v3.layer_report.json`).


## Aggiornamento (2026-11-08, seconda tornata)
Questo rapporto descrive il **prototipo** `cinema.v3.sqlite3` (`8760f0fd…`), invariato. Il **difetto dei doppi ID** (§10) è corretto nel nuovo file `cinema.v3.reconciled.sqlite3` (`044c35f8…`): vedi `PHASE9_RECONCILED_REPORT.md` per regole, conteggi, verifiche e anomalie. Il difetto era più ampio: coinvolgeva anche le valutazioni IMDb, il confronto dei crediti esistenti con l'elenco del cast (`people_and_cast` usava il primo ID registrato) e l'abbinamento degli episodi alla serie secondaria.

## Aggiornamento (2026-11-08, sera)
Il file corrente è `cinema.v3.reconciled2.sqlite3` (vedi `PHASE9_RECONCILED_REPORT.md`, «Seconda correzione»); questo rapporto descrive il prototipo `8760f0fd…`.

## Aggiornamento (2026-11-09)
File corrente: `cinema.v3.candidate.sqlite3` (`PHASE9_F_REPORT.md`).
