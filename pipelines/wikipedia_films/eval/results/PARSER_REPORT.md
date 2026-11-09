# Verifica del parser sulle 76 domande (62 originali + 14 supplementari)

Domande senza problemi: 70/76.

| Tipo di problema | Casi |
|---|---|
| franchise non estratto | 2 |
| contraddizione rilevata dove non c'è | 1 |
| nessun segnale negativo estratto | 1 |
| contraddizione non rilevata | 1 |
| titolo da escludere non estratto | 1 |

- **1** (A) Consigliami horror psicologici come Hereditary, ma senza possessioni demoniache : contraddizione rilevata dove non c'è
- **14** (B) Cerco commedie come Una notte da leoni, ma non voglio sequel o film della stessa: franchise non estratto: Una notte da leoni
- **16** (B) Voglio film fantasy come Il Signore degli Anelli, ma non voglio altri film della: franchise non estratto: Terra di Mezzo
- **46** (F) Voglio fantasy dark, ma non fantasy medievale: nessun segnale negativo estratto
- **61** (H) Voglio un thriller lento e contemplativo, ma con tantissima azione: contraddizione non rilevata
- **109** (P) Consigliami horror con Jamie Lee Curtis, ma non della saga di Halloween: titolo da escludere non estratto: Halloween

---
## Confronto tra configurazioni del parser (76 domande, controllo automatico di `eval/parser_check.py`)

| Parser | Domande senza problemi |
|---|---|
| prompt di valutazione (`tool/RAGWikipedia/retrieval/parser.py`), gpt-5.6-luna | 71/76 |
| produzione, gpt-5.6-luna, ragionamento predefinito (3 esecuzioni; 2 prima e 2 dopo l'ultima modifica del prompt) | 73, 70, 70, 69 |
| produzione, gpt-5.6-luna, ragionamento `low` | 69 |
| produzione, gpt-5.6-luna, ragionamento `none` | 67 (filtri di genere troppo ampi, genere evitato = voluto) |
| produzione, gpt-5.4-mini | 65 |
| produzione, gpt-5.4 (`PARSER_REPORT_gpt-5.4.md`) | 70 (più lento) |

Scelta: gpt-5.6-luna con il ragionamento predefinito (~3,5–4 s): `none` e i modelli piccoli peggiorano in modo misurabile.
La variazione tra esecuzioni uguali (69–73) è il rumore dell'LLM. Problemi ricorrenti: (1) nomi di franchise in forma diversa da quella della batteria (casi 14, 16, 17, 109: artefatti del controllo, la
risoluzione per id e per nome li copre nel recupero); (2) rilevamento della contraddizione instabile nei casi H (61, 62) e un falso positivo occasionale (caso 1): il prompt è stato
stretto («contraddittoria SOLO se nessun film può soddisfare entrambe le richieste»); (3) filtri di genere troppo ampi («azione» 13% del catalogo) o uguali al genere voluto («distopico»):
**non arrivano mai alla ricerca**, perché `film_index/search.py:build_context` scarta un genere evitato che è anche voluto, che etichetta più dell'8% del catalogo o oltre il terzo.
