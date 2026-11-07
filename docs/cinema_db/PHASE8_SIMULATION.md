# Fase 8 — simulazione offline degli interventi 3 e 4 (generata da `simulate_phase8.py`)

Dati: 165 esecuzioni con DB acceso del secondo giro (`phase7_live/runs.jsonl`), 1950 s totali. Nessuna API. **[M]** misurato · **[C]** classificazione dichiarata a mano dal testo della domanda (tabella `DECLARED`) · **[S]** stima.

## Cosa i dati NON permettono
- Gli **argomenti** dei passi non sono registrati: l'indipendenza dal risultato locale è una classificazione [C], non una lettura.
- Le chiamate del planner che rispondono solo «fatto» e il tempo di ogni chiamata non sono registrati (i `timings` esistono solo dai run futuri): i passi sotto sono un **limite inferiore**.
- Il peso in secondi di UNA chiamata del planner non è misurato. Due indizi in conflitto: la regressione del tempo sui passi dà 4,7 s (spento) e 6,8 s (acceso) per passo, ma un passo comprende anche il tool e una risposta con più contesto; il confronto a coppie `cinema+X` contro `X` solo sulla stessa domanda dà da 0,0 s (P06) a 12 s (X02, n=1). Il tempo risparmiato è quindi un **intervallo largo [S]**.

## Passi successivi al primo, per classe [C]
Passi dopo il primo (ognuno costa almeno una chiamata `_plan_next`): **85**. A (richiesti e indipendenti) 24 · B (condizionati) 38 · C (argomenti da risultati) 19 · D (non richiesti dalla domanda) 1 · U (non dichiarati) 3.

| Domanda | Classi dei passi successivi (3 ripetizioni) |
|---|---|
| B05 | B×1 |
| B13 | C×19 |
| B15 | A×5 |
| B16 | A×3 |
| B17 | A×3 |
| B18 | A×3, B×3 |
| B30 | U×2 |
| E02 | B×1 |
| E05 | D×1 |
| E06 | B×3 |
| E08 | B×5, U×1 |
| P01 | A×3, B×7 |
| P03 | B×3 |
| P04 | B×3 |
| P06 | A×3 |
| P08 | A×3 |
| X02 | A×1 |
| X05 | B×3 |
| X07 | B×3 |
| X08 | B×6 |

## Intervento 3 — passi già pianificati eseguiti senza `_plan_next`
- Candidati: la classe A, **24** passi su 85 [C]. Risparmio: **24 chiamate di planner** (−28 % dei passi successivi), **0 chiamate esterne** (i tool partono comunque), 0-163 s su 1950 s (0.0-8.4 %) [S].
- Non applicabile ai passi B, C e D: dipendono dal risultato o non servono.
- **Costo non simulabile**: il primo planner dovrebbe scrivere gli argomenti di TUTTI i passi (lo schema di TMDb è 12.232 caratteri; un argomento sbagliato fa rifiutare l'intera richiesta). L'output cresce e il rischio si sposta sulla prima chiamata. Contraddice la scelta D7 solo se i passi diventano paralleli: qui restano in sequenza.
- **Rischio DB-first**: la stessa meccanica, applicata a un passo D (E05), lo renderebbe obbligatorio. Va limitata ai dati che il DB non ha.

## Intervento 4b — OMDb per più titoli in un passo
- Turni con ≥2 passi OMDb (DB acceso): 3 (B13 r1: 5 passi, 45 s, B13 r2: 6 passi, 49 s, B13 r3: 5 passi, 30 s). Risparmio: **13 chiamate di planner**, **0 richieste HTTP** (stessi titoli, stesso costo di budget), 0-88 s [S]. Un solo caso di domanda (B13) con 3 ripetizioni: campione piccolo.
- Completezza: invariata se tutti i titoli sono elaborati; il budget di 10 richieste per turno copre 5 titoli per titolo (2 richieste ciascuno), 10 per id. Ogni titolo deve riportare il proprio stato (ambiguo, non trovato) invece di fallire insieme agli altri.

## Intervento 4a — meno completamenti per campi `partial`
- Passi interessati: i premi di una persona (E06, P03, P04), **9** esecuzioni con un passo Wikipedia dopo `cinema_sql`. Risparmio teorico: 9 chiamate di planner e 9 passi Wikipedia (le richieste HTTP registrate sono poche per la cache del tool: non misurabile qui).
- **Completezza persa [M]**: `awards` di Christopher Nolan con `award: Oscar` dà 6 risultati (5 candidature, 1 vittoria: regia di *Oppenheimer*); la vittoria come produttore del miglior film (*Oppenheimer*) non c'è, quindi «quanti Oscar ha vinto» direbbe 1 invece di 2. Denis Villeneuve: 1 candidatura (*Arrival*, regia); manca *Dune* come miglior film [conoscenza generale, non verificata con una fonte in questa sessione]. Dato noto già in `PHASE5_REPORT.md` §6.2.
- Il campo `partial` con righe presenti NON significa «completo»: soglia sulla sola presenza di righe = risposte sbagliate con tono sicuro. **Da scartare** come regola generale. Resta possibile togliere il completamento solo quando la richiesta non riguarda il totale o l'elenco (es. «ha vinto un Oscar per la regia?»), ma questo è un giudizio del planner e non una soglia: nessun guadagno certo.

## Passi extra non richiesti (classe D) — osservazione
- 1 passi D: un passo `cinema_sql` prima di TMDb dove la domanda è di TMDb (E05, E08) (solo E05 è rimasto D). X07 NON è un passo superfluo: era stato classificato D per errore, e controllando il database reale la filmografia solo-serie di Nolan è vuota (`no_credits_in_catalogue`, `follow_up` verso TMDb), quindi il passo TMDb è il ripiego previsto di un risultato vuoto (B). Confronto a coppie [M]: X07 `cinema>tmdb` 15,2 s contro `tmdb` 9,8 s (n=3, ma `tmdb` da solo non può sapere che il locale è vuoto); E05 15,0 s (n=1) contro 7,0 s; stesso percorso su P06: 10,3 contro 10,3 s. Qui il guadagno possibile è nella regola di routing (1g contro 1), non nel ciclo.
