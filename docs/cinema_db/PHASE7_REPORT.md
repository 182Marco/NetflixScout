# Fase 7 — DB-first, qualità dei dati, routing: rapporto (2026-11-06)

Etichette: **[M]** misurato · **[I]** ipotesi · **[D]** da fare. Il flag `cinema_db.enabled` resta **spento di default**. **La fase non è conclusa sul punto che decide l'accensione:
il giudizio a ciechi del secondo giro è fermo a 51 coppie su 165** (crediti OpenAI esauriti, errore 429 anche al nuovo tentativo del 2026-11-06). Nulla qui è stato aggirato.

## 1. Cosa è stato fatto
- **Dati** (offline, nessuna richiesta Wikidata): premi dei vincitori (P1346) e conteggio uno per premio; puntate doppie e varianti di titolo degli episodi; build `build/4`, digest `c888ebd0f6cf953f…`, seconda build identica
  (`PHASE7_BUILD_REPORT.md`). Schema invariato (`generate --check` = 0).
- **Routing e affidabilità**: `tool/cinema_db/reliability.py` (stato per campo `verified|partial|uncertain|absent`, passo di completamento solo per il campo di cui la richiesta parla), regola 1g DB-first.
- **Dopo il secondo giro** (questa sessione, un solo difetto riproducibile): l'opera d'origine non audiovisiva è registrata con il solo titolo (autore e titolo originale assenti): nuovo campo `source_work`
  `partial` e passo verso `wikipedia_search` quando la richiesta parla di libro, romanzo, autore o «tratto da / based on» (casi B04 e B16).
- **Presenter SQL** (richiesta del proprietario, rovescia la scelta della fase 6 «nessun SQL»): lo step `cinema_sql_calls` porta `queries[]` = solo le query **realmente eseguite** (la guardia le registra dopo
  l'esecuzione), con `sql`, `params` ripuliti (controlli tolti, 120 caratteri, `***` se sembrano credenziali), `display_sql` (valori inseriti, solo per la lettura), `rows`, `ms`. Nessuna query soltanto pianificata,
  nessuna chiamata HTTP (`calls` non esiste), nessun'altra informazione interna fuori da `queries`. Terminale, web, contratto `chat_stream.md` e frontend (`render.js`, repository `marco-m-netflix`) allineati.
- **Harness**: il giudizio scrive gli errori in `judgments_credit_errors.jsonl`, non li conta come giudicati e si ferma dopo 3 errori consecutivi; `tool_ms` (tempo per tool) registrato nelle esecuzioni future.

## 2. Confronto live: misure [M]
55 domande × 3 ripetizioni × 2 modalità = 165 esecuzioni per modalità, planner/classificatore/tool/risposta reali, nessun embedding. Dati: `cinema_db/data/phase7_live/` (ignorata da git).

| | Spento | Acceso, giro 1 | Acceso, giro 2 |
|---|---|---|---|
| Richieste HTTP | 222 | 88 (−60 %) | 116 (−48 %) |
| Tempo totale | 1.865 s | 1.701 s (−9 %) | 1.950 s (+5 %) |
| Passi di tool | 221 | 231 | 250 |
| Query SQL | 0 | 422 | 391 |
| Fatti attesi (controllo meccanico) | 77/111 | 93/111 | 100/111 |
| `cinema_sql` scelto | — | 124 | 119 |

Giudice (`gpt-5.5`, a ciechi): **giro 1, 165 coppie: 71 acceso, 32 pareggi, 62 spento. Giro 2: 51 coppie su 165 (domande B01–B17): 27 acceso, 5 pareggi, 19 spento; le 114 restanti NON giudicate.** Sulle stesse 51 coppie
il giro 1 dava 25/6/20: nessun cambiamento apprezzabile nella metà giudicata. Le domande toccate dalle correzioni del giro 2 (E03, B30, P01, X05, premi) sono tutte nella metà **non giudicata**.

Fatti attesi per domanda (giro 2): acceso ≥ spento in tutte le domande con attese tranne B13 (1/3 contro 2/3). Tre domande hanno 0 fatti in entrambe le modalità per attese non adatte, non per errore: B11 (l'acceso risponde
con un numero, 22 film «tra quelli registrati»), E04 (l'acceso nomina il produttore, Albert S. Ruddy; l'attesa cercava «Paramount»), P05 (TVmaze chiede quale *Friends*; identico in entrambe). Il controllo meccanico
**non decide** nulla da solo (indicazione del proprietario).

## 3. Latenza: diagnosi [M salvo dove indicato]
- Costo per passo: a modalità spenta una domanda con 1, 2, 3, 4 passi di tool dura in media 8,8 / 17,0 / 25,4 / 33,1 s; ≈ **8,3 s per passo** (ogni passo è una chiamata di pianificazione più il tool). Con DB acceso 8,6 / 15,1 / 22,0 / 30,4 s.
- L'acceso fa **+29 passi** (250 contro 221): 35 esecuzioni a due passi contro 21. Sono i passi voluti dalla regola 1g (cinema_sql + completamento: cast in rilievo, premi generali, punteggi). 29 passi × ≈ 8 s ≈ 240 s di costo teorico, ben sopra gli +85 s netti: il resto è compensato dalle domande che passano da 3–4 passi esterni a un solo passo locale (B04, B16, E01: −20/−29 s).
- Somma per coppia: nelle 119 coppie in cui l'acceso usa `cinema_sql` la differenza di tempo è **+13 s**; nelle 46 in cui non lo usa è **+72 s** (E03 ripetizione 3: stesso tool, +30 s). Quindi il +5 % **non è attribuibile al
  database**: è per metà rumore delle API esterne.
- Rumore: lo stesso insieme di domande con la stessa modalità accesa è durato 1.701 s nel giro 1 e 1.950 s nel giro 2 (+249 s, cambia solo il routing); la dispersione mediana tra ripetizioni di una domanda spenta è 2 s.
- SQL: il tempo per query non è registrato in questi giri. Benchmark della fase 5: mediana 33 ms; 391 query × 33 ms ≈ 13 s al massimo **[I]**, circa 0,7 % del totale. Non è la causa.
- Ripetizioni di `cinema_sql` nello stesso turno: 10 esecuzioni; X05 (due turni, attese), E02 (omonimo John Williams: seconda ricerca dopo l'ambiguità), X08 e P01 (due ruoli/premi). Non c'è un duplicato dello stesso
  identificativo dimostrato dai dati registrati; gli argomenti dei passi non sono salvati, quindi **non dimostrabile** **[D]**: nelle prossime esecuzioni `tool_ms` e i passi per tool permettono di farlo.
- **Nessuna ottimizzazione di latenza applicata**: nessuna causa isolabile con le evidenze disponibili. L'unica modifica di questa sessione che tocca il numero di passi *aumenta* leggermente i passi (`source_work`, solo
  per richieste su libro/autore/«tratto da»), a favore della completezza.

## 4. Analisi qualitativa (giudizi disponibili: 165 del giro 1, 51 del giro 2, motivi letti a mano)
Domande dove lo spento vince in modo stabile e causa:
| Domanda | Causa | Tipo |
|---|---|---|
| B04 Blade Runner, da quale libro | l'opera d'origine ha solo il titolo italiano, senza Dick né titolo originale | **dato** (corretto con `source_work`, non verificato live) |
| B16 Oppenheimer, da cosa è tratto | l'opera d'origine è «Robert Oppenheimer, il padre della bomba atomica», titolo parziale | **dato** (idem) |
| B07, B10 Parasite | il database chiede quale film; il giudice preferisce la risposta diretta | **scelta voluta** (omonimi, non modificata) |
| B02 sceneggiatura di Blade Runner | cautela «può includere gli autori del materiale d'origine» giudicata fuorviante | **scelta voluta** (X08, crediti `writer`) |
| B14 Rotten Tomatoes Oppenheimer | tutte e due le modalità usano OMDb: il planner non passa l'anno e OMDb dà due opere | **planner/tool esterno**, non il database |
| B13 critica sui film di Villeneuve | il planner ha dato candidati non pertinenti a OMDb; la filmografia locale è corretta (9 film) | **planner** |
Domande dove l'acceso vince 3 volte su 3 nel giro 2 (solo tra quelle giudicate): B01, B03, B05, B06, B09, B11, B15. Su B01 lo spento elenca anche *Dune – Parte tre* (2026) e *Untitled James Bond Film*, progetti non
usciti; l'acceso lascia fuori due film (*Polytechnique*, *32 août sur terre*: catalogo incompleto, dichiarato). Per le altre domande (E01, E09, X03, X10…) non c'è un giudizio del giro 2.

Errori per origine **[M, letti nei motivi del giudice]**: database/dati 2 (B04, B16); scelte volute 2 (omonimi, crediti writer); planner/tool esterni 2 (B13, B14). Fallback esterni mancanti: nessuno osservato nelle 51 coppie
giudicate del giro 2. **Le 114 coppie non giudicate non sono state analizzate qualitativamente**: sono lette solo tramite tool usati, HTTP e controllo meccanico.

## 5. Presenter SQL: stato [M]
Percorso `cinema_sql` → `Session.calls` (registrato solo dopo l'esecuzione) → `trace.build_trace` → `cinema_calls_view` (pulizia dei parametri, `display_sql`) → `serialize_cinema_sql_calls_step` → evento SSE `step`
(validato da `EVENT_MODELS["step"]`) → `render.js` (`cinemaLines`, righe «Query SQL eseguite» come `db_query`). Test: `tests/test_cinema_presenters.py`, `tests/test_cinema_sql_turn.py` (guardia reale su database miniatura),
`tests/web_api/test_web_api_doc.py` (esempio del contratto = serializzatore), `tests/test_cinema_frontend_render.py` (Node 22 sul frontend vero). **Non verificato** in un browser reale (nessun `npm run build`).

## 6. Mappa del database [M, con un limite]
`docs/cinema_db/schema.html` (grafo interattivo) è generata dal file SQLite reale; `generate --check` = 0 (non obsoleta). Contiene tabelle, colonne, tipi, chiavi primarie, chiavi esterne come archi con simboli ER (una barra =
uno, cerchio = zero, zampa di gallina = molti), direzione figlio → genitore, chiavi opzionali tratteggiate, tabelle ponte (molti-a-molti) in arancione, sottotipi, indici e vincoli CHECK per tabella, viste pubbliche.
Test offline verdi: un nodo per tabella, un arco per chiave esterna, nessuna relazione inventata, percorsi finiti anche per le auto-relazioni, nessuna sovrapposizione di nodi, ponte = chiave primaria su due entità,
Mermaid = chiavi esterne. **Il test nel browser vero (`CINEMA_MAP_BROWSER_TEST=1`) non si è concluso in questa sessione**: Chrome headless non risponde nell'ambiente della shell (timeout a 90 s e a 300 s) e il tentativo
fuori sandbox non è stato autorizzato, quindi la navigabilità reale (zoom, selezione, evidenziazione) in questa sessione **non è stata riverificata** **[D]**: aprire il file e provare, o eseguire il test da un terminale normale.

## 7. Suite
Suite di `AGENTS.md` sullo stato iniziale (modifiche non committate della sessione precedente, prima delle mie): **2.618 passati, 1 saltato** (78 s; la suite lanciata nella sessione precedente non aveva lasciato un log).
Suite finale, dopo tutte le modifiche: **2.619 passati, 1 saltato** (63 s). Il saltato è il test del browser reale della mappa (opt-in).

## 8. Raccomandazione sull'accensione di default
**Non accendere ancora. [Decisione del proprietario; il flag non è stato toccato.]**
A favore **[M]**: richieste HTTP −48 % / −60 %; più fatti attesi (100/111 contro 77/111) con la stessa o minore dipendenza da servizi esterni; nessun errore su 330 esecuzioni; vittorie dell'acceso nel giro 1 (71 contro 62).
Contro **[M]**: giudizio del giro 2 incompleto (31 % delle coppie), e proprio le domande corrette dopo il giro 1 non sono giudicate; 11 domande che lo spento vince 3 volte su 3 nel giro 1 (quattro avevano cause di routing o di query:
B08, E03, B30, P01; corrette, ma la prova live manca perché non giudicate); la latenza non migliora in modo dimostrato (+5 % contro −9 %: rumore ±250 s); il risparmio di chiamate non vale se la qualità peggiora, e le due cause dati (autore dell'opera
d'origine, elenchi con catalogo incompleto) sono dichiarate ma non eliminate.
Criteri per accendere **[D]**: (1) completare le 165 coppie del giro 2 con i crediti; (2) un terzo giro con le correzioni di questa sessione (`source_work`), registrando `tool_ms`; (3) nessuna domanda persa 3 su 3 per
cause dei dati; (4) latenza non peggiore oltre il rumore misurato. Rischio residuo se si accende ora: risposte su libro d'origine e omonimi meno complete di quelle esterne.

## 9. Aperto
- Giudizio di 114 coppie (serve credito OpenAI); terzo giro dopo `source_work`.
- Verifica nel browser reale della mappa del database e del frontend con le query SQL.
- Richieste Wikidata (181 vincitori, pilota di 12 persone, 21 per i franchise con `franchise.kind`, 100–150 per le persone): **NON eseguite, servono autorizzazioni** (`PHASE7_WIKIDATA_PLAN.md`).
- Omonimi e crediti `writer`: scelte volute. Conteggi di episodi (Game of Thrones, I Soprano senza stagioni nella fonte), remake non distinguibili (`remake_of` vuota), catalogo incompleto dopo il 2019.
- Il frontend `dist/` non è ricostruito.
