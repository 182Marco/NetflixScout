# Confronto A/B live: vecchio RAG (`netflix_scout`) contro nuovo RAG (`wikipedia_films_it_v3`)

Metriche calcolate sulle liste di 5 film. *Violazione* = il film mostra un tratto da evitare, è un titolo/franchise escluso (giudice cieco O controllo deterministico della batteria). *Pertinente* = ha il genere e le caratteristiche volute. *Valido* = pertinente e senza violazioni. Le domande H (contraddittorie) sono escluse dalle percentuali e valutate nella parte sulle risposte.

## 1. Strategie di recupero (stesso algoritmo su entrambi i corpus dove possibile)

| Sistema | Violazioni | di cui titolo/franchise | di cui tratti | Pertinenti | Validi | Genere ok | Liste con violazione | Validi di S0 persi | s |
|---|---|---|---|---|---|---|---|---|---|
| NEW-S6 | 4% | 0 | 10 | 85% | 82% | 91% | 6/56 | 0/0 | 0.37 |
| NEW-X4 | 4% | 0 | 10 | 88% | 85% | 94% | 10/56 | 0/0 | 0.36 |
| NEW-X5 | 2% | 0 | 7 | 87% | 85% | 92% | 7/56 | 0/0 | 3.02 |
| NEW-X6 | 4% | 0 | 12 | 89% | 85% | 93% | 11/56 | 0/0 | 3.73 |
| NEW-X7 | 4% | 0 | 10 | 88% | 84% | 93% | 10/56 | 0/0 | 2.18 |
| NEW-X8 | 6% | 0 | 16 | 88% | 83% | 94% | 13/56 | 0/0 | 2.92 |

## 2. Per categoria (violazioni / validi)

| Sistema | A | B | C | D | E | F | G | H |
|---|---|---|---|---|---|---|---|---|
| NEW-S6 | 14% / 62% | 0% / 94% | 5% / 88% | 3% / 70% | 0% / 97% | 0% / 88% | 0% / 78% | 17% / 60% |
| NEW-X4 | 10% / 72% | 0% / 96% | 2% / 90% | 3% / 80% | 0% / 90% | 8% / 80% | 0% / 85% | 37% / 43% |
| NEW-X5 | 4% / 76% | 0% / 98% | 5% / 85% | 3% / 77% | 0% / 90% | 5% / 80% | 0% / 85% | 30% / 50% |
| NEW-X6 | 10% / 76% | 0% / 96% | 8% / 82% | 3% / 80% | 0% / 90% | 8% / 82% | 0% / 88% | 30% / 47% |
| NEW-X7 | 10% / 72% | 0% / 96% | 2% / 90% | 7% / 77% | 0% / 90% | 5% / 82% | 0% / 82% | 37% / 43% |
| NEW-X8 | 20% / 64% | 0% / 98% | 2% / 88% | 7% / 73% | 0% / 93% | 8% / 80% | 0% / 85% | 33% / 43% |

Categorie: **A** genere da mantenere, elemento specifico da escludere; **B** stesso genere, diverso dal riferimento (titoli e franchise); **C** preferenze negative multiple; **D** positive e negative con più riferimenti; **E** le esclusioni non distruggono la pertinenza; **F** genere mantenuto, sottogeneri evitati; **G** ricerca semantica e lessicale; **H** robustezza e richieste contraddittorie

## 3. Esclusioni espresse in linguaggio naturale (A, C, D, F) e come titoli/franchise (B, E)

| Sistema | Violazioni NL | Validi NL | Violazioni titoli | Validi titoli |
|---|---|---|---|---|
| NEW-S6 | 6% | 76% | 0% | 95% |
| NEW-X4 | 6% | 80% | 0% | 94% |
| NEW-X5 | 4% | 79% | 0% | 95% |
| NEW-X6 | 8% | 80% | 0% | 94% |
| NEW-X7 | 6% | 80% | 0% | 94% |
| NEW-X8 | 10% | 76% | 0% | 96% |

## 4. Copertura dei film di riferimento nell'indice


## 5. Risposte finali: film consigliati che violano i vincoli

| Configurazione | Risposte | Film consigliati | Violazioni | Risposte con violazione |
|---|---|---|---|---|

## 6. Confronto A/B cieco delle risposte (ordine casuale; giudice LLM)

| Confronto | Vittorie primo | Vittorie secondo | Pareggi | p (segno) |
|---|---|---|---|---|
