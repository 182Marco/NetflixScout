# Confronto A/B live: vecchio RAG (`netflix_scout`) contro nuovo RAG (`wikipedia_films_it_v3`) — 2026-11-04

Dati grezzi, tabelle complete e analisi: `eval/results/` (`REPORT.md`, `ANALYSIS.md`, `H_REPORT.md`, `LEXICAL_REPORT.md`, `extra_REPORT.md`, `wide_REPORT.md`, `*.jsonl`).
Codice: `retrieval/` (retriever), `eval/` (batteria, harness, report). Batteria originale intatta in `eval/battery.json` (62 domande, A–H); batteria supplementare `eval/battery_extra.json` (14 domande P, filtri su persone/anno/paese: lacuna della batteria originale).

## Come è stato fatto
- **Stesse condizioni**: stesso modello (`gpt-5.6-luna`) per parser, rerank, risposte e giudice; stesso parser delle richieste (una sola analisi per domanda, in italiano e in inglese) per entrambi i corpus; stesso prompt di risposta; 5 film per lista; embedding del corpus (small per il vecchio, large 1536 per il nuovo). Il vecchio è stato eseguito anche **come gira nell'applicazione** (`OLD-NATIVE`: suo parser, Cohere/LLM rerank), senza il flusso dei riferimenti TMDb perché scrive nella collezione.
- **Strategie** (le stesse su entrambi i corpus dove tecnicamente possibile): S0 semantico; S1 + id dei film citati esclusi; S2n + franchise per nome (entrambi); S2f + franchise per id (solo nuovo: il vecchio non ha il campo); S3 penalità sul pool (λ=0,5, pool 300); S3b sottrazione di vettori (α=0,5); S4 filtri di genere/formato; S5 combinazione; S6 = S5 + riordino LLM del top 25.
- **Giudice cieco per film** (1.717 film unici giudicati una volta per domanda, senza sapere da quale sistema vengono): viola / pertinente / genere. **Controllo deterministico** (titoli e franchise della batteria) in aggiunta: una violazione è contata se lo dice il giudice O il controllo. **Giudice cieco A/B delle risposte** con ordine casuale, ripetuto in due passaggi con ordini diversi (accordo 82%).
- Criterio centrale applicato: un horror soprannaturale è violazione anche senza legame con Hereditary.
- Costo/consumi della sessione: ~2.700 chiamate LLM, ~190 chiamate di embedding (7.000 token). Nessuna scrittura su Qdrant dalla valutazione.

## Chi vince
**Il nuovo RAG vince**, sia come dataset sia come algoritmo, con due precisazioni oneste (sotto). Domande A–G (56 liste da 5 film = 280 film per sistema; le 6 domande H a parte):

| Sistema | Violazioni | Validi (pertinenti, senza violazioni) | Genere ok |
|---|---|---|---|
| OLD-S0 (nessuna esclusione) | 37% | 29% | 83% |
| NEW-S0 (nessuna esclusione) | 47% | 35% | 91% |
| **OLD-NATIVE** (come gira ora) | **10%** | **66%** | 94% |
| OLD-S6 (algoritmo completo) | 4% | 70% | 89% |
| NEW-S5 (senza LLM) | 10% | 58% | 83% |
| **NEW-S6 (algoritmo completo)** | **4%** | **80%** | 90% |
| NEW-S6, pool 50 (`S6w`) | 4% | 81% | 91% |

Risposte finali (giudice cieco, due passaggi, 124 giudizi per confronto; vittorie nuovo / vecchio / pari): NEW-S0 vs OLD-S0 75/41/8; NEW-S5 vs OLD-S5 89/31/4; NEW-S6 vs OLD-S6 93/29/2; **NEW-S6 vs OLD-NATIVE 96/27/1** (primo passaggio 51/10/1, p<0,001). Film consigliati che violano un vincolo: NEW-S6 6 su 221, OLD-NATIVE 9 su 204.

**Dataset contro algoritmo.** A parità di algoritmo il nuovo corpus dà +6 punti di film validi senza esclusioni (S0), +12 con S2n/S3, +20 con S5, +9 con S6. L'**algoritmo conta più del dataset**: S0→S6 porta +41 punti al vecchio e +44 al nuovo; il vecchio algoritmo completo (OLD-S6, 70%) è vicino alla pipeline attuale (66%). Il nuovo dataset aggiunge: riferimenti presenti nell'indice 41/41 contro 25/41 (61%); filtri su regista, attore, anno e paese; franchise per id; lessicale preciso; trame in italiano. Registro il limite di copertura separatamente: i 16 riferimenti assenti dal vecchio non sono stati penalizzati artificialmente (si usa la descrizione del film come vettore, uguale per entrambi).

**Per categoria** (film validi NEW-S6 / OLD-NATIVE): A 66/58, B 96/74, C 72/75, D 67/77, E 97/77, F 82/80, G 78/28, H 37/47. Il vecchio fa **meglio nel recupero** in D (positivi e negativi con più riferimenti) e leggermente in C e H; con il riordino su pool 50 il nuovo sale a D 73, C 75. Nelle risposte il nuovo vince comunque in tutte le categorie tranne H (3–3).

## Quale strategia gestisce meglio le preferenze negative
Violazioni (A–G): esclusioni in linguaggio naturale (tratti, A/C/D/F) / esclusioni per titolo e franchise (B/E):

| Strategia (NEW) | Tratti NL | Titoli/franchise | Validi totali |
|---|---|---|---|
| S0 nessuna | 44% | 76% | 35% |
| S1 solo id citati | 36% | 68% | 39% |
| S2n franchise per nome | 36% | 18% | 50% |
| S2f franchise per id | 36% | 9% | 51% |
| S3 penalità sul pool | 28% | 75% | 40% |
| S3b sottrazione vettori | 28% | 75% | 40% |
| S4 filtri genere/formato | 44% | 76% | 35% |
| S5 combinata | 16% | 5% | 58% |
| **S6 combinata + riordino LLM** | **6%** | **0%** | **80%** |

- **Titoli e franchise**: l'esclusione per id non basta (68% di violazioni: restano sequel e remake); il franchise per **id** batte il franchise per nome (9% contro 18%) e non esiste nel vecchio indice.
- **Tratti in linguaggio naturale**: la penalità sul pool (28%) è meglio dei soli id (36%) e della sottrazione di vettori, che non dà vantaggio sulla penalità (28% contro 28%): la sottrazione non si adotta. I **filtri di genere (S4) non servono** a questo scopo: i tratti da escludere («soprannaturale», «splatter») quasi mai sono etichette del catalogo, quindi S4 ≈ S0 (1 sola lista cambiata).
- **Il vero guadagno viene dal riordino LLM che conosce i film** (S5→S6: tratti 16%→6%), ma costa ~10 s per domanda (le altre ~0,35 s). La combinazione senza LLM (S5) dimezza le violazioni di S0 (47%→10%) ed è la variante veloce.
- **Perdita di risultati validi**: S3 e S5 tolgono 18 e 21 film validi su 99 di S0 (sostituiti da altri); nel vecchio 26/82. Nessuna strategia annulla la pertinenza (validi crescono sempre).

## Filtri su persone, anno, paese (batteria supplementare, 14 domande)
NEW-S5f 82% validi (3% violazioni, 0,11 s), NEW-S6f 95% validi (0%); OLD-NATIVE 11% validi (86% violazioni); OLD-S6f 73%/25%. Risposte: NEW-S6f contro OLD-NATIVE 14–0–0. Il vecchio non ha il regista nel payload e finisce al 2012 (due domande sono fuori copertura per lui).

## Componente lessicale (40 domande con parola rara)
Solo denso hit@5 0,47; **filtro full-text di Qdrant + ordine denso 1,00 (hit@1 0,95)**; candidati BM25 ordinati dal denso 0,68; BM25 da solo 0,78. Il lessicale entra come filtro nella stessa query: nessun secondo ranking, `hybrid.py` non serve (si rimuove in Fase F). Limite: il test dà il termine esatto.

## Contraddizioni (categoria H, 6 domande)
Tutte le configurazioni dichiarano la contraddizione (nuovo 5–6/6, vecchio 5–6/6), nessuna inventa una soluzione e nessuna chiede chiarimento; serve solo la parte coerente: 3–4/6 (nuovo), 3–6/6 (vecchio). È un risultato del prompt di risposta, non del retriever.

## Routing (`run_routing_eval --live`)
Eseguito sull'applicazione **attuale** (vecchio RAG; il nuovo non è integrato): **67/72**, 144 chiamate. I 5 fallimenti non riguardano il RAG: 4 casi `wikidata_search` bocciati dalla validazione degli argomenti («type not given in the conversation», «title 'La cosa' does not contain 'thing') e 1 caso TMDb+YouTube. È la baseline per dopo l'integrazione. Il routing con le nuove istruzioni non è eseguibile prima dell'integrazione.

## Problemi da risolvere prima dell'integrazione
1. **Latenza**: S6 ~10 s (una chiamata LLM); decidere S6 (qualità) o S5f (0,1–0,4 s) o un modello più piccolo per il riordino; il vecchio nativo è già a ~12 s.
2. **Categoria D e H**: il vecchio recupera un po' meglio con più riferimenti positivi e negativi; provare pool più grande (50: D 67→73) e il riordino con il testo completo della trama.
3. **Parser**: un solo passo per tutto (positivo, negativi, franchise, filtri, termini rari); non misurato sui casi in cui sbaglia (es. franchise non riconosciuto, genere negativo uguale al desiderato); il filtro dei paesi dipende dal nome italiano esatto (es. «Italia»).
4. **Copertura**: `franchise_id` su 4.049 film (10%): fuori dai franchise noti resta solo la penalità; `genres` è testo libero; catalogo scarso dopo il 2019.
5. **Bias della valutazione**: stesso modello per parser, rerank e giudice; evidenza in italiano per il nuovo e in inglese per il vecchio nel confronto sulle risposte; un campione di 62+14 domande, una sola esecuzione del recupero. Le metriche per film con controllo deterministico sono il riferimento principale.
6. **Non ancora provati**: serie e film (`content_type`), conflitti con le impostazioni, routing con le nuove istruzioni, arricchimento TMDb per `imdb_id`, comportamento nell'orchestratore e nel web: sono lavoro di integrazione (Fasi C–D del piano).
7. `AGENTS.md`, `preferences/` e i test «intento vince» codificano ancora la precedenza opposta.
