# Fase 5 - valutazione qualitativa cieca: riepilogo per variante

**Valutatore: il modello (non una persona).** Cecita' imperfetta: le metriche automatiche aggregate erano gia' note, la mappa etichetta-variante no. Un solo valutatore: evidenza indicativa, non statistica. I punteggi sono 0/1/2 per elenco di 5 risultati.

## A. Risultati numerici (punteggi medi per variante)

| variante | pertinenza | vicinanza | assenza del tratto da evitare | fatti |
|---|---|---|---|---|
| A ricerca normale | 1.391 | 1.0 | 1.571 | 1.957 |
| B average_vector | 1.217 | 0.952 | 1.857 | 1.957 |
| C best_score | 1.0 | 0.714 | 1.619 | 1.957 |

Casi per dimensione: {'pertinenza': 23, 'vicinanza': 21, 'assenza': 21, 'fatti': 23} (vicinanza e assenza esistono solo dove la scheda ha film piacevoli / da evitare).

Confronto accoppiato con A (numero di casi migliori / uguali / peggiori):

| variante | pertinenza | vicinanza | assenza | fatti |
|---|---|---|---|---|
| B average_vector | 2/17/4 | 6/9/6 | 4/17/0 | 1/21/1 |
| C best_score | 1/14/8 | 4/8/9 | 5/12/4 | 0/23/0 |

## B. Per caso (P/V/A/F per A | B | C)

| caso | A | B | C |
|---|---|---|---|
| c01 | 1/1/2/2 | 1/1/2/2 | 1/1/2/2 |
| c02 | 2/2/2/2 | 2/1/2/2 | 2/1/2/2 |
| c03 | 1/0/2/1 | 1/1/2/2 | 1/1/2/1 |
| c04 | 1/1/1/2 | 1/1/2/2 | 1/1/1/2 |
| c05 | 2/1/0/2 | 0/1/2/2 | 0/0/1/2 |
| c06 | 2/1/1/2 | 2/2/1/2 | 0/0/2/2 |
| c07 | 2/2/2/2 | 2/1/2/2 | 1/0/1/2 |
| c08 | 1/0/-/2 | 1/1/-/2 | 0/0/-/2 |
| c09 | 2/1/-/2 | 2/1/-/2 | 1/0/-/2 |
| c10 | 1/-/0/2 | 1/-/2/1 | 1/-/1/2 |
| c11 | 2/-/2/2 | 1/-/2/2 | 2/-/2/2 |
| c12 | 1/1/2/2 | 1/2/2/2 | 1/2/2/2 |
| c13 | 1/0/2/2 | 1/1/2/2 | 1/1/1/2 |
| c14 | 2/2/1/2 | 2/1/1/2 | 2/2/1/2 |
| c15 | 1/0/2/2 | 2/1/2/2 | 1/1/1/2 |
| c16 | 1/1/2/2 | 1/1/2/2 | 0/0/1/2 |
| c17 | 1/1/1/2 | 1/0/2/2 | 1/1/2/2 |
| c18 | 2/2/2/2 | 0/0/2/2 | 1/1/2/2 |
| c20 | 2/1/2/2 | 1/0/2/2 | 2/1/2/2 |
| c25 | 1/1/2/2 | 2/1/2/2 | 1/1/2/2 |
| c26 | 1/1/1/2 | 1/1/1/2 | 1/0/2/2 |
| c27 | 1/1/2/2 | 1/1/2/2 | 0/0/2/2 |
| c28 | 1/1/2/2 | 1/1/2/2 | 2/1/2/2 |
