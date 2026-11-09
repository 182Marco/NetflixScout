# Confronto A/B live: vecchio RAG (`netflix_scout`) contro nuovo RAG (`wikipedia_films_it_v3`)

Metriche calcolate sulle liste di 5 film. *Violazione* = il film mostra un tratto da evitare, è un titolo/franchise escluso (giudice cieco O controllo deterministico della batteria). *Pertinente* = ha il genere e le caratteristiche volute. *Valido* = pertinente e senza violazioni. Le domande H (contraddittorie) sono escluse dalle percentuali e valutate nella parte sulle risposte.

## 1. Strategie di recupero (stesso algoritmo su entrambi i corpus dove possibile)

| Sistema | Violazioni | di cui titolo/franchise | di cui tratti | Pertinenti | Validi | Genere ok | Liste con violazione | Validi di S0 persi | s |
|---|---|---|---|---|---|---|---|---|---|
| NEW-S0 | 47% | 86 | 46 | 71% | 35% | 91% | 40/56 | 0/99 | 0.61 |
| NEW-S1 | 40% | 57 | 55 | 69% | 39% | 89% | 35/56 | 2/99 | 0.46 |
| NEW-S2n | 26% | 17 | 55 | 67% | 50% | 88% | 29/56 | 2/99 | 0.34 |
| NEW-S2f | 23% | 7 | 58 | 65% | 51% | 87% | 25/56 | 5/99 | 0.57 |
| NEW-S3 | 37% | 84 | 20 | 70% | 40% | 88% | 37/56 | 18/99 | 0.34 |
| NEW-S3b | 38% | 84 | 21 | 70% | 40% | 88% | 37/56 | 16/99 | 0.35 |
| NEW-S4 | 47% | 86 | 46 | 71% | 35% | 91% | 40/56 | 0/99 | 0.35 |
| NEW-S5 | 10% | 3 | 26 | 62% | 58% | 83% | 18/56 | 21/99 | 0.36 |
| NEW-S6 | 4% | 0 | 10 | 82% | 80% | 90% | 8/56 | 57/99 | 9.75 |
| OLD-S0 | 37% | 58 | 46 | 53% | 29% | 83% | 40/56 | 0/82 | 0.57 |
| OLD-S1 | 34% | 43 | 52 | 51% | 32% | 82% | 37/56 | 2/82 | 0.38 |
| OLD-S2n | 25% | 17 | 53 | 49% | 38% | 80% | 32/56 | 2/82 | 0.3 |
| OLD-S3 | 29% | 56 | 25 | 47% | 28% | 73% | 32/56 | 26/82 | 0.3 |
| OLD-S3b | 29% | 56 | 24 | 47% | 28% | 73% | 31/56 | 26/82 | 0.31 |
| OLD-S4 | 37% | 58 | 45 | 53% | 30% | 83% | 39/56 | 0/82 | 0.31 |
| OLD-S5 | 16% | 17 | 27 | 44% | 38% | 70% | 24/56 | 26/82 | 0.32 |
| OLD-S6 | 4% | 1 | 11 | 72% | 70% | 89% | 8/56 | 42/82 | 9.23 |
| OLD-NATIVE | 10% | 5 | 23 | 71% | 66% | 94% | 16/56 | 82/82 | 11.84 |

## 2. Per categoria (violazioni / validi)

| Sistema | A | B | C | D | E | F | G | H |
|---|---|---|---|---|---|---|---|---|
| NEW-S0 | 62% / 26% | 86% / 6% | 28% / 60% | 73% / 20% | 60% / 37% | 18% / 50% | 0% / 55% | 60% / 20% |
| NEW-S1 | 48% / 34% | 76% / 12% | 28% / 60% | 53% / 27% | 53% / 40% | 18% / 50% | 0% / 55% | 57% / 20% |
| NEW-S2n | 48% / 34% | 18% / 56% | 28% / 60% | 53% / 27% | 17% / 70% | 18% / 50% | 0% / 55% | 57% / 20% |
| NEW-S2f | 48% / 34% | 14% / 60% | 28% / 60% | 53% / 27% | 0% / 73% | 18% / 50% | 0% / 55% | 57% / 20% |
| NEW-S3 | 42% / 38% | 86% / 6% | 18% / 68% | 47% / 30% | 57% / 37% | 5% / 55% | 0% / 55% | 43% / 23% |
| NEW-S3b | 42% / 36% | 86% / 6% | 15% / 68% | 50% / 30% | 57% / 37% | 8% / 52% | 0% / 55% | 43% / 23% |
| NEW-S4 | 62% / 26% | 86% / 6% | 28% / 60% | 73% / 20% | 60% / 37% | 18% / 50% | 0% / 55% | 60% / 20% |
| NEW-S5 | 24% / 46% | 8% / 66% | 18% / 68% | 13% / 47% | 0% / 70% | 5% / 55% | 0% / 55% | 40% / 23% |
| NEW-S6 | 10% / 66% | 0% / 96% | 8% / 72% | 7% / 67% | 0% / 97% | 0% / 82% | 0% / 78% | 20% / 37% |
| OLD-S0 | 40% / 32% | 67% / 27% | 25% / 45% | 50% / 13% | 53% / 37% | 25% / 25% | 0% / 25% | 43% / 27% |
| OLD-S1 | 36% / 34% | 57% / 37% | 25% / 45% | 50% / 17% | 47% / 37% | 25% / 25% | 0% / 25% | 43% / 27% |
| OLD-S2n | 36% / 34% | 31% / 59% | 25% / 45% | 50% / 17% | 7% / 60% | 25% / 25% | 0% / 25% | 43% / 27% |
| OLD-S3 | 24% / 32% | 67% / 27% | 15% / 45% | 30% / 7% | 50% / 37% | 15% / 22% | 0% / 25% | 30% / 33% |
| OLD-S3b | 24% / 32% | 67% / 27% | 12% / 45% | 30% / 7% | 50% / 37% | 15% / 22% | 0% / 25% | 30% / 33% |
| OLD-S4 | 40% / 32% | 67% / 27% | 25% / 45% | 50% / 13% | 53% / 37% | 22% / 28% | 0% / 25% | 40% / 27% |
| OLD-S5 | 16% / 36% | 31% / 59% | 15% / 45% | 23% / 13% | 7% / 57% | 15% / 22% | 0% / 25% | 23% / 40% |
| OLD-S6 | 8% / 56% | 0% / 98% | 15% / 62% | 0% / 53% | 0% / 100% | 5% / 80% | 0% / 42% | 0% / 70% |
| OLD-NATIVE | 20% / 58% | 4% / 74% | 20% / 75% | 7% / 77% | 10% / 77% | 8% / 80% | 0% / 28% | 10% / 47% |

Categorie: **A** genere da mantenere, elemento specifico da escludere; **B** stesso genere, diverso dal riferimento (titoli e franchise); **C** preferenze negative multiple; **D** positive e negative con più riferimenti; **E** le esclusioni non distruggono la pertinenza; **F** genere mantenuto, sottogeneri evitati; **G** ricerca semantica e lessicale; **H** robustezza e richieste contraddittorie

## 3. Esclusioni espresse in linguaggio naturale (A, C, D, F) e come titoli/franchise (B, E)

| Sistema | Violazioni NL | Validi NL | Violazioni titoli | Validi titoli |
|---|---|---|---|---|
| NEW-S0 | 44% | 39% | 76% | 18% |
| NEW-S1 | 36% | 43% | 68% | 22% |
| NEW-S2n | 36% | 43% | 18% | 61% |
| NEW-S2f | 36% | 43% | 9% | 65% |
| NEW-S3 | 28% | 48% | 75% | 18% |
| NEW-S3b | 28% | 47% | 75% | 18% |
| NEW-S4 | 44% | 39% | 76% | 18% |
| NEW-S5 | 16% | 54% | 5% | 68% |
| NEW-S6 | 6% | 72% | 0% | 96% |
| OLD-S0 | 34% | 30% | 62% | 30% |
| OLD-S1 | 33% | 31% | 53% | 37% |
| OLD-S2n | 33% | 31% | 22% | 59% |
| OLD-S3 | 21% | 28% | 61% | 30% |
| OLD-S3b | 20% | 28% | 61% | 30% |
| OLD-S4 | 34% | 31% | 62% | 30% |
| OLD-S5 | 17% | 31% | 22% | 58% |
| OLD-S6 | 8% | 63% | 0% | 99% |
| OLD-NATIVE | 14% | 71% | 6% | 75% |

## 4. Copertura dei film di riferimento nell'indice

- NEW-S0: 41/41 riferimenti presenti nell'indice (100%)
- OLD-S0: 25/41 riferimenti presenti nell'indice (61%)

## 5. Risposte finali: film consigliati che violano i vincoli

| Configurazione | Risposte | Film consigliati | Violazioni | Risposte con violazione |
|---|---|---|---|---|
| NEW-S0 | 56 | 95 | 7 | 5 |
| NEW-S5 | 56 | 171 | 6 | 5 |
| NEW-S6 | 56 | 221 | 6 | 5 |
| OLD-NATIVE | 56 | 204 | 9 | 6 |
| OLD-S0 | 56 | 95 | 6 | 5 |
| OLD-S5 | 56 | 133 | 5 | 4 |
| OLD-S6 | 56 | 217 | 6 | 4 |

## 6. Confronto A/B cieco delle risposte (ordine casuale; giudice LLM)

| Confronto | Vittorie primo | Vittorie secondo | Pareggi | p (segno) |
|---|---|---|---|---|
| NEW-S0 vs OLD-S0 | 38 | 19 | 5 | 0.0163 |
| NEW-S5 vs OLD-S5 | 43 | 18 | 1 | 0.0019 |
| NEW-S6 vs OLD-S6 | 48 | 13 | 1 | 0.0 |
| NEW-S6 vs OLD-NATIVE | 51 | 10 | 1 | 0.0 |

### NEW-S0 vs OLD-S0

| Categoria | primo | secondo | pareggi |
|---|---|---|---|
| A | 6 | 3 | 1 |
| B | 2 | 6 | 2 |
| C | 6 | 1 | 1 |
| D | 3 | 3 | 0 |
| E | 4 | 2 | 0 |
| F | 5 | 2 | 1 |
| G | 7 | 1 | 0 |
| H | 5 | 1 | 0 |

Punteggi medi (1-5): NEW-S0.respects_exclusions 4.73, NEW-S0.pertinence 3.52, NEW-S0.honesty 3.61, NEW-S0.usefulness 3.24, OLD-S0.respects_exclusions 4.61, OLD-S0.pertinence 3.23, OLD-S0.honesty 3.55, OLD-S0.usefulness 3

### NEW-S5 vs OLD-S5

| Categoria | primo | secondo | pareggi |
|---|---|---|---|
| A | 7 | 3 | 0 |
| B | 8 | 2 | 0 |
| C | 4 | 4 | 0 |
| D | 6 | 0 | 0 |
| E | 4 | 2 | 0 |
| F | 6 | 2 | 0 |
| G | 4 | 4 | 0 |
| H | 4 | 1 | 1 |

Punteggi medi (1-5): NEW-S5.respects_exclusions 4.85, NEW-S5.pertinence 3.9, NEW-S5.honesty 4.02, NEW-S5.usefulness 3.79, OLD-S5.respects_exclusions 4.66, OLD-S5.pertinence 3.23, OLD-S5.honesty 3.69, OLD-S5.usefulness 2.95

### NEW-S6 vs OLD-S6

| Categoria | primo | secondo | pareggi |
|---|---|---|---|
| A | 6 | 4 | 0 |
| B | 9 | 1 | 0 |
| C | 6 | 2 | 0 |
| D | 5 | 1 | 0 |
| E | 4 | 2 | 0 |
| F | 8 | 0 | 0 |
| G | 8 | 0 | 0 |
| H | 2 | 3 | 1 |

Punteggi medi (1-5): NEW-S6.respects_exclusions 4.71, NEW-S6.pertinence 4.44, NEW-S6.honesty 4.06, NEW-S6.usefulness 4.23, OLD-S6.respects_exclusions 4.68, OLD-S6.pertinence 3.47, OLD-S6.honesty 3.66, OLD-S6.usefulness 3.34

### NEW-S6 vs OLD-NATIVE

| Categoria | primo | secondo | pareggi |
|---|---|---|---|
| A | 9 | 1 | 0 |
| B | 9 | 1 | 0 |
| C | 6 | 1 | 1 |
| D | 5 | 1 | 0 |
| E | 5 | 1 | 0 |
| F | 6 | 2 | 0 |
| G | 8 | 0 | 0 |
| H | 3 | 3 | 0 |

Punteggi medi (1-5): NEW-S6.respects_exclusions 4.71, NEW-S6.pertinence 4.42, NEW-S6.honesty 4.08, NEW-S6.usefulness 4.23, OLD-NATIVE.respects_exclusions 4.47, OLD-NATIVE.pertinence 3.44, OLD-NATIVE.honesty 3.4, OLD-NATIVE.usefulness 3.1
