# Confronto A/B live: vecchio RAG (`netflix_scout`) contro nuovo RAG (`wikipedia_films_it_v3`)

Metriche calcolate sulle liste di 5 film. *Violazione* = il film mostra un tratto da evitare, è un titolo/franchise escluso (giudice cieco O controllo deterministico della batteria). *Pertinente* = ha il genere e le caratteristiche volute. *Valido* = pertinente e senza violazioni. Le domande H (contraddittorie) sono escluse dalle percentuali e valutate nella parte sulle risposte.

## 1. Strategie di recupero (stesso algoritmo su entrambi i corpus dove possibile)

| Sistema | Violazioni | di cui titolo/franchise | di cui tratti | Pertinenti | Validi | Genere ok | Liste con violazione | Validi di S0 persi | s |
|---|---|---|---|---|---|---|---|---|---|
| NEW-S6w | 4% | 0 | 11 | 85% | 81% | 91% | 8/56 | 0/0 | 13.52 |
| OLD-S6w | 7% | 1 | 18 | 76% | 72% | 89% | 12/56 | 0/0 | 11.79 |

## 2. Per categoria (violazioni / validi)

| Sistema | A | B | C | D | E | F | G | H |
|---|---|---|---|---|---|---|---|---|
| NEW-S6w | 4% / 76% | 0% / 94% | 5% / 75% | 10% / 73% | 0% / 97% | 10% / 75% | 0% / 80% | 17% / 63% |
| OLD-S6w | 12% / 60% | 0% / 98% | 20% / 62% | 3% / 67% | 0% / 93% | 10% / 72% | 0% / 55% | 10% / 67% |

Categorie: **A** genere da mantenere, elemento specifico da escludere; **B** stesso genere, diverso dal riferimento (titoli e franchise); **C** preferenze negative multiple; **D** positive e negative con più riferimenti; **E** le esclusioni non distruggono la pertinenza; **F** genere mantenuto, sottogeneri evitati; **G** ricerca semantica e lessicale; **H** robustezza e richieste contraddittorie

## 3. Esclusioni espresse in linguaggio naturale (A, C, D, F) e come titoli/franchise (B, E)

| Sistema | Violazioni NL | Validi NL | Violazioni titoli | Validi titoli |
|---|---|---|---|---|
| NEW-S6w | 7% | 75% | 0% | 95% |
| OLD-S6w | 12% | 65% | 0% | 96% |

## 4. Copertura dei film di riferimento nell'indice


## 5. Risposte finali: film consigliati che violano i vincoli

| Configurazione | Risposte | Film consigliati | Violazioni | Risposte con violazione |
|---|---|---|---|---|

## 6. Confronto A/B cieco delle risposte (ordine casuale; giudice LLM)

| Confronto | Vittorie primo | Vittorie secondo | Pareggi | p (segno) |
|---|---|---|---|---|
