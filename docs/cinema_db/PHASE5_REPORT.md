# Fase 5 — il tool `cinema_sql` (2026-11-06)

Il tool interroga in sola lettura il database cinematografico locale (`cinema_db/data/cinema.sqlite3`, digest `b3b0de51…`, schema v2 invariato). **Non è integrato**: `app.py`, il planner, le regole di routing, i presenter, `CONFIG` e le impostazioni utente non sono stati toccati. Il tool soddisfa il protocollo `Tool` (`name`, `description`, `input_schema`, `run`), quindi collegarlo sarà registrazione e routing, non lavoro sul tool. Numeri del benchmark: `PHASE5_BENCHMARK.md` e `.json` (generati).

## 1. Architettura

Le richieste del planner arrivano come `operation` + argomenti tipizzati (`CinemaSqlInput`, `extra="forbid"`). Il modello **non scrive SQL** per le 12 operazioni dedicate: `queries.py` sceglie quale query approvata eseguire, con frammenti costanti e parametri legati, e ogni istruzione passa comunque dal motore sicuro della Fase 1 (validatore sull'AST, connessione `mode=ro` + `immutable`, authorizer con negazione predefinita, limiti di tempo, righe e byte). La tredicesima operazione, `sql`, accetta una SELECT libera sulle sole viste approvate (decisione D2 del piano), con tutte le difese esistenti. Il motore sicuro non è stato modificato.

Un'esecuzione apre la connessione (10 ms misurati), risolve le entità, esegue poche query mirate, chiude. La connessione non è condivisa tra thread (il server web esegue ogni turno in un thread diverso).

### File e responsabilità (`tool/cinema_db/`, nuovi)
| File | Responsabilità |
|---|---|
| `models.py` | `CinemaSqlInput`: 13 operazioni, identificativi accettati solo se dati da utente, conversazione o passo precedente (`work_id`, `person_id`, `imdb_id`, `wikidata_id`, `tmdb_id` con `type`), regole di coerenza (es. `tmdb_id` senza `type` rifiutato perché gli id di film e serie si sovrappongono, `awards` con esattamente un bersaglio), errori che nominano il campo e mai il valore |
| `resolve.py` | risoluzione di opere, persone, società e franchise: identificativo, poi nome normalizzato (titolo, titolo originale, tradotto, alias), poi ricerca testuale solo come alternative. Stati `resolved`, `ambiguous`, `unverified`, `not_found`; nessuna fusione; un dato mancante non è una corrispondenza |
| `queries.py` | tutto l'SQL del tool: costanti, parametri legati, limiti interi già validati, nessun testo del modello |
| `operations.py` | le 13 operazioni e il formato dei risultati (con totale, elementi mostrati, troncamento e note sui limiti dei dati) |
| `session.py` | una esecuzione: validazione, budget di query per turno (per `turn_id`, con blocco, limitato), registro delle istruzioni realmente eseguite |
| `tool.py` | `CinemaSqlTool`, `planner_schema()` compatto (3.825 caratteri, descrizione 2.457 con le viste generate dalla policy), `FINAL_INSTRUCTIONS` (per `tool_final_instructions`), esiti `ok`/`empty`/`error` e `follow_up` |
| `constants.py` | tipi di opera, limiti, e le **note sui limiti dei dati** (un'unica fonte, 16 codici stabili) |
| `trace.py` | step `cinema_sql_calls` (SQL riscritto, parametri, viste, righe, ms, licenza) |
| `config.py`, `names.py` | `CinemaDbConfig` senza default (valori suggeriti in `SUGGESTED_CONFIG`, da mettere in `CONFIG["cinema_db"]` al collegamento) e la normalizzazione dei nomi identica a quella della build |

### Operazioni
`find_work`, `find_person` (identificano: id, anno, regia, alternative), `work_card` (scrittori, compositori, generi, paesi, società, importi), `filmography` (con ruolo, tipo, intervallo di anni, ordine, totale), `cast`, `crew`, `collaborations` (opere in comune di due persone, oppure i collaboratori più frequenti), `awards` (di un'opera, di una persona o per nome del premio), `series` (stagioni, o episodi di una stagione), `companies` (di un'opera, o le opere di una società), `franchise`, `relations`, `sql`.

### Viste usate
Le operazioni leggono 13 delle 20 viste approvate: `v_name`, `v_title_search`, `v_work`, `v_person`, `v_credit`, `v_award_result`, `v_external_id`, `v_work_company`, `v_franchise`, `v_work_relation`, `v_work_genre`, `v_work_country`, `v_work_financial`. L'operazione `sql` può leggere tutte le 20. Nessuna tabella di base è leggibile dal modello.

### Riuso degli identificativi
Ogni risultato riporta `work_id`/`person_id`, `imdb_id`, `tmdb_id`, `wikidata_id` dell'entità e, per le prime 15 opere di una filmografia o di un franchise, `imdb_id` e `tmdb_id` di ciascuna (una query in più, nota `ids_partial` oltre le 15). Con un id il titolo non si cerca: **non si risparmiano query** (la scheda e i registi costano come la ricerca per nome: misurato 4 contro 4), si elimina l'ambiguità e la ricerca approssimativa (con `work_id` «Crash» non è ambiguo). Il guadagno vero è alimentare passi esterni: la filmografia di Villeneuve dà 5 id IMDb pronti per OMDb.

### Onestà sui dati mancanti
Ogni risultato porta note (`notes`: codice e testo) e `follow_up` (un solo passo verso lo strumento online corrispondente) quando è `empty`, `not_found` o `unverified`, mai quando è `ambiguous` (decide l'utente). Le istruzioni finali vietano di dedurre che qualcosa non esista. Le note dichiarano i limiti **verificati sui dati reali** (vedi §6).

## 2. Impostazioni
`SOURCE_CATEGORY = "official information"` in `tool.py`, con la motivazione verificata sui dati: fatti strutturati enciclopedici di Wikipedia e Wikidata, come `wikipedia_search` e `tmdb_search`; nessun voto del pubblico (non è `user ratings`), nessun punteggio o testo di critica (non è `reviews`: i premi sono riconoscimenti dell'industria, non recensioni), nessuna intervista, nessuna trama (nessuno spoiler), film e serie. Un test verifica che nessun risultato contenga chiavi di punteggi, voti, recensioni o trame, che la categoria esista in `preferences/fields.json` e che `preferences/behavior.py` **non** nomini ancora `cinema_sql`. Il comportamento effettivo delle impostazioni non è cambiato; il test del conflitto preferenza/richiesta esplicita (richiesto dalla skill) spetta al collegamento.

## 3. Test (offline, gratuiti)
| File | Test | Cosa copre |
|---|---|---|
| `tests/test_cinema_sql_tool_real.py` | 37 | **database reale** (si salta con motivo se manca): titolo, alias e titolo originale; id esterni (IMDb, Wikidata, TMDb con tipo, `work_id`) e id in disaccordo; persona, omonimi e anno di nascita; filmografia con totale, intervallo, ordine, limite, id per il passo successivo; cast, crew, collaborazioni (a coppie e frequenti), premi (opera, persona, nome e anno), serie, società, franchise, relazioni; omonimi (Crash, The Godfather, John Williams); vuoti, non trovato, nomi simili, anno sbagliato; **protezioni**: SQL libero e istruzioni vietate (INSERT, DELETE, DROP, PRAGMA, ATTACH, tabelle di base, `load_extension`, due istruzioni), file del database invariato (dimensione, mtime, nessun journal), limite di righe, budget del turno, interruzione per tempo o piano, database mancante; **correttezza**: 40 persone (filmografie) e 40 film (cast e premi) a campione con seme fisso, ricalcolati con SQL indipendente sulle tabelle di base |
| `tests/test_cinema_sql_tool.py` | 28 | miniatura costruita dalla build vera (dati inventati, deterministici): operazioni, validazione degli input (valori mai riportati), schema del planner, protocollo del tool, nessun codice di rete o LLM nel pacchetto, ogni query possibile passa dal validatore, nessun testo del modello nelle query, categoria delle impostazioni |
| `tests/test_cinema_sql_benchmark.py` | 6 | le 30 domande coincidono con la baseline, la verifica indipendente rileva una risposta alterata, una scelta impossibile di candidato è segnalata, i totali del confronto |
Suite richiesta da `AGENTS.md`: **2.545 test passati** (2.474 prima della fase: +71), schema invariato (`generate --check` esce con 0). I valori attesi dei test reali sono stati controllati a mano con SQL indipendente prima di scriverli.

## 4. Benchmark (`PHASE5_BENCHMARK.md`)
39 domande: le 30 della baseline e 9 aggiuntive; 30 eseguite, 9 non applicabili (streaming, trailer, uscite, voti MovieLens, consigli semantici, prossimo episodio, prosa). Esiti: **22 corrette, 5 corrette dopo la scelta tra omonimi, 2 con elenco di alternative come risposta attesa, 1 non trovato corretto, nessuna sbagliata** rispetto a SQL indipendente sulle tabelle di base. Per ogni domanda: risposta, query, millisecondi (mediana di 5), e la **mia lettura manuale** contro ciò che so del mondo (non un controllo automatico).
- **Query**: 116 sul totale, mediana 3 per domanda (da 1 per `sql` a 7 per `work_card`; 4 per cast e filmografia; 5 per episodi).
- **Tempo** (query, risoluzione e apertura della connessione, tutti i passi di una domanda): mediana **33 ms**, massimo **83 ms**. Nessuna richiesta di rete.
- **I piani sono scritti da me, non da un planner LLM**: non si misura quale piano scriverebbe un planner reale né il costo di pianificazione.

## 5. Confronto con la baseline (30 domande)
- Copertura teorica: **13 complete, 8 parziali, 9 nessuna** (nessuna: streaming, trailer, uscite, voti MovieLens, consigli semantici, prossimo episodio, prosa).
- Verificate: 12 delle 13 complete risolvono la domanda; **B05 e B17** (remake di The Thing e di Solaris) restituiscono relazioni corrette ma il database non dice «remake»: la domanda resta da Wikidata o Wikipedia.
- Richieste HTTP: oggi 96; la baseline assumeva 49 dopo; **verificate 56** (la differenza sono B05 e B17, che non si risolvono localmente: 7 richieste). È un conteggio di richieste tra due piani scritti a mano, **non** la misura di turni reali.
- **Costo non previsto dalla baseline**: 5 domande (B05, B07, B10, B17, B29) hanno un titolo omonimo («Parasite» è anche il titolo originale di un film del 1982, «The Thing», «Solaris») e richiedono un secondo passo di pianificazione dopo le alternative; la baseline le contava a un solo passo.
- Sostituibili del tutto con una risposta verificata: `tmdb_search` per filmografie, regie, sceneggiatori e compositori (B01–B03, B11–B12); `wikidata_search` per fonti, franchise e omonimi (B04, B06, B09); `wikipedia_search` usato oggi per i premi (B07, B08) e `tvmaze_search` per le stagioni (B26). Restano indispensabili: OMDb (punteggi), YouTube (interviste), TVmaze (numerazione degli episodi), Wikidata o Wikipedia per «remake», e tutti i tool per i dati che il database non ha.

## 6. Limiti noti (misurati sui dati reali)
1. **Catalogo incompleto**: mancano film (2 di Villeneuve: *Un 32 août sur terre* 1998 e *Polytechnique* 2009), il cast è parziale e senza ordine di rilievo, i 99 film italiani del 1960 sono meno dei reali. Una risposta locale può essere incompleta senza che il tool lo sappia: le note e `follow_up` lo dichiarano, il rischio resta.
2. **Premi per persona**: un risultato è attribuito a una persona solo se la fonte nomina il nominato. Le vittorie di *Oppenheimer* (miglior film e regia) sono nel database sul film ma non sul nominato, quindi `awards` di Nolan non le mostra (6 risultati, tutte candidature). Nota `awards_person_scope`; per le vittorie conviene anche `awards` dell'opera.
3. **Conteggi degli episodi inaffidabili** (difetto di dati della Fase 3): Breaking Bad S1 8 righe/7 numerate (reali 7), S4 13/11 (reali 13), S5 18/0 (reali 16); in *Dark* gli episodi non hanno numero. Il tool riporta `episodes` e `numbered_episodes` e la nota `episode_duplicates`. **Non corretto**: richiederebbe una modifica ai dati (vedi §8).
4. **«Franchise» può essere una lista**: *Inception* risulta «parte» di «i 100 migliori film del XXI secolo secondo la BBC» (Wikidata registra anche liste e raccolte come «parte della serie»). Nota `franchise`. **Non corretto**: richiederebbe la classe degli elementi (§8).
5. **Remake non distinguibile**: «basato su» comprende remake, adattamenti e opere solo ispirate; «segue» è l'ordine in una serie (nota `relations`).
6. **Titoli omonimi**: l'ambiguità è dichiarata, non risolta con euristiche; è la scelta più sicura (con una regola «il titolo primario vince» *The Godfather* darebbe il cortometraggio del 1911).
7. **Premi per nome**: i nomi sono quelli registrati (spesso in italiano; una categoria compare a volte come premio a sé); la ricerca è per sottostringa, con la categoria esatta elencata per prima.
8. **Date di vita ambigue non importate** (Fase 4) e luogo di nascita assente (`birth_country` sempre vuoto).
9. Non coperti dalle operazioni dedicate (restano raggiungibili con `sql`): generi e paesi come filtro di ricerca, date di uscita per paese, importi per opera fuori dalla scheda.
10. Nessun presenter né serializzatore web per lo step `cinema_sql_calls` e nessun test di routing: appartengono al collegamento.

## 7. Come eseguire e verificare
```bash
python -m pytest tests/test_cinema_sql_tool.py tests/test_cinema_sql_tool_real.py tests/test_cinema_sql_benchmark.py -q   # offline, ~10 s
python -m cinema_db.harness.tool_eval.run_benchmark          # riscrive PHASE5_BENCHMARK.json e .md (offline, gratis, ~10 s)
python - <<'E'                                                # una prova a mano
from tool.cinema_db.tool import CinemaSqlTool
from tool.cinema_db.config import CinemaDbConfig, SUGGESTED_CONFIG
tool = CinemaSqlTool(config=CinemaDbConfig(**SUGGESTED_CONFIG))
print(tool.run(query="film di Nolan", params={"operation": "filmography", "person": "Christopher Nolan", "role": "director"})["metadata"])
E
```
Le istruzioni per il modello sono `tool.tool.FINAL_INSTRUCTIONS`; la policy delle viste è `tool/cinema_db/approved_views.py` (generata dal file SQLite).

## 8. Problemi che richiederebbero modifiche ai dati (NON applicate: serve una decisione)
1. **Episodi doppi o senza numero** (build della Fase 3): la pagina di un episodio senza numero e la riga della tabella dello stesso episodio non si riconoscono come uno. Proposta: nella build, unire le pagine-episodio senza numero alla riga numerata della stessa stagione quando il titolo coincide a meno del qualificatore tra parentesi («Questione di chimica (Breaking Bad)»); poi ricostruire e rieseguire `verify --reproduce`. Costo: modifica a `build.py`, nuova build (~7 minuti), nessuna richiesta di rete.
2. **Franchise che sono liste**: proposta: leggere da Wikidata la classe (`P31`) dei ~1.071 elementi franchise (circa 22 richieste, come in Fase 4) e importare solo le classi «franchise media», «serie di film», «universo narrativo»; le liste e le raccolte resterebbero fuori. Richiede una nuova autorizzazione per la rete.
3. **Attribuzione dei premi** (miglior film alle persone): nessuna proposta di inventare un nominato; si può esporre `awards` dell'opera accanto a quella della persona (già possibile con due passi).
4. **Catalogo**: i film mancanti non sono recuperabili con una modifica locale (non sono nel catalogo di origine).

## 9. Prossimi passi e decisioni per autorizzare l'integrazione (Fase 6)
Per integrarlo senza modificare il comportamento attuale servono, in questo ordine, e nessuno è stato fatto:
1. **Autorizzare la modifica di `app.py`**: registrare il tool in `build_app` e in `allowed_tools` (spento di default), `CONFIG["cinema_db"]` con `SUGGESTED_CONFIG`, `tool_final_instructions["cinema_sql"] = FINAL_INSTRUCTIONS`.
2. **Regola di routing** nel planner (senza rinumerare le altre), che dica quando preferire `cinema_sql` e quando ricadere su Wikidata, TMDb e Wikipedia: ciò cambia il prompt di planning e richiede il routing eval con il planner reale (a pagamento, con permesso). Il costo di un passo in più per gli omonimi va misurato lì.
3. **Impostazioni**: `SOURCE_TOOLS["cinema_sql"] = "official information"`, con il test del conflitto preferenza/richiesta esplicita e la guardia per `content_type` (il tool non filtra film e serie da sé: `filmography` e `find_work` accettano `type`).
4. **Presenter**: vista condivisa, renderer terminale, serializzatore web e contratto del frontend per `cinema_sql_calls`; le fonti (Wikipedia CC BY-SA, Wikidata CC0) vanno mostrate dall'interfaccia, mai affidate al modello.
5. Decisioni sui problemi di dati del §8 e sul ritiro (o no) di `wikidata_search`, che con il tool diventa un ripiego.
