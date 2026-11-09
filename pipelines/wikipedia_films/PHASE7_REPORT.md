# Fase 7: dataset pulito e collezione `wikipedia_films_it_v2` [risultati effettivi]

Nessun commit. `films.jsonl` intatto (SHA-256 `68495921…949`, uguale a quello del manifesto di Fase 1; `pipeline verify` → OK). `netflix_scout` (42.522 punti) e `wikipedia_films_it` (41.438) invariate: stesso numero di punti e stesso digest SHA-256 degli id prima e dopo. Vecchio RAG, orchestratore, `app.py`, frontend non toccati; nessuna integrazione.

## Riconciliazione
`python -m pipelines.wikipedia_films.audit.reconcile` → `audit/decisions_manifest.json` (377 record, uno per `film_id`, con fonte e motivo) e `audit/plan_overrides.json`. Sovrapposizioni controllate: 259∩27, 259∩46, 27∩46, 71∩46, 259∩71, Lobo∩altri liste → **tutte vuote**; i 27 sono tutti tra i 71. Nessun record sottratto due volte. L'unico cambio di decisione ammesso è il reinserimento di 8 delle 259, come approvato.

| Decisione | Record |
|---|---|
| Esclusi | 284 = 251 (259 − 8 riesaminati) + 18 dubbi + 14 ibridi + 1 (*Lobo*) |
| Inclusi verificati (decisi) | 28 = 4 reinseriti + *Dive!!* + 23 ibridi film |
| Inclusi non verificati (decisi) | 65 = 4 incerti reinseriti + 8 dubbi in sospeso + 9 ibridi in sospeso + 44 dubbi non riesaminati |
| Film inclusi in tutto | **41.137** (41.421 − 284) |

## Interpretazioni che ti segnalo (nessuna è una contraddizione non risolvibile, ma sono scelte mie)
1. **I 4 casi incerti tra le 259** (*Another*, *Il vento dell'Amnesia*, *The Connection*, *Fantaghirò* 1991): «mantieni… contrassegnandoli come non verificati» e «mantieni i casi non verificati nel dataset» → li ho **inclusi, non verificati**. Per escluderli basta toglierli da `reinstate` e rilanciare `reconcile` + `build_clean`.
2. ***Lobo Paramilitary Christmas Special*** (un fumetto, falso positivo del campionamento): escluso per la regola «opere non cinematografiche»; non era nell'elenco approvato.
3. **Regola dei film TV in due serate** contro i 14 ibridi esclusi: sette di essi li avevo descritti come «miniserie in due parti/serate» (*Il processo di Norimberga*, *Padre Pio – Tra cielo e terra*, *La storia di Anne Frank*, *Atomic Train*, *Attila l'unno*, *Aftershock*, *I guardiani del cielo*). Ho applicato l'elenco approvato alla lettera; se per te sono un'unica opera in due serate vanno reinseriti.
4. I **44 dubbi non riesaminati** restano inclusi e non verificati (regola della Fase 4); *Dive!!* è verificato.

## Dataset pulito (`data/clean/`)
`build_clean build` poi `verify` → «OK: ricostruzione byte per byte e reversibile» (ripetuto a fine lavoro). 6,7 s.

| File | Contenuto |
|---|---|
| `films.clean.jsonl` | 41.137 record, 131,5 MB, SHA-256 `a22ae050…db` |
| `excluded.jsonl` / `excluded_list.json` | 284 esclusi interi, con categoria, fonte e motivo |
| `unverified.json` | 65 record non verificati (campo `catalog_status`) |
| `corrections.json` | 25 trame: hash originale, hash nuovo, eccezione manuale |
| `category_counts.json` | conteggi per categoria (inclusi ed esclusi) |
| `clean_manifest.json` | conteggi e SHA-256 di tutte le entrate e uscite |

Inclusi per categoria dell'audit (`category_counts.json`; i 65 non verificati compaiono nella loro categoria, 9 sono di tipo «film»): lungometraggi 35.113, corti 3.430, animazione 1.309, film TV 901, muti 209, speciali TV 29, home video 28, non rilasciati 14, documentari 3, serial 7, musicali 7, sconosciuti 26, dubbi 53 (manga, anime, OVA, film TV…), altro 8. Esclusi: dettaglio per categoria nello stesso file (63 miniserie, 63 manga, 25 voci di genere, 33 esclusioni approvate in Fase 6, ecc.).

**25 trame:** *Nero-Fumo* usa la sola sezione «Trama» (2.030 car.); *Final Fantasy* tiene «Temi affrontati»; nessuna ha più `<ref>`, `{{`, `[[` o `''`; nessuna trama del catalogo supera 8.191 token (massimo 7.761); *Il re leone* e *Quinto potere* sono ora un solo punto ciascuno. Ogni correzione conserva lo SHA-256 dell'originale.

## Embedding
`python -m pipelines.wikipedia_films.indexing.v2 plan|embed|index|check|…`
- Riusati 41.112 vettori dagli shard verificati (stesso `film_id` e stesso hash del testo); **embeddati solo 25** testi.
- **Costo effettivo 0,003492 USD** (26.864 token), 1 richiesta, **4,3 s**, tetto 0,01. Nessun'altra chiamata a pagamento.
- Modello `text-embedding-3-large`, 1.536 dimensioni. I 25 nuovi vettori sono in `data/embeddings/…-v2/new_vectors.npz` (ricostruibili senza ripetere la chiamata).

## Qdrant `wikipedia_films_it_v2`
Creata in 96,5 s (+38 s di indicizzazione, stato green): **41.137 punti = 41.137 record**, 1 punto per film, cosine, 1.536 dimensioni, indici di payload come la v1 più `catalog_status` e `unverified` (booleano). Spazio su disco: 549 MB (v1: 526 MB).

| Verifica | Esito |
|---|---|
| Punti = record; `film_id` della collezione = quelli del dataset | sì (41.137 / 41.137) |
| **Ogni** punto contro il suo record: vettore, titolo, anno, trama, stato | 41.137 controllati, 0 errori |
| Esclusi presenti | 0 su 284 |
| 25 vettori nuovi (tutti) corrispondono ai nuovi testi | 25/25 |
| Punti con più chunk | 0 |
| Non verificati filtrabili (`unverified = true`) | 65 trovati = 65 attesi; verificati 41.072 |
| Collezioni vecchie intatte | sì (conteggi e digest degli id identici) |

## Test e benchmark (senza chiamate a pagamento)
- Test: 91 nella cartella (5 nuovi in questa fase: riconciliazione, riuso dei vettori, divieto di toccare le collezioni vecchie, esito dei report); suite del progetto 2.067 passati. Fase 1 `verify` OK.
- **72 query di Fase 2** (embedding in cache), contro la fonte dei film:

| | v1 (41.438 punti) | v2 (41.137 punti) |
|---|---|---|
| Hit@5 / Hit@10 / MRR@10 | 0,153 / 0,181 / 0,105 | 0,167 / 0,181 / 0,106 |
| Sovrapposizione top 10 v1–v2 | 99,4% | |
| Non film (esclusi) nelle top 10 | 4 su 720 | 0 |
| Doppioni nella top 10 | – | 0 |
| Non verificati nella top 10 | – | 0 |

I valori assoluti sono bassi per costruzione (l'intero corpus ha 41 volte i distrattori del benchmark di Fase 2); i giudizi LLM della Fase 2 coprono solo il 3% delle top 10, quindi qui non si può dire altro.
- **Richieste di genere e formato:** non ho potuto rilanciare le 8 frasi testuali, perché embeddarle sarebbe un'altra chiamata a pagamento (nel caso di dieci frasi circa 0,00001 USD). Come prova sostitutiva ho usato i vettori delle 236 pagine escluse (voci di genere, serie, ecc.) come query, il caso peggiore: nelle top 10 della v1 il 20,7% (489 su 2.360) dei risultati erano pagine escluse, nella v2 **0**.
- **25 trame corrette:** tutte recuperate al primo posto dal proprio nuovo vettore; la similarità tra vettore vecchio e nuovo va da 0,61 (minimo, verosimilmente le trame più contaminate) con mediana 0,80.

## Problemi ancora aperti
1. I **7 ibridi «in due serate»** e le interpretazioni 1–2 sopra.
2. **~9 film anime collegati** alle serie escluse (*Digimon* ecc.) non esistono come voci: servirebbe estrarre la loro trama dalla pagina.
3. Casi di confine del campione non decisi e quindi rimasti inclusi come verificati: *La notte quando è morto Pasolini*, *Il giovane Mussolini*, *Vette di libertà*, *2 Girls 1 Cup*, *Rabbits*, *Grachi Sweet 16*.
4. **Anomalie dei metadati** lasciate come sono (come deciso): 12 anni probabilmente sbagliati in `year`, 4 film del 2026 usciti dopo il dump, due IMDb condivisi, una coppia titolo+anno.
5. Le **query testuali di genere/formato** da rilanciare quando autorizzi ~10 embedding di query.
6. **Nessun alias** né passaggio di `rag_search` alla v2: non richiesti. Restano da fare il confronto di qualità vecchio/nuovo su domande reali (a pagamento) e l'adattamento di `rag_search`. `README.md`/`PROGRESS.md` sezione integrazione parallela vanno allineate.
