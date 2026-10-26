# Fase 2 - spike Qdrant embedded (2026-10-26)

Macchina: macOS 12.7.6 x86_64, Python 3.11.16, `qdrant-client` 1.20.0 (ultima su PyPI al momento della prova), numpy 2.2.6 nel venv dello spike.
Dati: i 42.522 punti reali, letti dalla **copia** di Chroma (non dall'originale), caricati in un Qdrant embedded in una cartella temporanea. Script: `spike_local.py` (risultati grezzi in `spike_local_result.json`).

## Misure (embedded, un processo)

| Misura | Qdrant embedded | Chroma (riferimento, stessa macchina) |
|---|---|---|
| Caricamento dei 42.522 punti | 70,6 s | - |
| Dimensione su disco | 742 MB | 808 MB |
| Apertura a freddo dell'indice | 11,7 s (24,8 s alla prima riapertura nello stesso processo) | 0,6 s |
| RSS dopo l'apertura | ~4,0 GB | ~0,36 GB |
| `query_points` top-50, p50 / p95 | 480 / 612 ms | 6,5 ms (p50) |
| `average_vector` (2 positivi, 1 negativo), p50 | 473 ms | - |
| `best_score` (stessi esempi), p50 | 1.756 ms | - |
| `scroll` con filtro su `title_norm`, p50 | 594 ms | - |
| Query con filtro `Range` su `release_year_int`, p50 | 998 ms | - |
| Scroll completo (sorgente dell'indice BM25) | 1,8 s | paginato, simile |

Il client emette un avviso a oltre 20.000 punti ("Local mode is not recommended..."): e' un avviso, non un errore; i dati sono stati caricati e interrogati senza problemi, ma le prestazioni sopra sono quelle da attendersi.

## Esattezza e funzioni verificate sul client 1.20.0

- Ricerca locale esatta: recall@10 = 1,0 e recall@50 = 1,0 su tutte le 28 query contro la scansione esatta della baseline.
- `average_vector` coincide con la formula `2*media(positivi) - media(negativi)` (stessi id e stessi punteggi).
- `best_score` funziona in locale; i suoi punteggi (0,69) non hanno la scala del coseno: non mescolare punteggi di strategie diverse.
- Esempi come id: l'id di riferimento e' escluso dai risultati. Esempi come vettori grezzi: il film di riferimento **compare** tra i risultati -> l'esclusione per `movie_id` e' obbligatoria (gia' nel piano).
- `Range` su `release_year` stringa: 0 risultati; su `release_year_int` intero: funziona (i campi numerici separati sono necessari).
- `create_payload_index` e `SearchParams(exact, hnsw_ef)` sono accettati e ignorati in locale.
- Un secondo client sulla stessa cartella solleva `RuntimeError` (cartella bloccata): un solo processo alla volta.
- **Vettori non bit-identici a Chroma**: Qdrant con distanza coseno normalizza i vettori in scrittura. I vettori OpenAI in Chroma hanno norma 1 +- 5e-4; differenza massima per componente 5,3e-5. La validazione "esatta" della Fase 3 va quindi riformulata: vettore Qdrant == vettore Chroma normalizzato entro tolleranza float32 (da fissare e registrare), non `array_equal`. Il ranking per coseno non cambia.

## Conclusioni (non soglie a priori)

- Funzionalmente embedded e' adeguato: strategie, filtri, esattezza, persistenza, lock.
- Come sostituto di Chroma per l'uso quotidiano e' molto piu' pesante: ~75x di latenza per query, ~11x di memoria, ~20-40x di tempo di avvio. Per `python app.py` e `web_api` (avvio a freddo di 12-25 s, ~4 GB) e' un peggioramento reale dell'esperienza.
- Il server (HNSW, indici di payload) e' la destinazione di pubblicazione e potrebbe eliminare questi costi, ma **non e' stato provato**: Docker non e' installato e il tentativo di eseguire il binario ufficiale scaricato e' stato negato dal sistema di permessi. Esito server: **APERTO**.

---

# Variante server (binario ufficiale 1.20.0, macOS x86_64, solo 127.0.0.1)

Server = release ufficiale `qdrant-x86_64-apple-darwin.tar.gz` v1.20.0 (SHA-256 `94a2e6f6...084f4d`, dimensione uguale a quella dichiarata da GitHub), eseguito dal binario, **non** dall'immagine Docker. Client e server sono alla stessa versione (1.20.0). Script: `spike_server.py` (risultati grezzi: `spike_server_result.json`). Collezione temporanea, cancellata a fine prova; server fermato.

Suite `tests/test_qdrant_store.py` con `QDRANT_URL` impostata: **44 passati** (le tre varianti `memory`, `embedded`, `server`), incluso il controllo che il server dichiari la versione pinnata.

| Misura (42.522 punti reali) | Server 1.20.0 | Embedded | Chroma |
|---|---|---|---|
| Query top-50, p50 / p95 | **5,8 / 9,7 ms** | 480 / 612 ms | 6,5 ms (p50) |
| `exact=True`, p50 | 17,1 ms | (sempre esatto) | - |
| `average_vector`, p50 | 6,1 ms | 473 ms | - |
| `best_score`, p50 | 9,0 ms | 1.756 ms | - |
| Filtro `Range` su `release_year_int`, p50 | 5,9 ms | 998 ms | - |
| `find_by_title` (indice keyword), p50 | 1,8 ms | 594 ms | - |
| Caricamento con indici di payload | 154 s | 71 s | - |
| Scroll completo | 3,5 s | 1,8 s | - |
| Throughput 1 / 4 / 8 client | 89 / 193 / 179 qps | un solo processo | - |

Qualita' dell'HNSW contro la ricerca esatta sulle 28 query della baseline (valori indicativi dello spike, **non** la valutazione formale di Fase 4):

| `hnsw_ef` | recall@10 (min) | recall@50 (min / media) | p50 |
|---|---|---|---|
| default | 1,00 | 0,98 / 0,9964 | 5,8 ms |
| 128 | 1,00 | 0,98 / 0,9986 | 6,1 ms |
| 256 | 1,00 | 1,00 / 1,00 | 10,2 ms |

- Raccomandazioni: `average_vector` e `best_score` danno recall@10 = 1,0 contro `exact=True` sia con `ef` di default sia con 128; i primi cinque titoli sono identici tra default, `ef128` ed esatta. Con `best_score` la precisione "cala ai default" per documentazione, ma su questo campione non e' misurabile; non dimostra nulla in generale.
- Query filtrata (anno intero): recall@50 = 1,0 contro l'esatta.
- Omonimi: `find_by_title("Alien")` restituisce *Alien* (1979) e *The Alien* (senza anno): la normalizzazione toglie l'articolo, quindi i due compaiono entrambi -> la risoluzione dei riferimenti dovra' trattarli come candidati multipli (gia' previsto: `ambiguous` senza anno).
- Validazione dei vettori (regola di `protocol.md`): su 29 punti la differenza massima tra vettore Qdrant e vettore Chroma normalizzato e' 1,5e-8 (tolleranza 1e-6): **ok sul campione**; la validazione di tutti i punti e' della Fase 3.
- Indicizzazione: la collezione e' `green` con 41.500 vettori su 42.522 indicizzati; il resto sta in un segmento piccolo sotto `indexing_threshold` (10.000), cercato per forza bruta. Normale; l'attesa "tutti indicizzati" del mio script era troppo rigida (timeout di 600 s senza conseguenze).

## Cosa resta APERTO

- L'immagine **Docker** non e' stata provata (Docker non installato): e' stato provato il binario ufficiale della stessa versione. Non cambia il motore, ma il criterio "compatibile con la distribuzione Docker" resta aperto fino a una prova con l'immagine `qdrant/qdrant:v1.20.0`.
- Carico reale con piu' processi dell'app (`web_api` con un worker) e persistenza tra riavvii del server non sono stati misurati.
- Chiave API / TLS del server: non configurati (solo localhost).

## Conclusione per lo sviluppo quotidiano

Il server e' alla pari con Chroma per latenza (5,8 ms contro 6,5 ms) e molto piu' leggero dell'embedded. Embedded (480 ms, ~4 GB, apertura 12-25 s) resta adatto a test e prototipi, non all'uso quotidiano. Proposta per le fasi successive: sviluppo contro il binario/server locale, embedded solo come fallback e per i test.
