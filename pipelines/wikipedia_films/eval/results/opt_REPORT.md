# Confronto A/B live: vecchio RAG (`netflix_scout`) contro nuovo RAG (`wikipedia_films_it_v3`)

Metriche calcolate sulle liste di 5 film. *Violazione* = il film mostra un tratto da evitare, è un titolo/franchise escluso (giudice cieco O controllo deterministico della batteria). *Pertinente* = ha il genere e le caratteristiche volute. *Valido* = pertinente e senza violazioni. Le domande H (contraddittorie) sono escluse dalle percentuali e valutate nella parte sulle risposte.

## 1. Strategie di recupero (stesso algoritmo su entrambi i corpus dove possibile)

| Sistema | Violazioni | di cui titolo/franchise | di cui tratti | Pertinenti | Validi | Genere ok | Liste con violazione | Validi di S0 persi | s |
|---|---|---|---|---|---|---|---|---|---|
| NEW-S5 | 13% | 3 | 33 | 63% | 54% | 79% | 22/56 | 0/0 | 0.76 |
| NEW-S6 | 5% | 0 | 13 | 84% | 81% | 90% | 9/56 | 0/0 | 0.55 |
| NEW-C1 | 18% | 1 | 43 | 74% | 60% | 89% | 19/48 | 0/0 | 2.32 |
| NEW-V1 | 6% | 0 | 18 | 83% | 79% | 90% | 16/56 | 0/0 | 0.39 |
| NEW-V10 | 6% | 0 | 16 | 82% | 78% | 91% | 13/56 | 0/0 | 0.79 |
| NEW-V2 | 8% | 1 | 21 | 81% | 75% | 89% | 17/56 | 0/0 | 0.39 |
| NEW-V3 | 7% | 0 | 20 | 81% | 75% | 89% | 18/56 | 0/0 | 0.4 |
| NEW-V4 | 10% | 0 | 29 | 79% | 70% | 91% | 17/56 | 0/0 | 0.4 |
| NEW-V5 | 8% | 1 | 22 | 78% | 72% | 89% | 16/56 | 0/0 | 0.43 |
| NEW-V6 | 8% | 0 | 21 | 78% | 71% | 87% | 12/56 | 0/0 | 0.53 |
| NEW-V7 | 6% | 0 | 16 | 88% | 83% | 92% | 14/56 | 0/0 | 0.59 |
| NEW-V8 | 4% | 0 | 11 | 85% | 82% | 91% | 10/56 | 0/0 | 0.64 |
| NEW-V9 | 4% | 0 | 12 | 89% | 85% | 92% | 9/56 | 0/0 | 0.73 |
| NEW-W1 | 10% | 1 | 26 | 88% | 80% | 92% | 19/56 | 0/0 | 0.87 |
| NEW-W2 | 8% | 1 | 22 | 89% | 81% | 94% | 17/56 | 0/0 | 0.9 |
| NEW-W3 | 8% | 1 | 22 | 81% | 75% | 89% | 18/56 | 0/0 | 0.92 |
| NEW-W4 | 8% | 1 | 21 | 88% | 81% | 92% | 14/56 | 0/0 | 0.94 |
| NEW-W5 | 6% | 0 | 17 | 89% | 84% | 92% | 14/56 | 0/0 | 0.95 |
| NEW-W6 | 8% | 0 | 21 | 82% | 76% | 91% | 14/56 | 0/0 | 0.94 |
| NEW-X1 | 5% | 0 | 14 | 91% | 86% | 94% | 11/56 | 0/0 | 3.68 |
| NEW-X2 | 5% | 0 | 15 | 86% | 81% | 92% | 13/56 | 0/0 | 3.33 |
| NEW-X3 | 6% | 0 | 18 | 87% | 81% | 92% | 14/56 | 0/0 | 3.86 |
| NEW-X4 | 4% | 0 | 11 | 89% | 85% | 93% | 11/56 | 0/0 | 3.52 |

## 2. Per categoria (violazioni / validi)

| Sistema | A | B | C | D | E | F | G | H |
|---|---|---|---|---|---|---|---|---|
| NEW-S5 | 24% / 46% | 8% / 64% | 20% / 55% | 23% / 47% | 3% / 70% | 10% / 55% | 0% / 40% | 27% / 37% |
| NEW-S6 | 12% / 62% | 0% / 94% | 8% / 85% | 10% / 63% | 0% / 97% | 2% / 80% | 0% / 85% | 17% / 73% |
| NEW-C1 | 36% / 44% | 2% / 78% | 23% / 73% | 40% / 40% | 0% / 85% | 17% / 63% | 0% / 49% | 44% / 32% |
| NEW-V1 | 14% / 58% | 0% / 94% | 15% / 75% | 10% / 63% | 0% / 97% | 5% / 78% | 0% / 88% | 10% / 70% |
| NEW-V10 | 14% / 62% | 0% / 94% | 12% / 80% | 13% / 60% | 0% / 93% | 0% / 75% | 0% / 80% | 17% / 57% |
| NEW-V2 | 16% / 62% | 2% / 86% | 18% / 70% | 13% / 60% | 0% / 97% | 5% / 70% | 0% / 82% | 17% / 60% |
| NEW-V3 | 20% / 60% | 0% / 88% | 10% / 80% | 13% / 53% | 0% / 97% | 5% / 62% | 0% / 82% | 10% / 47% |
| NEW-V4 | 16% / 66% | 0% / 88% | 28% / 70% | 20% / 47% | 0% / 83% | 10% / 62% | 0% / 68% | 37% / 33% |
| NEW-V5 | 18% / 62% | 2% / 82% | 18% / 72% | 17% / 53% | 0% / 90% | 2% / 72% | 0% / 70% | 23% / 47% |
| NEW-V6 | 18% / 56% | 0% / 94% | 15% / 68% | 13% / 53% | 0% / 83% | 5% / 65% | 0% / 75% | 13% / 70% |
| NEW-V7 | 14% / 72% | 0% / 96% | 10% / 80% | 10% / 70% | 0% / 100% | 5% / 78% | 0% / 88% | 7% / 73% |
| NEW-V8 | 12% / 68% | 0% / 94% | 5% / 82% | 10% / 63% | 0% / 93% | 0% / 85% | 0% / 88% | 17% / 67% |
| NEW-V9 | 8% / 84% | 0% / 94% | 12% / 78% | 10% / 67% | 0% / 100% | 0% / 82% | 0% / 90% | 3% / 77% |
| NEW-W1 | 16% / 68% | 2% / 94% | 15% / 80% | 27% / 60% | 0% / 100% | 10% / 75% | 0% / 82% | 27% / 53% |
| NEW-W2 | 16% / 74% | 2% / 90% | 12% / 85% | 23% / 57% | 0% / 100% | 5% / 82% | 0% / 80% | 47% / 47% |
| NEW-W3 | 14% / 64% | 2% / 92% | 15% / 70% | 20% / 63% | 0% / 80% | 8% / 72% | 0% / 78% | 50% / 37% |
| NEW-W4 | 14% / 70% | 2% / 90% | 12% / 88% | 20% / 60% | 0% / 97% | 8% / 75% | 0% / 85% | 43% / 50% |
| NEW-W5 | 10% / 76% | 0% / 96% | 15% / 82% | 10% / 67% | 0% / 97% | 8% / 72% | 0% / 92% | 43% / 50% |
| NEW-W6 | 18% / 68% | 0% / 84% | 10% / 80% | 10% / 53% | 0% / 93% | 12% / 68% | 0% / 85% | 27% / 43% |
| NEW-X1 | 10% / 76% | 0% / 98% | 10% / 82% | 10% / 67% | 0% / 100% | 5% / 80% | 0% / 95% | 30% / 57% |
| NEW-X2 | 8% / 78% | 0% / 92% | 8% / 80% | 17% / 60% | 0% / 93% | 8% / 75% | 0% / 88% | 30% / 50% |
| NEW-X3 | 8% / 72% | 0% / 98% | 10% / 85% | 17% / 67% | 0% / 93% | 12% / 65% | 0% / 88% | 37% / 50% |
| NEW-X4 | 8% / 74% | 0% / 96% | 2% / 90% | 10% / 70% | 0% / 90% | 8% / 80% | 0% / 92% | 40% / 50% |

Categorie: **A** genere da mantenere, elemento specifico da escludere; **B** stesso genere, diverso dal riferimento (titoli e franchise); **C** preferenze negative multiple; **D** positive e negative con più riferimenti; **E** le esclusioni non distruggono la pertinenza; **F** genere mantenuto, sottogeneri evitati; **G** ricerca semantica e lessicale; **H** robustezza e richieste contraddittorie

## 3. Esclusioni espresse in linguaggio naturale (A, C, D, F) e come titoli/franchise (B, E)

| Sistema | Violazioni NL | Validi NL | Violazioni titoli | Validi titoli |
|---|---|---|---|---|
| NEW-S5 | 19% | 51% | 6% | 66% |
| NEW-S6 | 8% | 72% | 0% | 95% |
| NEW-C1 | 30% | 54% | 2% | 80% |
| NEW-V1 | 11% | 68% | 0% | 95% |
| NEW-V10 | 10% | 69% | 0% | 94% |
| NEW-V2 | 13% | 66% | 1% | 90% |
| NEW-V3 | 12% | 64% | 0% | 91% |
| NEW-V4 | 18% | 62% | 0% | 86% |
| NEW-V5 | 14% | 66% | 1% | 85% |
| NEW-V6 | 13% | 61% | 0% | 90% |
| NEW-V7 | 10% | 75% | 0% | 98% |
| NEW-V8 | 7% | 75% | 0% | 94% |
| NEW-V9 | 8% | 79% | 0% | 96% |
| NEW-W1 | 16% | 71% | 1% | 96% |
| NEW-W2 | 14% | 76% | 1% | 94% |
| NEW-W3 | 14% | 68% | 1% | 88% |
| NEW-W4 | 13% | 74% | 1% | 92% |
| NEW-W5 | 11% | 75% | 0% | 96% |
| NEW-W6 | 13% | 68% | 0% | 88% |
| NEW-X1 | 9% | 77% | 0% | 99% |
| NEW-X2 | 9% | 74% | 0% | 92% |
| NEW-X3 | 11% | 72% | 0% | 96% |
| NEW-X4 | 7% | 79% | 0% | 94% |

## 4. Copertura dei film di riferimento nell'indice


## 5. Risposte finali: film consigliati che violano i vincoli

| Configurazione | Risposte | Film consigliati | Violazioni | Risposte con violazione |
|---|---|---|---|---|

## 6. Confronto A/B cieco delle risposte (ordine casuale; giudice LLM)

| Confronto | Vittorie primo | Vittorie secondo | Pareggi | p (segno) |
|---|---|---|---|---|
