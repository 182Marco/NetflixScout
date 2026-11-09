# Fase 2 — Benchmark delle strategie di preparazione e embedding delle trame

Stato: **benchmark concluso, in attesa di approvazione**. Nessun embedding o sintesi dell'intero dataset, nessun indice Qdrant, nessuna integrazione, nessun commit. I risultati della Fase 1 (README e PROGRESS) non sono stati toccati.

Codice e dati in `benchmark/` (gli artefatti stanno in `benchmark/results/`, ignorata da git). Ogni numero è marcato **[misurato]** o **[proiezione]**.

## 1. Statistiche reali delle 41.421 trame [misurato]

Tokenizer `cl100k_base` (quello di `text-embedding-3-*`), `benchmark/plot_stats.py`.

| | token |
|---|---|
| totale | 23.925.910 (82,9 M caratteri, 3,47 caratteri/token) |
| media / mediana | 577,6 / 365 |
| min / max | 99 / 21.896 |
| deviazione standard | 550 |
| percentili 1 / 5 / 10 / 25 | 117 / 131 / 149 / 212 |
| percentili 75 / 90 / 95 / 99 / 99,9 | 776 / 1.306 / 1.651 / 2.409 / 3.933 |

Distribuzione: <150: 4.230 · 150–300: 12.668 · 300–500: 8.561 · 500–800: 5.973 · 800–1.200: 4.866 · 1.200–2.000: 4.164 · 2.000–4.000: 919 · 4.000–8.191: 35 · >8.191: **5**.

- Il limite di input dei modelli `text-embedding-3-*` è 8.191 token: **solo 5 trame su 41.421 lo superano**. Le altre stanno intere in un solo embedding (nel benchmark le 5 sono troncate a 8.000 token).
- Trame >1.000 token: 7.314 (17,7%) · >2.000: 958 · >4.000: 40 · oltre media+3σ: 607.
- Tenere ogni trama intera in un embedding è quindi tecnicamente possibile. Resta la domanda di qualità (un vettore per 5.000 token può diluire i dettagli), che il benchmark misura.

## 2. Metodologia

**Corpus del benchmark [misurato]**: pool di **1.000 film** (1.041.782 token, media 1.042, mediana 679), campionato con seme fisso e stratificato per lunghezza, con le trame lunghe volutamente sovrarappresentate (150/200/200/200/150/100 film nei sei intervalli). Dentro il pool: **campione di valutazione di 150 film** e **72 film sorgente** delle query (18 per ognuno di 4 intervalli di lunghezza, 250–500, 500–1.000, 1.000–2.000, >2.000).

**Strategie** (testo da incorporare; ogni vettore conserva il `film_id`):

| | descrizione |
|---|---|
| **A** | trama integrale, 1 vettore per film |
| **B1** | sintesi LLM moderata: ≈40% delle parole originali, tra 90 e 250 parole |
| **B2** | sintesi LLM forte: ≈15%, tra 40 e 90 parole |
| **C500** | chunking delle trame >1.000 token, chunk ≈500 token (frasi intere, 1 frase di sovrapposizione); le altre restano un vettore |
| **C250** | come C500 con chunk ≈250 token, per le trame >500 token |

Le sintesi usano `gpt-5.6-luna` (il modello del progetto) con un prompt che impone di conservare personaggi, relazioni, motivazioni, conflitti principali e secondari, sviluppo fino alla conclusione, temi e sottotesti, elementi distintivi, senza inventare. Una trama già vicina alla lunghezza obiettivo (≤1,25×) resta originale (154 su 2.000 casi). Per i film chunked il punteggio del film è il **massimo** della similarità coseno tra i suoi vettori.

**Modelli**: `text-embedding-3-small` (1.536), `text-embedding-3-large` (3.072), `large` ridotto a 1.536 (e, come informazione aggiuntiva, a 1.024). La riduzione è fatta troncando e rinormalizzando il vettore a 3.072, quello che fa il parametro `dimensions`: verificato sull'API su 5 testi, coseno 0,9997–1,0000.

**Query [misurato]**: 72, 12 per tipo (analogia narrativa, temi e conflitti, trasformazione psicologica, atmosfera e situazione, più sottotrame, richiesta combinata). Scritte in italiano da `gpt-5.6-luna` a partire dalla trama **originale** di un film sorgente, senza nomi né luoghi e con parafrasi invece delle parole della trama. Sovrapposizione lessicale media tra query e trama sorgente (parole ≥4 lettere): 20%.

**Pertinenza**: *pooling*. Per ogni query si uniscono i primi 10 di tutte le 15 combinazioni strategia×modello (small, large, large-1536), in tutto 2.485 coppie query–film; un giudice LLM assegna 0/1/2 leggendo la trama **originale** (mai la sintesi; trame oltre 1.500 token mostrate come primi 1.200 + ultimi 300). Il film sorgente vale 2 per costruzione. Il giudice non vede la fonte né il sistema. In media 15,75 film con grado ≥1 e 2,64 con grado 2 per query.

**Metriche** (K=5 e 10): Precision@K (grado ≥1) e Precision stretta (grado 2); Recall@K rispetto all'insieme pertinente del pool; nDCG@K con guadagno = grado. In più due misure **oggettive** che non dipendono dal giudice: *Hit@K* (il film sorgente è tra i primi K) e MRR. Differenze con intervallo di confidenza al 95% da bootstrap appaiato sulle query (4.000 ricampionamenti).

**Affidabilità del giudice [misurato]**: il film sorgente è giudicato pertinente (≥1) in 72/72 casi (grado 2 in 71); rigiudicando 213 coppie di 6 query con una seconda chiamata indipendente: accordo esatto 83,6%, sulla pertinenza sì/no 88,3%, entro un grado 100%.

## 3. Risultati del retrieval [misurato]

72 query, 2.498 giudizi. Ordinati per nDCG@10 (large-1024 omesso: è un controllo aggiuntivo, mai migliore del 1536, vedi `results/metrics.json`).

| strategia | modello | Hit@5 | Hit@10 | MRR | P@5 | P@10 | R@10 | nDCG@5 | nDCG@10 |
|---|---|---|---|---|---|---|---|---|---|
| B1 | large-3072 | .667 | .736 | .464 | .714 | .637 | .451 | .662 | **.663** |
| B1 | large-1536 | .653 | .750 | .466 | .711 | .636 | .446 | .653 | .656 |
| C500 | large-3072 | .639 | .708 | .463 | .739 | .626 | .441 | .654 | .648 |
| C500 | large-1536 | .611 | .708 | .443 | .731 | .622 | .436 | .646 | .641 |
| A | large-3072 | .625 | .681 | .469 | .717 | .622 | .436 | .644 | .639 |
| A | large-1536 | .611 | .708 | .442 | .706 | .624 | .439 | .626 | .635 |
| C250 | large-3072 | .597 | .694 | .430 | .711 | .624 | .443 | .618 | .629 |
| C250 | large-1536 | .611 | .694 | .440 | .692 | .626 | .448 | .608 | .626 |
| B2 | large-3072 | .583 | .681 | .403 | .681 | .600 | .427 | .596 | .605 |
| B2 | large-1536 | .583 | .694 | .407 | .669 | .596 | .421 | .591 | .598 |
| C500 | small-1536 | .333 | .375 | .223 | .481 | .447 | .310 | .403 | .422 |
| A | small-1536 | .319 | .375 | .198 | .506 | .456 | .319 | .407 | .421 |
| B1 | small-1536 | .375 | .417 | .191 | .486 | .436 | .300 | .396 | .406 |
| C250 | small-1536 | .292 | .431 | .186 | .458 | .418 | .284 | .370 | .389 |
| B2 | small-1536 | .319 | .431 | .219 | .414 | .385 | .269 | .359 | .378 |

### Differenze con intervallo di confidenza al 95% (bootstrap appaiato)

| confronto | nDCG@10 | Hit@10 |
|---|---|---|
| **large vs small** (A, stessa strategia) | **+0,218** [+0,180, +0,252] | **+0,306** [+0,194, +0,431] |
| large vs small a pari dimensioni (A, 1.536) | +0,214 [+0,178, +0,249] | +0,333 [+0,222, +0,444] |
| large 1.536 vs 3.072 (A) | −0,003 [−0,016, +0,008] | +0,028 [0,000, +0,069] |
| large 1.536 vs 3.072 (B1) | −0,007 [−0,018, +0,004] | +0,014 [0,000, +0,042] |
| B1 vs A (large) | +0,024 [−0,002, +0,051] | +0,056 [0,000, +0,125] |
| B2 vs A (large) | **−0,033** [−0,064, −0,002] | 0,000 [−0,083, +0,083] |
| C500 vs A (large) | +0,009 [−0,009, +0,027] | +0,028 [−0,028, +0,083] |
| C250 vs A (large) | −0,010 [−0,033, +0,013] | +0,014 [−0,083, +0,111] |

Solo sulle 36 query il cui film sorgente ha >1.000 token: B1 vs A nDCG@10 +0,047 [+0,011, +0,085]; C500 vs A +0,022 [−0,007, +0,051]; C250 vs A +0,007 [−0,025, +0,040]; B2 vs A +0,014 [−0,026, +0,053].

### Per tipo di query (A, large-3072; nDCG@10 / Hit@10)

analogia .700/.917 · atmosfera .687/.750 · più sottotrame .675/.667 · trasformazione psicologica .635/.333 · temi e conflitti .610/.750 · combinata .524/.667. Con `small` (A): analogia .457/.583 · multi-sottotrama .464/.583 · atmosfera .426/.250 · temi .424/.250 · psicologica .387/.167 · combinata .367/.417.
La trasformazione psicologica ha il Hit@10 più basso con `large` (le query descrivono uno stato interiore e molti film diversi lo condividono: il film sorgente è spesso preceduto da alternative valide), le richieste combinate il nDCG più basso.

### Per lunghezza del film sorgente (Hit@10, large-3072)

| | 250–500 | 500–1.000 | 1.000–2.000 | >2.000 |
|---|---|---|---|---|
| A | .722 | .611 | .722 | .667 |
| B1 | .778 | .667 | .833 | .667 |
| B2 | .667 | .667 | .722 | .667 |
| C500 | .722 | .611 | .722 | .778 |
| C250 | .778 | .556 | .722 | .722 |

Ogni cella ha 18 query: le differenze tra celle non sono significative.

## 4. Esempi concreti (`benchmark/examples.py`)

Con large-3072 e la trama integrale, il film sorgente è primo in 25 query su 72 e non è nei primi 10 in 23.

- **Riuscito**, q00 (analogia): la richiesta descrive un giovane idealista contro una grande organizzazione economica che si innamora, senza saperlo, della sua dirigente. *Giovanotto mi piacete* (1925) è primo con `large` e solo 15° con `small`.
- **Riuscito solo con large**, q06: un uomo in fuga scambiato per un agente infiltrato in un territorio esotico. *L'avventuriero di Macao* (1952): 2° con `large`, 38° con `small`. In 17 query il film è nei primi 3 con `large` e fuori dai primi 10 con `small`.
- **Fallito**, q09 (atmosfera): famiglia divisa da un conflitto fratricida in una casa isolata. *Dan* (1914) non compare nei primi 100 con nessuna strategia; i risultati sono melodrammi plausibili (uno giudicato 2).
- **Fallito ma con alternativa valida**, q07 (noir): il film sorgente è 11° con A, ma tra i primi 3 c'è un film giudicato 2. Per questo Hit@K da solo sottostima i sistemi, e nDCG/P@K sono più equi.
- **Il chunking aiuta**, q64 (multi-sottotrama, *Tenet*, 2.637 token): rango 17 con A, **3 con C500**. Capita in 2 query su 72.
- **La sintesi aiuta**, q31 (*La vita davanti a sé*, 924 token): rango 17 con A, **2 con B1**. Capita in 1 query su 72.

## 5. Valutazione delle sintesi [misurato]

Checklist estratta dalla trama originale (categorie: motivazioni, conflitto principale, conflitti secondari, evoluzione della storia, temi e sottotesti, relazioni, elementi distintivi) e verificata su ogni sintesi dal giudice LLM; 80 film del campione (70 per B1, perché in 10 casi B1 ha lasciato la trama originale).

| | B1 | B2 |
|---|---|---|
| lunghezza rispetto all'originale (token) | 39% | 22% |
| copertura media della checklist | **87,5%** (p10 75%) | **72,9%** (p10 50%) |
| motivazioni / conflitto principale | 89% / 94% | 77% / 82% |
| conflitti secondari / evoluzione | 88% / 95% | 68% / 85% |
| temi e sottotesti | **77%** | **62%** |
| relazioni / elementi distintivi | 85% / 89% | 71% / 66% |
| affermazioni segnalate come non supportate (media per sintesi) | 1,51 | 1,18 |
| sintesi con almeno una segnalazione | 55/70 (79%) | 43/80 (54%) |

Le sintesi perdono di più proprio ciò che il prodotto cerca: temi e sottotesti, conflitti secondari. Le segnalazioni di "non supportato" sono un misto: leggendo a mano 10 casi (campione piccolo, giudizio mio) circa 4 erano errori fattuali veri (chi sottrae il codice bancario, chi segue chi, il ceto di un personaggio, chi organizza un rapimento), gli altri sfumature interpretative. Il costo di un errore fattuale in una sintesi: viene incorporato e non è recuperabile dall'indice, mentre l'originale è sempre disponibile.

## 6. Costi, dimensioni e tempi

### Costo del benchmark [misurato, dal registro delle chiamate]

| voce | USD |
|---|---|
| sintesi del pool (1.846 chiamate, 2 livelli) | 1,651 |
| embedding (313 chiamate, 6,75 M token, small + large) | 0,506 |
| giudizi di pertinenza (274 chiamate) | 0,535 |
| verifica di fedeltà (230 chiamate) | 0,305 |
| generazione query (72) + controlli del giudice (95) | 0,072 |
| **totale** | **3,07** (budget autorizzato 5,00; tetto nel codice 4,00) |

### Intero dataset (41.421 film), per strategia

Token e vettori di A, C500, C250 sono **misurati** (tutti i film chunkizzati davvero, senza embedding); i token di B1/B2 sono **proiezione** (lunghezza obiettivo); i prezzi sono quelli standard del 2026-11-04.

| strategia | vettori (per film) | token da incorporare | embedding small | embedding large | sintesi LLM [proiezione] |
|---|---|---|---|---|---|
| A | 41.421 (1,00) | 23,90 M | 0,48 $ | 3,11 $ | — |
| B1 | 41.421 (1,00) | 9,8 M | 0,20 $ | 1,27 $ | **≈ 27,8 $** (31.915 chiamate) |
| B2 | 41.421 (1,00) | 3,9 M | 0,08 $ | 0,51 $ | ≈ 29,8 $ (41.421 chiamate) |
| C500 | 61.907 (1,50) | 24,9 M | 0,50 $ | 3,24 $ | — |
| C250 | 117.764 (2,84) | 26,1 M | 0,52 $ | 3,39 $ | — |

La proiezione delle sintesi usa la lunghezza reale di ogni trama e il consumo reale per parola obiettivo, compreso il ragionamento interno del modello (≈418 token di output costanti più ≈1,14 token per parola); applicata al pool riproduce il costo reale entro il 2,5% (0,86 $ contro 0,84 $ per B1, 0,83 $ contro 0,81 $ per B2). Con la Batch API (−50%) le sintesi B1 costerebbero circa 14 $.

### Spazio dei vettori [misurato: aritmetica float32]

| configurazione | vettori | 1.536 dim | 3.072 dim |
|---|---|---|---|
| A / B1 / B2 (1 per film) | 41.421 | 254,5 MB | 509,0 MB |
| C500 | 61.907 | 380,4 MB | 760,7 MB |
| C250 | 117.764 | 723,5 MB | 1.447 MB |

**Qdrant [proiezione]**: la collezione attuale `netflix_scout` pesa 480 MB su disco per 42.522 punti da 1.536 dimensioni, cioè 11,3 KB/punto, di cui 6,1 KB di vettore e circa 5,1 KB di payload e indice HNSW (m=16). Per la strategia A con large a 1.536 dimensioni: 41.421 × ≈11,3 KB ≈ **470 MB**; con large a 3.072: 41.421 × ≈17,4 KB ≈ **720 MB**; C500: ≈ 700 MB (a 1.536). Il payload effettivo dipende dai campi scelti: `films.jsonl` da solo pesa 130 MB (3,1 KB/film).

### Tempi

Misurati nel benchmark (6 richieste in parallelo per l'LLM, batch da 64 sequenziali per gli embedding): 1.846 sintesi in 37 min (0,82 chiamate/s); 313 chiamate di embedding per 6,75 M token in 19 min (≈ 5,8 k token/s); 274 chiamate di giudizio in 5 min. **Proiezioni**: embedding della strategia A su tutto il dataset ≈ 70 min per modello con la stessa implementazione (parallelizzabile); sintesi B1 ≈ 11 ore con 6 richieste parallele.

## 7. Raccomandazione

**Strategia A con `text-embedding-3-large` a 1.536 dimensioni: la trama integrale, un vettore per film.**

1. **Il modello pesa più di ogni altra scelta.** `large` batte `small` di +0,22 nDCG@10 e +0,31 Hit@10, con intervalli di confidenza lontani da zero, in tutti i tipi di query e in tutte le strategie. L'effetto è più grande di tutte le differenze tra strategie messe insieme.
2. **1.536 dimensioni non costano qualità.** −0,003 nDCG@10 [−0,016, +0,008]: lo stesso spazio della collezione attuale (254 MB per i vettori contro 509 MB) e identico a `small` come dimensione.
3. **La trama integrale non è battuta da nessuna alternativa in modo affidabile.** B1 sembra migliore (+0,024 nDCG@10) ma l'intervallo include zero (significativo solo sulle trame lunghe, +0,047) e costerebbe ≈ 28 $ di LLM, circa 11 ore e il rischio di errori fattuali incorporati nel vettore (≈ 79% delle sintesi con una segnalazione, di cui forse 4 su 10 errori veri). B2 è peggio (−0,033, significativo) e perde temi e sottotesti. Il chunking non dà vantaggi dimostrati (C500 +0,009, C250 −0,010, intervalli attorno a zero) e costa 1,5–2,8 volte i vettori.
4. **Costo e tempo piccoli:** circa 3,1 $ di embedding e circa 70 min per tutto il dataset (proiezioni).

**Cosa non è dimostrato** (cosa vorrei verificare se si vuole andare oltre): le trame molto lunghe (>2.000 token, 958 film) sono l'unica zona dove B1 e il chunking mostrano indizi di vantaggio; con 18 query per intervallo non si può concludere. Un'estensione economica sarebbe un secondo giro solo su queste, o una variante "film intero più chunk per le trame >2.000 token". Non la raccomando in anticipo: i dati non la sostengono.

## 8. Limiti da tenere presenti

- **72 query**: differenze sotto circa 0,03 nDCG@10 non sono rilevabili; i dettagli per tipo (12 query) o per lunghezza (18) sono indicativi.
- **Pool di 1.000 film, non 41.421**: la densità di film simili è molto più bassa che nel dataset vero; i valori assoluti sulla collezione completa saranno inferiori, e l'ordine tra le strategie non è garantito.
- **Query scritte dall'LLM a partire dalla trama originale**: favoriscono la trama integrale rispetto alle sintesi (anche se la sovrapposizione lessicale è solo del 20%); inoltre query, sintesi e giudice sono dello stesso modello (`gpt-5.6-luna`), possibile correlazione non misurata. Il giudice legge sempre l'originale.
- **Pertinenza da pooling**: i film fuori dall'unione dei primi 10 contano come non pertinenti; il Recall@K è relativo all'insieme giudicato (large-1024 non è nel pool, quindi i suoi numeri sono prudenti). Il giudice ha un accordo del 84% con sé stesso: i valori di P@K e nDCG@K hanno questa incertezza, uguale per tutti i sistemi. Hit@K sul film sorgente è oggettivo ma penalizza le alternative valide.
- Solo query in italiano; nessun confronto con una ricerca lessicale (BM25) né con il reranking (Cohere), che nel sistema attuale agirebbe dopo il retrieval.
- Una sola esecuzione delle sintesi (prompt e modello fissi) e una sola riga di controllo manuale (10 casi) sulle segnalazioni di fedeltà.
- Costo e tempo delle sintesi dell'intero dataset sono proiezioni; i tempi dipendono dal limite di richieste dell'account.

## 9. Riproduzione

```bash
pip install -r pipelines/wikipedia_films/benchmark/requirements.txt      # tiktoken (solo benchmark)
cd pipelines/wikipedia_films/benchmark
python plot_stats.py && python sample.py                          # gratis
python summarize.py && python queries.py && python embed.py      # a pagamento (OPENAI_API_KEY da .env)
python judge.py && python fidelity.py 80 && python judge_checks.py   # a pagamento
python metrics.py && python compare.py && python examples.py && python projections.py   # gratis
```
Le chiamate a pagamento hanno tetto di 4 USD (`common.BUDGET_CAP_USD`), registro in `results/cost_ledger.jsonl` e cache degli embedding per testo.
