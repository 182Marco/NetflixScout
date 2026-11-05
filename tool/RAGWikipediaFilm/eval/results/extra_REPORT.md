# Confronto A/B live: vecchio RAG (`netflix_scout`) contro nuovo RAG (`wikipedia_films_it_v3`)

Metriche calcolate sulle liste di 5 film. *Violazione* = il film mostra un tratto da evitare, è un titolo/franchise escluso (giudice cieco O controllo deterministico della batteria). *Pertinente* = ha il genere e le caratteristiche volute. *Valido* = pertinente e senza violazioni. Le domande H (contraddittorie) sono escluse dalle percentuali e valutate nella parte sulle risposte.

## 1. Strategie di recupero (stesso algoritmo su entrambi i corpus dove possibile)

| Sistema | Violazioni | di cui titolo/franchise | di cui tratti | Pertinenti | Validi | Genere ok | Liste con violazione | Validi di S0 persi | s |
|---|---|---|---|---|---|---|---|---|---|
| NEW-S0 | 77% | 1 | 53 | 20% | 20% | 80% | 14/14 | 0/14 | 0.52 |
| OLD-S0 | 90% | 3 | 60 | 7% | 7% | 79% | 14/14 | 0/5 | 0.39 |
| OLD-NATIVE | 86% | 2 | 58 | 11% | 11% | 100% | 14/14 | 5/5 | 22.07 |
| NEW-S5f | 3% | 0 | 2 | 82% | 82% | 86% | 2/14 | 2/14 | 0.11 |
| NEW-S6f | 0% | 0 | 0 | 95% | 95% | 97% | 0/14 | 4/14 | 7.77 |
| OLD-S5f | 47% | 0 | 26 | 40% | 40% | 82% | 8/14 | 0/5 | 0.29 |
| OLD-S6f | 25% | 0 | 14 | 73% | 73% | 96% | 3/14 | 3/5 | 7.24 |

## 2. Per categoria (violazioni / validi)

| Sistema | P |
|---|---|
| NEW-S0 | 77% / 20% |
| OLD-S0 | 90% / 7% |
| OLD-NATIVE | 86% / 11% |
| NEW-S5f | 3% / 82% |
| NEW-S6f | 0% / 95% |
| OLD-S5f | 47% / 40% |
| OLD-S6f | 25% / 73% |

Categorie: **P** filtri su persone, anno e paese (batteria supplementare, lacuna della batteria originale)

## 3. Esclusioni espresse in linguaggio naturale (A, C, D, F) e come titoli/franchise (B, E)

| Sistema | Violazioni NL | Validi NL | Violazioni titoli | Validi titoli |
|---|---|---|---|---|
| NEW-S0 | - | - | - | - |
| OLD-S0 | - | - | - | - |
| OLD-NATIVE | - | - | - | - |
| NEW-S5f | - | - | - | - |
| NEW-S6f | - | - | - | - |
| OLD-S5f | - | - | - | - |
| OLD-S6f | - | - | - | - |

## 4. Copertura dei film di riferimento nell'indice

- NEW-S0: 1/1 riferimenti presenti nell'indice (100%)
- OLD-S0: 1/1 riferimenti presenti nell'indice (100%)

## 5. Risposte finali: film consigliati che violano i vincoli

| Configurazione | Risposte | Film consigliati | Violazioni | Risposte con violazione |
|---|---|---|---|---|
| NEW-S0 | 14 | 14 | 1 | 1 |
| NEW-S5f | 14 | 55 | 1 | 1 |
| NEW-S6f | 14 | 60 | 0 | 0 |
| OLD-NATIVE | 14 | 8 | 1 | 1 |
| OLD-S0 | 14 | 3 | 0 | 0 |
| OLD-S5f | 11 | 19 | 0 | 0 |
| OLD-S6f | 11 | 37 | 0 | 0 |

## 6. Confronto A/B cieco delle risposte (ordine casuale; giudice LLM)

| Confronto | Vittorie primo | Vittorie secondo | Pareggi | p (segno) |
|---|---|---|---|---|
| NEW-S0 vs OLD-S0 | 10 | 2 | 2 | 0.0386 |
| NEW-S5f vs OLD-S5f | 10 | 1 | 0 | 0.0117 |
| NEW-S6f vs OLD-S6f | 4 | 4 | 3 | 1.0 |
| NEW-S6f vs OLD-NATIVE | 14 | 0 | 0 | 0.0001 |

### NEW-S0 vs OLD-S0

| Categoria | primo | secondo | pareggi |
|---|---|---|---|
| P | 10 | 2 | 2 |

Punteggi medi (1-5): NEW-S0.respects_exclusions 4.93, NEW-S0.pertinence 2.93, NEW-S0.honesty 3.79, NEW-S0.usefulness 3.14, OLD-S0.respects_exclusions 5, OLD-S0.pertinence 1.29, OLD-S0.honesty 2.93, OLD-S0.usefulness 1.36

### NEW-S5f vs OLD-S5f

| Categoria | primo | secondo | pareggi |
|---|---|---|---|
| P | 10 | 1 | 0 |

Punteggi medi (1-5): NEW-S5f.respects_exclusions 4.82, NEW-S5f.pertinence 4.91, NEW-S5f.honesty 4.36, NEW-S5f.usefulness 4.91, OLD-S5f.respects_exclusions 5, OLD-S5f.pertinence 3.45, OLD-S5f.honesty 3.82, OLD-S5f.usefulness 2.82

### NEW-S6f vs OLD-S6f

| Categoria | primo | secondo | pareggi |
|---|---|---|---|
| P | 4 | 4 | 3 |

Punteggi medi (1-5): NEW-S6f.respects_exclusions 5, NEW-S6f.pertinence 4.73, NEW-S6f.honesty 4.27, NEW-S6f.usefulness 4.55, OLD-S6f.respects_exclusions 5, OLD-S6f.pertinence 4.09, OLD-S6f.honesty 4.18, OLD-S6f.usefulness 3.73

### NEW-S6f vs OLD-NATIVE

| Categoria | primo | secondo | pareggi |
|---|---|---|---|
| P | 14 | 0 | 0 |

Punteggi medi (1-5): NEW-S6f.respects_exclusions 5, NEW-S6f.pertinence 4.93, NEW-S6f.honesty 4.5, NEW-S6f.usefulness 5, OLD-NATIVE.respects_exclusions 4.57, OLD-NATIVE.pertinence 1.5, OLD-NATIVE.honesty 2.29, OLD-NATIVE.usefulness 1.36
