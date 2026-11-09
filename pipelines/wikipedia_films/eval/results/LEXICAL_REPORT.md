# Componente lessicale: parole rare di trama (UN solo ranking denso in ogni variante)

40 domande generate da termini presenti in al più 2 trame.

| Variante | hit@1 | hit@5 | hit@10 | trovata (top 50) |
|---|---|---|---|---|
| D0 solo denso | 0.38 | 0.47 | 0.57 | 0.68 |
| L1 denso + filtro full-text Qdrant | 0.95 | 1.00 | 1.00 | 1.00 |
| L2 candidati BM25 ordinati dal punteggio denso | 0.50 | 0.68 | 0.82 | 0.90 |
| BM25 da solo (riferimento, non candidato) | 0.65 | 0.78 | 0.80 | 0.90 |
