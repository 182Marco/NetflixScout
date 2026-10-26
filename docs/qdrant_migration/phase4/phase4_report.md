# Fase 4 - parita' del retrieval Chroma <-> Qdrant (2026-10-26)

Dati: 28 query della baseline, stessi vettori di embedding e stessi segnali del parser salvati, indice reale di 42.522 punti.
Qdrant: server 1.20.0 (binario ufficiale) su 127.0.0.1, collezione migrata in Fase 3. Chroma: copia ripristinata dal backup.
Nessuna chiamata a pagamento. Soglie di `protocol.md`, non modificate: recall@10 >= 0,95, recall@50 >= 0,90, tolleranza 1e-4.
Dati grezzi: `parity_report.json`; tabella per query: `parity_per_query.md`; script: `parity.py`.

## Misurato

### Ricerca grezza top-50 contro la ricerca esatta (28 query)
| Motore | recall@10 media / min | recall@50 media / min | query sotto soglia (@10 / @50) |
|---|---|---|---|
| Chroma | 0,9786 / 0,80 | 0,9307 / 0,72 | 4 / 6 |
| Qdrant HNSW default | **0,9964** / 0,90 | **0,9929** / 0,96 | 1 (q17) / 0 |
| Qdrant `hnsw_ef`=128 | 1,0000 / 1,00 | 0,9964 / 0,98 | 0 / 0 |
| Qdrant `exact=True` | 1,0000 / 1,00 | 1,0000 / 1,00 | 0 / 0 |

- Soglie sulla media: rispettate da Qdrant default. Soglia per singola query: una eccezione, **q17** (recall@10 = 0,90, un vicino al confine dell'HNSW; Chroma ha 0,90 sulla stessa query; con `ef`=128 diventa 1,0). Il protocollo non dice se la soglia sia sulla media o per query: riportate entrambe.
- Rispetto a Chroma: Qdrant ha recall@10 peggiore in 0 query e migliore in 3; recall@50 peggiore in 1 (q06: 0,96 contro 0,98, risolta con `ef`=128) e migliore in 18.
- Scambi (un elemento esce dal top-k, un altro entra) rispetto all'esatta: Chroma 6 al k=10 e 97 al k=50; Qdrant default 1 e 10; `ef`=128 0 e 5.
- **Nessun pareggio numerico** (|dsim| <= 1e-4) in nessun confronto e **nessuna inversione di ordine** tra elementi comuni: ogni differenza e' uno scambio al bordo dell'approssimazione HNSW, non un riordino per punteggi uguali.
- Qdrant contro Chroma (stesso top-k): overlap medio 0,982 al k=10 (5 scambi) e 0,933 al k=50 (94 scambi). Questi non sono regressioni di Qdrant: rispetto all'esatta Qdrant e' piu' vicino di Chroma.

### Pipeline di produzione (`retrieval._retrieve`, k_largo=10, genre boost, penalita', esclusioni, `_light_rerank`)
| | Chroma = riferimento esatto | Qdrant = riferimento esatto |
|---|---|---|
| semantic (28 query) | 22 | **27** (unica differenza: q17, 1 scambio) |
| hybrid (28 query) | 24 | **28** |

- Qdrant e' piu' vicino al riferimento esatto di Chroma in 5 query semantic (q02, q12, q21, q26, q27) e **mai peggiore** (0 query).
- Metadati dei chunk sugli id comuni: identici in 28/28 query per entrambe le modalita'. Query di rerank (`compose_rerank_query`): uguale in 28/28.
- Insieme dei documenti inviati al reranker: uguale a quello di Chroma in 23/28 (semantic) e 25/28 (hybrid); le differenze coincidono con le query in cui Chroma si discosta dall'esatta.
- Il pool di Chroma oggi coincide con quello salvato nella baseline in 28/28 query (determinismo).
- BM25: i 42.522 chunk (id, testo, metadati) sono identici nei due indici; l'ordine dei chunk no (Chroma: inserimento; Qdrant: ordine UUID; **nessuno dei due e' ordinato per id**). Con pareggi BM25 questo puo' cambiare quali documenti entrano nel taglio: su dati sintetici con molti pareggi succede (test `test_bm25_index_and_scores_match`); sulle 28 query reali **non ha prodotto alcuna differenza** (hybrid con l'ordine di Qdrant = riferimento in 28/28). Ordinare per id non riprodurrebbe l'ordine di Chroma.
- Filtri nativi di Qdrant contro la forza bruta: esclusione per `movie_id` (3 film esclusi per query) recall@10 medio 0,9964, **0 riferimenti trapelati**; filtro intero sull'anno 1950-1969 recall@10 medio 0,9964, recall@50 0,9979.

### Test offline (vettori controllati, Chroma reale e Qdrant in memoria)
`search` identico (id, ordine, punteggi entro 1e-5, metadati) in 8 scenari: base, pool largo, k oltre la collezione, boost di genere, genere escluso, esclusione per titolo, segnali negativi, tutto insieme; forma di `query`; paginazione `get` (sequenziale, con salto, oltre la fine); indice BM25; `_retrieve` semantic e hybrid; interruttore `engine`; modello sbagliato rifiutato. Un bug reale trovato e corretto dai test: `get` oltre la fine ricominciava dalla prima pagina.

## Non misurato (verifiche mancanti)
- **Qualita' e comportamento del reranker Cohere**: il reranker e' sostituito da uno stub. Verificato solo che riceverebbe gli stessi documenti; l'uguaglianza delle risposte finali con lo stub (28/28 semantic, 27/28 hybrid) NON e' una prova sul reranker reale.
- I segnali del parser sono quelli salvati: non e' stata rieseguita la chiamata LLM.
- Latenza della pipeline completa e dell'app: misurata solo la ricerca grezza (Fase 2).
- Modalita' `embedded` attraverso l'adattatore su dati reali; immagine Docker; piu' processi dell'app; `python app.py` e web API con `engine = qdrant` (Fase 6).
- Risposte finali del bot e valutazione umana della qualita' (Fase 7).

## Decisioni e correzioni in questa fase
- Nessuna correzione al comportamento di Qdrant: nessuna regressione reale e' emersa. Nessuna modifica proposta all'ordine BM25.
- Difetto nella MIA metrica corretto durante la fase: il primo conteggio dei "pareggi" era unilaterale e gonfiava i numeri. Ora uno scambio e' un pareggio solo se le due similarita' differiscono di <= 1e-4 (test in `tests/test_qdrant_parity_metrics.py`). Le soglie non sono cambiate.
