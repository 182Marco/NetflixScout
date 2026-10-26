# Fase 5 - valutazione qualitativa cieca (2026-10-26)

**Valutatore: il modello (Claude), non una persona**, su richiesta dell'utente. Fonte unica: `qualitative_sheets.md`. Giudizi per singolo risultato in `qualitative_judgments.json`, punteggi 0/1/2 per elenco in `qualitative_scores.json` (hash in `qualitative_scores.sha256`, **salvati alle 12:22:39, prima di aprire la chiave**), riepilogo in `qualitative_summary.md/json`.

## Condizioni e limiti (da leggere prima dei numeri)
- **Cecita' imperfetta:** il valutatore conosceva gia' le metriche automatiche aggregate e i delta per caso, ma non quale etichetta X/Y/Z fosse quale variante; `qualitative_key.json` e `ab_summary.md` non sono stati aperti prima del salvataggio. Gli elenchi identici tra etichette sono stati valutati in modo identico.
- Un solo valutatore, per di piu' un modello: **evidenza indicativa, non dimostrazione statistica** e non e' una valutazione umana (che resta non eseguita).
- Griglia a 3 livelli su 5 risultati, con anteprima di trama di 220 caratteri: alcuni giudizi si appoggiano alla conoscenza dei film. Regola esplicita di conversione dai giudizi per risultato ai punteggi di elenco (media >= 0,7 -> 2; >= 0,3 -> 1; altrimenti 0), applicata da uno script.
- "Fatti" misura solo la coerenza del record (titolo/anno/genere): non verifica i fatti sul mondo.
- 23 schede (i 5 casi di controllo, identici ad A per costruzione, non sono nel foglio).

## A. Risultati numerici (media dei punteggi per variante)

| variante | pertinenza | vicinanza ai film piacevoli | assenza del tratto da evitare | fatti |
|---|---|---|---|---|
| A ricerca normale | **1,39** | **1,00** | 1,57 | 1,96 |
| B `average_vector` | 1,22 | 0,95 | **1,86** | 1,96 |
| C `best_score` | 1,00 | 0,71 | 1,62 | 1,96 |

Vicinanza e assenza hanno 21 casi (esistono solo dove la scheda ha film piacevoli / da evitare); pertinenza e fatti 23.

Confronto accoppiato con A (casi migliori / uguali / peggiori):

| variante | pertinenza | vicinanza | assenza | fatti |
|---|---|---|---|---|
| B | 2 / 17 / 4 | 6 / 9 / 6 | **4 / 17 / 0** | 1 / 21 / 1 |
| C | 1 / 14 / 8 | 4 / 8 / 9 | 5 / 12 / 4 | 0 / 23 / 0 |

Quindici coppie di elenchi hanno punteggi identici; nessuna variante cambia la coerenza dei record (i tre elenchi con un record non-film, `plot_summaries.txt` e `README.txt` usati come titolo, sono ripartiti tra le varianti).

## B. Giudizio qualitativo (separato dai numeri)
- **B migliora l'assenza del tratto da evitare senza peggiorarla mai** (4 casi migliori, 0 peggiori): e' l'unico effetto netto in suo favore. Esempi: nella richiesta di fantascienza senza robot (c10) la ricerca normale apre con *The Terminators*, B no; in c05 B elimina i film americani della seconda guerra mondiale.
- **Il prezzo e' la pertinenza**: 4 casi peggiori contro 2 migliori. Nei casi peggiori la lista si sposta sul film di riferimento a scapito della richiesta (c05: i film sulla Prima guerra mondiale diventano film di sommergibili della Seconda; c18: l'elenco diventa quasi rumore). La vicinanza ai film piacevoli resta in pareggio (6 migliori, 6 peggiori).
- **C non ha un vantaggio qualitativo leggibile**: pertinenza peggiore in 8 casi su 23 (es. c06: da film sulla perdita di memoria a thriller generici; c16: nessun sommergibile sovietico), vicinanza peggiore in 9 su 21, assenza mista (5 migliori, 4 peggiori).
- **Disaccordo con le metriche automatiche (da riportare):** per C la similarita' coseno ai vettori dei film piacevoli *saliva* di molto (+0,14) ma il giudizio sulla vicinanza *scende*: avvicinarsi ai vettori dei riferimenti non equivale a restituire film che un lettore riconosce come vicini. Per B i due approcci concordano sull'effetto sui negativi (calo di similarita' e miglioramento della scheda 'assenza') e sul costo in pertinenza.
- Elenchi quasi identici tra varianti nei casi con un solo film di riferimento ben noto (c02, c14, c20) indicano che lo spostamento e' modesto quando il testo e il riferimento puntano nella stessa direzione.
- Osservazione sui dati, non sulle varianti: nel corpus compaiono chunk non-film (`MovieSummaries/plot_summaries.txt`, `README.txt`) tra i risultati di tre elenchi; un presidio al momento dell'indicizzazione o del filtro li escluderebbe per qualunque variante.

## Cosa questo cambia e cosa no
- Il verdetto automatico **non cambia**: nessuna variante soddisfa tutti i criteri registrati. La valutazione qualitativa non e' un criterio del protocollo e non puo' ribaltare l'esito.
- La lettura qualitativa e' coerente con quella automatica: B e' l'unica con un effetto utile (sui negativi) ma costa pertinenza; C non porta un vantaggio.
- Non e' una prova che B sia inutilizzabile: suggerisce che il compromesso va gestito (peso del testo, riferimenti usati solo quando l'utente chiede esplicitamente di evitare un film) e che serve una tornata successiva con criteri registrati prima.
