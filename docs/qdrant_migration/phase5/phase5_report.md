# Fase 5 - ricerca con riferimenti positivi e negativi (2026-10-26)

Protocollo, criteri e soglie: `../protocol.md` (scritti **prima** della misura). Casi congelati: `cases.json` (hash in `cases.sha256`).
Dati: 28 casi, indice reale di 42.522 punti, server Qdrant 1.20.0 su 127.0.0.1, ricerca **esatta** per tutte le varianti. Nessuna chiamata a pagamento.
Risultati grezzi: `ab_results.json`; riepilogo e tabella per caso: `ab_summary.md`.

## Esito (applicando i criteri senza modificarli)

**Nessuna variante migliora abbastanza la baseline.** B (`average_vector`) e C (`best_score`) non soddisfano tutti i criteri.

| Criterio | B average_vector | C best_score |
|---|---|---|
| 1 negativi: calo medio >= 0,02 e in >= 60% dei casi (21 casi) | **OK**: -0,059; calo in 86% | **NO**: +0,044 (la similarita' ai negativi *sale*); calo in 19% |
| 2 pertinenza al testo: calo medio <= 0,02 (23 casi) | **NO**: -0,047 (8 casi con perdita > 0,05) | **NO**: -0,096 (16 casi con perdita > 0,05) |
| 3 positivi: calo medio <= 0,02; nessun riferimento con perdita > 0,05 | OK: +0,065; 0 eccezioni | OK: +0,141; 0 eccezioni |
| 4 vincoli: violazioni <= A | **NO**: 19 contro 16 | **NO**: 20 contro 16 |
| 5 riferimenti nei risultati = 0 | OK (0; anche senza le esclusioni del parser) | OK (0; idem) |
| 6 controlli senza riferimenti validi = A | OK: 5/5 | OK: 5/5 |

## Cosa e' misurato (automatico)
- **B** fa quello per cui e' pensata: allontana dai negativi (-0,059) e avvicina ai positivi (+0,065), ma sposta anche la lista (sovrapposizione media con A: 0,36) e riduce la pertinenza al testo.
- **C** avvicina molto ai positivi (+0,141) ma **non allontana dai negativi** (in 17 casi su 21 la similarita' ai negativi aumenta): con `best_score` un candidato vicino a *qualunque* positivo (il vettore del testo e' un positivo) non viene penalizzato dal negativo. Sovrapposizione media con A: 0,23.
- **Riferimenti nei risultati:** senza le esclusioni del parser, A restituisce i film di riferimento in 10 occasioni (es. Alien, Gravity, 2001 negli elenchi di c02/c03/c13/c14/c15); B e C mai (esclusione nativa per `movie_id` + guardia finale). Con le esclusioni del parser, 0 per tutte.
- **Controlli:** i 5 casi senza riferimenti validi (ambiguo-ambiguo, assenti, nessun riferimento, riferimento inesistente) danno risultati identici ad A per entrambe le varianti.
- **Risoluzione:** nessuna discrepanza rispetto agli stati attesi congelati (resolved / ambiguous / not_in_index). Omonimi (Scarface, Breathless) esclusi per titolo e tracciati.
- **Latenza** (mediana, ricerca esatta, compresa la pipeline): A 28 ms, B 34 ms, C 39 ms. Non e' un criterio.
- **Coerenza HNSW:** con `hnsw_ef` = 128 le liste di B e C coincidono con quelle esatte in tutti i casi (sovrapposizione minima 1,0).

## Limiti e anomalie (da dire, non da usare per riscrivere il verdetto)
1. **Il criterio 2 misura una quantita' che A massimizza per costruzione**: la ricerca normale restituisce i vicini piu' prossimi al vettore del testo, quindi *qualunque* spostamento verso dei riferimenti la riduce. Con una soglia di 0,02 e un effetto sui negativi richiesto di >= 0,02 i due criteri sono in tensione; B ottiene -0,059 sui negativi al prezzo di -0,047 sulla pertinenza. Il protocollo non e' stato modificato; se lo si rivede, serve un nuovo turno con criteri registrati prima di misurare.
2. **Criterio 4 (vincoli):** le sole violazioni sono nei due casi con intervallo di anni (c26, c27), dove **A ha gia' 8 risultati su 10 fuori intervallo** perche' l'anno non e' un filtro del retrieval (e' un vincolo controllato dopo, dal reranker/`constraint_report`). B e C aggiungono 1-2 violazioni perche' sterzano verso film di altre epoche. Il criterio e' fallito cosi' com'e' scritto.
3. **Descrizione stimata per film assenti: non misurata.** Richiede un nuovo embedding (chiamata a pagamento); i casi con film assenti misurano solo lo stato `not_in_index` e il ritorno alla ricerca normale.
4. **Peso del testo (`text_repeat`) non esplorato**: congelato a 1, come da protocollo. E' la leva piu' ovvia per il compromesso del punto 1, ma provarla ora, dopo aver visto i risultati, non sarebbe una misura registrata prima.
5. I vettori del testo sono quelli salvati dalla baseline (nessuna nuova richiesta di embedding); il parser dei riferimenti (LLM) **non** e' stato eseguito: i riferimenti dei casi sono forniti a mano, come li produrrebbe un parser corretto. La capacita' del planner/parser di estrarre i titoli non e' misurata.
6. Un solo insieme di 28 casi costruito da me; film e coppie scelti prima della misura ma senza campionamento casuale.

## Valutazione qualitativa
Eseguita dopo il resto, **dal modello e non da una persona**, in modo non perfettamente cieco: vedi `qualitative_report.md`. In sintesi: B migliora l'assenza del tratto da evitare (4 casi migliori, 0 peggiori) ma riduce la pertinenza (4 peggiori, 2 migliori); C peggiora pertinenza (8 casi) e vicinanza (9 casi) senza un vantaggio chiaro. Non cambia il verdetto automatico. La valutazione umana resta non eseguita.

## Codice aggiunto (resta spento e non collegato all'orchestratore)
`references.py` (risoluzione deterministica: resolved / ambiguous / not_in_index / ignored_over_limit / estimated, esclusione dei film omonimi, guardia finale), `QdrantCollection.recommend`, opzioni `exact`/`ef` dello store, parametro `references` di `vectorstore.search` (senza riferimenti usabili la chiamata e' identica alla ricerca normale: testato), `CONFIG["rag"]["reference"]` con `enabled: False`, `strategy: None`.
**Non fatto:** campi `like_titles`/`avoid_titles` in `RagToolInput`, prompt del parser, regola di routing, trace e presenter. Cambiano lo schema del planner (richiedono il routing eval a pagamento) e non ha senso scriverli finche' nessuna variante supera i criteri.
