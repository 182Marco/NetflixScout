---
name: new-netflixscout-tool
description: Progetta e implementa un nuovo tool dell'orchestratore di NetflixScout (nuova API, nuova fonte dati, nuova operazione). Da usare quando si deve aggiungere un tool accanto a rag_search, movie_db_search, tmdb_search, youtube_search, o decidere tool interno vs MCP.
---

# Nuovo tool in NetflixScout

`AGENTS.md` è la fonte di verità su contratti e regole (non duplicarlo: rileggi le sezioni "Contratto dei tool",
"Avanzamento in tempo reale", "Trace dei tool", "Catalogo nel planner", "Regole di ingaggio"). Questa skill dice
**cosa ispezionare, cosa decidere, in che ordine costruire e come verificare**. Se `AGENTS.md` e il codice
divergono, vale il codice.

Esempio di riferimento per un'API esterna: `tool/youtube/` (il più recente e pulito). Per una fonte locale: `tool/movie_db/`.
Per un tool di sola lettura molto ampio: `tool/tmdb/`. Ognuno ha peculiarità che **non** vanno copiate (vedi §1).

## Principio obbligatorio: tutte le chiamate HTTP, visibili nel frontend

**Ogni nuovo tool che effettua chiamate HTTP deve esporre nei presenter frontend tutte le chiamate realmente
eseguite, con metodo ed endpoint completo. Le chiavi e gli altri segreti devono essere mascherati prima
dell'esposizione. L'integrazione non è completa finché tracing, payload SSE, presenter frontend e relativi test
non sono verificati end-to-end.** Come si realizza (contratto completo: `AGENTS.md`, «Chiamate HTTP dei tool»):

- Nel punto di `http.py` dove si costruisce l'URL che si invia, registra `session.recorder.record(http_call("GET", url, [segreto]))`
  (`turn.http_call`, `turn.mask_url`): URL reale con path e **tutti** i parametri, solo il valore della credenziale diventa `***`.
  Mai ricostruire l'URL da una descrizione, mai un secondo punto di registrazione, mai una chiamata fatta solo per popolare la traccia.
- La trace porta `calls: [{"method", "url"}]` nell'ordine reale, una voce per OGNI richiesta inviata (le risposte da memo o cache non sono chiamate).
- La vista condivisa usa `presenters/calls_view.call_views` (maschera ancora, idempotente) e terminale e web mostrano `METODO URL` per ogni chiamata.
- Il frontend (`marco-m-netflix`, `src/features/chat/messages/render.js`) ha una funzione di righe per il nuovo `kind` che usa `callLines`.
- Test obbligatori: `tests/test_http_call_trace.py` (aggiungi il tool alla parametrizzazione: ogni richiesta del transport ↔ una voce della trace con lo stesso URL a meno della chiave,
  più chiamate nello stesso turno tutte visibili, credenziali in URL di altro formato e nelle eccezioni del transport mai nell'output) e la verifica del §8 sul frontend renderizzato.

## 0. Vincoli di processo

- Un concern per volta, un commit per concern (messaggi brevi, inglese, minuscolo, senza prefissi). Commit solo se richiesti.
- Il working tree può contenere modifiche altrui: `git add` solo dei file tuoi, mai `-A`.
- Niente chiamate reali (OpenAI/Cohere/TMDb/YouTube), niente lettura di `.env`, nessuna nuova dipendenza o file di tooling senza chiedere.
- Non cambiare il comportamento dei tool esistenti: ogni modifica al core (`orchestrator.py`, `turn.py`, `app.py`) deve essere additiva e coperta da test che passano anche senza il nuovo tool.

## 1. Ispeziona prima di progettare

Leggi, in quest'ordine, e annota per ciascun tool cosa è **convenzione** e cosa **peculiarità**:

1. `orchestrator.py`: `Tool` Protocol (`name`, `description`, `input_schema`, `run(*, query, params, conversation_history) -> dict`), `Enricher`, come `_plan_turn` inserisce il catalogo.
2. `app.py`: `CONFIG` (sezione del tool), `build_app`, `allowed_tools`, `instructions` (regole di routing numerate), `tool_final_instructions`.
3. `turn.py`: `tool_outcome`, `OUTCOME_*`, `STEP_*`, `TOOL_PARAM_TURN_ID`, `TOOL_PARAM_TURN_LANGUAGE`.
4. Un tool completo: `tool/youtube/` (`config`, `settings`, `auth`, `errors`, `http`, `models`, `queries`, `relevance`, `trace`, `tool`).
5. Presenter: `presenters/youtube_view.py`, `presenters/terminal/youtube/`, `presenters/web/youtube/`, `STEP_RENDERERS`, `STEP_SERIALIZERS`, `story_view.TOOLS`.
6. Test: `tests/test_youtube_*.py` + `youtube_support.py`, `tests/test_presenter_parity.py`, `movie_db/harness/evaluation/routing_cases.py`.
7. Impostazioni: `preferences/fields.json` (pubblico), `preferences/behavior.py` (privato: `SOURCE_TOOLS`, `SOURCES_PLANNER`, `SOURCES_ANSWER`), `tests/test_preferences.py`, `web_api/contracts/settings.md` (vedi §2f).

| Convenzione (copiala) | Peculiarità (non copiarla) |
|---|---|
| `config.py` con `extra="forbid"`, **nessun default** (i valori stanno solo in `CONFIG`), pochi campi pubblici; il resto in `settings.py` | TMDb: cache TTL e budget di chiamate con memo; YouTube: nessuna cache (policy dei dati ≤ 30 giorni) |
| `auth.py` unico lettore della chiave; `http.py` unico punto di I/O (test AST) | `quota.py` di YouTube: dipende dalle quote Google |
| Input Pydantic validato **prima** di ogni chiamata; errore = `invalid_request` senza HTTP e senza riportare i valori | `requests` 1–4 di TMDb e `RULES`: servono a un'API con decine di endpoint |
| `result` = `{query, chunks, outcome, metadata, trace}`; `trace` fuori da `metadata` | `movie_db`: LLM parser interno + SQL whitelistato; `chunks` come righe |
| Errori tipizzati con `code`, messaggi sicuri per il prompt | filtro di pertinenza di YouTube (`relevance.py`) |
| Limiti per turno contati su `turn_id`, non sulla run | `tool/tmdb/enrich.py`: serve solo al completamento del RAG |

## 2. Decisioni da prendere (e da scrivere nel messaggio di commit/PR)

**a) Interno o MCP.** Tool interno se l'API serve solo all'orchestratore (caso di TMDb, YouTube, MovieLens): zero
processi, zero dipendenze, il `Tool` Protocol basta, la trace e il budget per turno restano in-process. MCP solo se un
secondo client esterno deve riusare lo stesso server, o l'integrazione esiste già come server mantenuto da terzi. In
quel caso scrivi la giustificazione e chiedi conferma prima di aggiungere dipendenze.

**b) Nuovo tool o nuova operazione.** Se il dominio e la fonte sono già coperti, aggiungi un'operazione
(`TmdbOperation` + `RULES` + `endpoints.py` + handler in `dispatch.py`; oppure `MovieDbOperation` + builder in
`QUERY_BUILDERS`). Nuovo tool solo per fonte, credenziali o politica di quota diverse. Se il tool deve solo
arricchire il risultato di un altro, è un `Enricher` (vedi `tool/tmdb/enrich.py`), non un tool.

**c) Rotta del planner.** Quando va scelto rispetto agli altri? Scrivi la regola di priorità (come la "1b" di
YouTube, inserita senza rinumerare) e i confini: cosa **non** deve prendere (es. i trailer restano a `tmdb_search`).

**d) Cosa decide il codice, cosa l'LLM.** L'LLM compila solo campi tipizzati dello schema e solo con valori presenti
in richiesta o conversazione (`year`, `director`… mai inventati: il campo lo dichiara nella `description`). Query,
URL, SQL, filtri e limiti li costruisce il codice da frammenti costanti (`tool/youtube/queries.py`, `tool/movie_db/sql/queries.py`).

**e) Limiti, quote, dati da non conservare.** Limite per turno su `turn_id` (`_searches_left`, `CallBudget`); chi è
l'autorità sulla quota; cosa non si può memorizzare per i termini dell'API. Le policy esterne vanno nel docstring del modulo.

**f) Quale fonte dell'utente serve questo tool (SEMPRE, non opzionale).** L'utente sceglie nelle impostazioni
"Preferred sources" (`preferences/fields.json`: `reviews`, `interviews`, `official information`, `user ratings`).
Un tool nuovo non è finito finché non è deciso, **con motivazione scritta e verificata sui dati reali** (risposte
registrate o fixture, mai solo la documentazione dell'API), a quale preferenza si aggancia in modo prevalente:
1. **Che tipo di dato porta davvero?** Guarda i campi che arrivano nel risultato: voti degli utenti, testo di
   recensioni (utenti o critica professionale: sono cose diverse e vanno dichiarate come tali), dichiarazioni dirette di
   registi/cast/autori, dati strutturati o enciclopedici. Annota cosa **non** porta.
2. **Quale preferenza serve?** Una sola prevalente (la riga di `SOURCE_TOOLS` in `preferences/behavior.py`); se ne
   serve più d'una, scrivi quale e perché. Se nessuna delle quattro descrive i suoi dati, non forzarla: proponi un
   valore nuovo (`fields.json`, `behavior.py`, test e `web_api/contracts/settings.md`, in un commit a parte).
3. **Sovrapposizioni.** Con quali tool esistenti dà lo stesso tipo di dato? Chi è più affidabile, più aggiornato, più
   costoso (quota, chiamate)? Scrivi la regola di priorità: l'intento della richiesta e le regole numerate di routing
   prevalgono sempre sulla preferenza, che serve solo da criterio secondario tra tool che già servono la richiesta.
4. **Nessuna chiamata in più, salvo eccezione decisa.** La preferenza orienta e mette in evidenza
   (`SOURCES_PLANNER`, `SOURCES_ANSWER`): non aggiunge passi né tool. L'unica eccezione oggi è `interviews`, che per un
   titolo identificato aggiunge un passo `youtube_search` per decisione del proprietario; ogni altra eccezione va
   chiesta e dichiarata nel modulo (`behavior.py`), in `PLANNER_INTRO` e in `AGENTS.md`. Se il nuovo tool ha quote o
   costi, dichiaralo.
5. **Spoiler e tipo di contenuto.** Il tool può restituire trame, finali o recensioni che spoilerano? Copre film, serie
   o entrambi? Va scritto, perché `spoiler_plot` e `content_type` si basano su questo.
6. **Conflitti da testare.** Almeno un caso in cui la preferenza e l'intento esplicito divergono, con l'esito atteso
   (l'intento vince, il limite è detto nella risposta).

Se per questa decisione serve una fonte che oggi non esiste (per esempio recensioni della critica professionale),
non inventarla: segnala all'utente le API o i server MCP gratuiti candidati (licenza, quota, dati, condizioni d'uso
verificati) e proponi un nuovo tool con questa stessa procedura.

## 3. Struttura e responsabilità

### Dove va il codice

Il codice dedicato a un tool **non va più in una cartella nella root**: va in `tool/<nome>/`, un pacchetto annidato
dentro la cartella `tool/` (che contiene già `rag/`, `movie_db/`, `tmdb/`, `wikipedia/`, `youtube/`). Nella root restano
solo le cose che non sono un tool (nucleo, `presenters/`, `web_api/`, `web_lists/`, `tests/`, dati e database).

- Crea `tool/<nome>/__init__.py` (docstring di una riga) e metti lì tutti i file della tabella qui sotto. Gli import
  **dentro** il pacchetto sono relativi (`from .config import ...`); da fuori sono assoluti dalla root
  (`from tool.<nome>.tool import <Nome>Tool`, come fa `app.py`). Niente `sys.path`, niente cartella `<nome>/` in root.
- Un tool importa solo sé stesso: nessun altro tool, nessun presenter o canale (`presenters`, `web_api`, `web_lists`),
  nessun `app`/`orchestrator`. Unico modulo del nucleo ammesso: `turn` (`TraceStep`, `tool_outcome`). Un tool non
  importa mai il proprio `harness/`, e `*/harness/` non è mai importato a runtime.
- Se il tool legge **dati o un database locali**, il dato resta in una cartella separata nella root e il tool sta in
  `tool/<nome>/`: è il caso di `movie_db/` (database, schema, ingestione, valutazioni, `data/`) e `tool/movie_db/` (il
  tool che lo interroga). Il tool può importare dalla root solo ciò che condivide con l'ingestione (`config`, `schema`),
  mai l'`harness`. Lo scrittore del dato (ingestione, build) non appartiene al tool.
- `tests/test_tool_package.py` fa rispettare tutto questo: aggiungi il tuo `<nome>` a `TOOLS` (con la voce in `ENTRY` se
  il file principale non si chiama `tool.py`), e se il tuo codice offline (eval, shim) importa `tool.<nome>` aggiungi
  quel file all'elenco degli importatori ammessi; se il tool tocca un database, estendi anche i controlli di
  `tests/test_movie_db_app.py` (sola lettura, nessun import di `harness`) al nuovo percorso.
- Comandi manuali: `python -m tool.<nome>.harness.live_smoke --live`. Attenzione ai test che scorrono le cartelle dei
  tool con `ROOT / "tool" / "<nome>"` (verifica "solo `http.py` fa I/O", "solo `auth.py` legge la chiave"): puntano lì.

Un file = un concern:

| File | Contenuto | Regola |
|---|---|---|
| `config.py` | modello Pydantic della sezione `CONFIG["<nome>"]` + `load_*_config` | solo il necessario; niente default |
| `settings.py` | costanti interne (URL base, timeout, fattori) | mai nell'LLM né in `CONFIG` |
| `auth.py` | unico lettore della chiave; `repr` mascherato | la chiave non esce da qui verso `http.py` |
| `errors.py` | gerarchia con `code` | messaggi senza URL, chiavi, `error.message` dell'API |
| `http.py` | **unico** I/O; `Transport` iniettabile; allowlist di path | ordine: memo → latch/budget → registrazione → invio; nessun retry |
| `models.py` | input validato, enum chiusi, risultati | `extra="forbid"`, validatori che normalizzano |
| `queries.py` / `normalize` | funzioni **pure** input → parametri/dati | nessun I/O, nessuno stato |
| `relevance.py` / regole | funzioni pure di decisione, con ragione dello scarto | permissive: scarta solo con prove forti |
| `trace.py` | `build_<x>_trace(...)` puro → `[{kind,title,data}]` | solo dati da mostrare; mai chiavi |
| `tool.py` | **solo composizione**: valida → credenziali → I/O → pure → risultato | niente logica di dominio qui dentro |

Non creare cartelle, classi astratte o layer "per il futuro". Dividi un file quando ha due concern, non per lunghezza.

## 4. Stile funzionale

- Funzioni pure per tutto ciò che trasforma dati (`build_search_params`, `prescreen`, `screen`, `verification`, `answer_hints`, `build_youtube_trace`): input espliciti, output nuovo, nessuna mutazione degli argomenti, nessun accesso a `os.environ`/tempo/rete.
- Effetti isolati in pochi punti nominati: rete (`http.py`), ambiente (`auth.py`), stato in memoria (`quota.py`, `_searches_used`). Dipendenze esterne **iniettate** come campi del dataclass (`transport`, `credentials`, `client`): i test le sostituiscono senza `monkeypatch` di moduli.
- Callback solo se serve davvero invertire il controllo (`Transport` per la rete, `TurnObserver` per lo streaming degli step). Non introdurre callback dove basta un valore di ritorno.
- Composizione > ereditarietà: dataclass `kw_only` e funzioni; una classe solo se tiene stato (budget, latch, sessione HTTP).

## 5. Ordine di implementazione (un commit per riga)

1. `tool/<nome>/__init__.py` + `config.py` + `settings.py` + sezione in `CONFIG` + test config (campo mancante/extra = errore) + il `<nome>` in `tests/test_tool_package.py`.
2. `errors.py` + `auth.py` + test (chiave mancante, mai nel `repr`).
3. `models.py` (input/risultati) + test di validazione e di `describe_validation_errors`.
4. Funzioni pure (`queries`, `relevance`/normalizzazione) + test su casi reali tratti dal dominio.
5. `http.py` + test con transport finto (errori mappati dal solo `reason`, nessun retry, test AST "solo `http.py` fa I/O", chiave mai in errori/trace).
6. `trace.py` + `tool.py` (le chiamate si registrano in `http.py`, vedi il principio obbligatorio) + test del contratto del risultato (`outcome`, `metadata`, `trace`, `turn_id`/limiti). Verifica `isinstance(tool, Tool)`.
7. Registrazione: `build_app` + `allowed_tools` + regola di routing in `instructions` + `tool_final_instructions["<nome>"]` (solo per i tool che ne hanno bisogno) + test come `tests/test_youtube_app.py` (registrato, nel catalogo del planner, regola nella posizione giusta, regole finali solo nei turni del tool).
8. Presenter: vista condivisa `presenters/<x>_view.py` (con `calls: list[CallView]` da `calls_view.call_views`, §0); `presenters/terminal/<x>/` (`blocks.py`, `renderer.py`); `presenters/web/<x>/serializer.py`; registrazione in `STEP_RENDERERS` **e** `STEP_SERIALIZERS`; voce in `story_view.TOOLS` (it/en) e `REASONS` se servono nuovi codici; nuovo `STEP_<X>_CALLS` in `turn.py`. Test: parità terminale/web, lingue it/en, nessun import del pacchetto del dominio dai presenter (`tests/test_youtube_presenters.py`).
9. Routing: casi in `routing_cases.py` (con `expected_*` se serve validare gli `arguments`) + test offline in `tests/test_movie_db_routing_eval.py`. **Non eseguire** `--live` senza permesso: consuma crediti. Cambiare lo schema cambia il prompt del planner: dichiara che il routing live è da rieseguire.
10. Preferenze (§2f): riga del tool in `SOURCE_TOOLS` (`preferences/behavior.py`) con la motivazione nel messaggio di commit; se il tool cambia cosa si può dire per una fonte, aggiorna `SOURCES_PLANNER`/`SOURCES_ANSWER` e le regole di routing; `tests/test_preferences.py` verifica che ogni tool di `allowed_tools` sia dichiarato. Aggiungi un test del conflitto tra preferenza e intento esplicito.
11. Documentazione: riga in "Mappa del codice" e sezione del tool in `AGENTS.md`, `README.md`. Comandi di verifica live (smoke) in `tool/<nome>/harness/`, mai importato a runtime. Se sposti o aggiungi file, aggiorna anche `mappa.html` (albero scritto a mano).

## 6. Integrazione con l'orchestratore, senza un secondo orchestratore

Il tool **non** sceglie altri tool, non chiama l'LLM per pianificare, non conosce `history` oltre a quella che gli passa `run`, non stampa. Tutto ciò che è flusso del turno resta in `orchestrator.py`: scelta, ciclo multi-tool, fallback, risposta finale. Il tool riceve `turn_id`/`turn_language` come parametri riservati (`.pop()` prima di validare; mai nello schema LLM), restituisce `outcome` (`ok|empty|error` + `reason`) e `trace`, e basta. Se ti serve completare il risultato di un altro tool usa un `Enricher` registrato in `build_app`, che non riordina `chunks`. Modifiche a `orchestrator.py` ammesse solo se il `Protocol` non basta: motivale e aggiungi un test che dimostra che gli altri tool non cambiano.

Il catalogo del planner contiene `description` e `input_schema` compatto: tienili brevi (`tool.youtube.tool.planner_schema` toglie la docstring già coperta dalla descrizione; ~3.100 caratteri per YouTube, ~11.500 per TMDb sono già molti).

## 7. Sicurezza e privacy (checklist)

- La chiave passa solo da `auth.authorize` → `http.py`; trace, metadata, errori, cache, log: mai. Test che cerca la chiave in tutto l'output.
- URL mostrati: l'URL realmente inviato, registrato in `http.py` con `turn.http_call` (solo il valore della credenziale è `***`, per nome del parametro e per valore noto), mai ricostruito da costanti.
- Errori sollevati fuori da ogni `except` (nessun `__cause__` con l'URL) e solo il `reason` dell'API, mai `error.message`.
- Valori utente nelle query: solo come frasi quotate, senza operatori (`queries.py`).
- Dati mostrati all'utente: quelli dell'API, invariati; l'LLM non li riscrive (URL, titoli, canali vengono dal presenter).
- Cosa non è verificato lo dice il risultato (`verification`, `outcome.reason`, `unverified`), e `final_instructions` vieta di presentarlo come certo.

## 8. Verifiche prima di chiudere

```bash
source .venv/bin/activate
python -m pytest tests/test_query_language.py tests/test_presenters.py tests/test_orchestrator.py \
  tests/test_retrieval.py tests/test_rag_constraints.py tests/test_rerank_query.py \
  tests/test_answer_constraints.py tests/test_movie_db_*.py tests/test_tmdb_*.py \
  tests/test_youtube_*.py tests/test_wikipedia_*.py tests/test_omdb_*.py tests/test_http_call_trace.py tests/test_answer_provenance_rules.py tests/test_story_view.py tests/test_presenter_parity.py \
  tests/test_tool_package.py -q
python -m pytest tests/test_<nuovo>_*.py -q          # i tuoi
python -m movie_db.harness.evaluation.run_eval       # solo offline; mai --live-parser senza permesso
git diff --stat && git diff                           # niente file non voluti, niente .env, nessun print fuori da presenters/terminal
```

**Verifica end-to-end del principio obbligatorio** (obbligatoria per ogni tool con chiamate HTTP): turno reale attraverso `web_api` (LLM scriptato se non si vuole spendere, tool e API reali) → SSE → frontend `marco-m-netflix` renderizzato in un browser;
nel DOM del blocco del passo devono comparire tutte le chiamate (`METODO URL`, parametri compresi) con la chiave come `***` e il valore della chiave non deve comparire in SSE, DOM, log. Non dichiarare il tool concluso con i soli test unitari.

Controlla a mano: la decisione §2f è scritta e motivata (che dato porta, a quale preferenza si aggancia, sovrapposizioni, spoiler, film/serie), non solo una riga in `SOURCE_TOOLS`; il codice sta in `tool/<nome>/`, non nella root; nessun import tra domini; nessun `print`; nessun default duplicato fuori da `CONFIG`; nessuna
modifica ai test dei tool esistenti salvo l'elenco dei tool registrati (es. `tests/test_movie_db_app.py:31`); il test
di parità `STEP_RENDERERS == STEP_SERIALIZERS` passa. Riporta cosa **non** hai verificato (live, routing eval).

## 9. Anti-pattern già evitati

- Un secondo planner dentro il tool, o un tool che ne chiama un altro (usa il ciclo multi-tool).
- Valori hardcoded nei moduli invece di `CONFIG`/`settings.py`; campi di config che non sono limiti reali.
- Importare `tool/tmdb/` da `tool/youtube/` per "riusare" un helper: duplica la funzione minima o spostala solo se due domini la usano davvero.
- Cache o contatori di quota locali quando l'autorità è l'API.
- Fallback silenzioso a `rag_search` quando il tool fallisce: l'esito è `error` e la risposta lo dice.
- Mettere URL, chiavi o liste lunghe in `metadata` (finisce nel prompt): vanno in `trace`.
- Refactoring dei tool esistenti "già che ci sei".
