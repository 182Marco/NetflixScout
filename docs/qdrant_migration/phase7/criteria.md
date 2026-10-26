# Fase 7 - end-to-end reali (NON eseguita: richiede autorizzazione, usa OpenAI, Cohere, TMDb)

Criteri scritti prima di eseguire. Funzione catalogo spenta (`CONFIG["catalog"]["enabled"] = False`).

## Esiti
- **Pieno**: nessun riferimento tra i raccomandati; vincoli di metadati rispettati; i film raccomandati sono quelli del contesto; la risposta
  rispetta gli stati dei vincoli (`tests/answer_checks.py`) e non presenta una stima come fatto.
- **Parziale**: una condizione non essenziale violata (es. un solo film fuori vincolo non verificabile).
- **Errato**: riferimento riapparso, vincolo rigido violato, stima presentata come fatto, errore di tool o risposta non pertinente.
Per ogni domanda: testo esatto, tool e motore effettivi, risultati, esito e motivazione, confronto con la baseline, secondi, errori.

## Domande
`questions.json`: 20 domande normali (RAG semantico e hybrid, `k_finale`, DB, TMDb, fuori tema) eseguite con `engine=qdrant`.
La ricerca guidata (riferimenti positivi/negativi) è spenta (Fase 5): nessuna domanda positiva/negativa in questa fase.
Blocco separato sul catalogo (5-6 domande su film assenti dall'indice, post-2012) solo su un CLONE dello storage e solo dopo
calibrazione C e decisione del proprietario.

## Valutazione
Pause >= 30 s tra gli invii. Valutazione cieca (ordine casuale, etichette anonime, griglia 0/1/2) solo se si confronta con Chroma;
un solo valutatore = evidenza indicativa, non dimostrazione statistica. Dopo ogni correzione: casi toccati, poi suite offline.

## Esecuzione
`CHROMA_COMPARE` non previsto. `PHASE7_AUTHORIZED=yes VECTORSTORE_ENGINE=qdrant python docs/qdrant_migration/phase7/run_e2e.py --out DIR`
(rifiuta di partire senza la variabile).

## Risultati salvati
Un file per domanda (`auto_class`, `auto_reasons`) e `summary.json` con i conteggi `completed`/`partial`/`missed`/`error`. È una pre-classificazione meccanica (errore del turno, risposta vuota o nessun tool = non successo; fallback silenziosi ed esiti di tool errati o vuoti = parziale), non un giudizio: pieno/parziale/errato si decide leggendo le risposte con i criteri sopra. Il runner esce con codice 1 se almeno un turno ha sollevato un errore.
