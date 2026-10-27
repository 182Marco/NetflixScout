# Passaggio al front-end: lingua dell'ultimo messaggio

Riassunto della **differenza** su ciò che il backend FastAPI invia dopo il cambio di lingua. Non è un
secondo contratto: la fonte resta `web_api/contracts/chat_stream.md` (già aggiornato). Gli esempi sono
reali: stessi turni serializzati con il codice precedente (`HEAD` prima della modifica) e con quello nuovo,
passando dalla vera app FastAPI con un orchestratore finto (nessuna rete, nessuna chiamata LLM).

## 1. Cosa NON cambia
- Rotte, metodi e codici d'errore (`{"error":{"code","message"}}`).
- Nomi, ordine e forma degli eventi SSE: `turn_start`, `status`, `story`, `step`, `answer_delta`, `answer_end`, `lists`, `done`, `error`.
- `turn_start.preferences` / `ignored_preferences`, `GET /settings`, `fields.json` (etichette UI it/en delle impostazioni).
- Formato di `lists`, `story[].level`, `step.kind`, chiavi dei payload degli step.
- I messaggi d'errore HTTP (`routes/errors.py`, `streaming/runner.py`) restano in inglese fisso e **non** seguono la lingua del turno.

## 2. Cosa cambia in ciò che viene inviato

### 2.1 `answer_end.language` (e `language` del payload del turno)
Prima: solo `"it"` o `"en"` (ogni altra lingua arrivava come `"en"`). Ora: **codice ISO 639-1 della lingua
dell'ultimo messaggio dell'utente**, qualunque (`"de"`, `"fr"`, `"ja"`, …). Non è mai `null`. Può cambiare
da un messaggio all'altro della stessa conversazione: la history non decide la lingua.

```json
// prima (messaggio tedesco)           // dopo
{"blocked":false,"language":"en",...}  {"blocked":false,"language":"de","tool":"tmdb_search","tools":["tmdb_search"],"history_compacted":false,"replace":null}
```
Per i codici fuori da `it`, `en`, `de` (es. `fr`) `language` è il codice vero, ma i testi fissi del server sono in inglese (vedi 2.2).

### 2.2 Testi fissi generati dal server
Sono nella lingua del turno per **`it`, `en`, `de`**; per ogni altra lingua in **inglese**.
Riguarda: righe di `story`, `title`/`labels`/`hints`/`source`/`label`/`kind_label`/`attributions[].text`
degli step `tmdb_calls`, `youtube_calls`, `wikipedia_calls`, e i titoli degli step `retrieval`/`rerank`
(prima solo italiani, ora it/en/de).

```json
// story, messaggio tedesco
prima: ["Understanding the question…","Searching on TMDb: …","TMDb: found, under 1 s"]
dopo : ["Ich verstehe die Frage…","Ich suche auf TMDb: …","TMDb: gefunden, unter 1 s"]
// step tmdb_calls
prima: {"kind":"tmdb_calls","title":"TMDB CALLS","calls":[{"label":"Called","url":"…"}],"attributions":[{"source":"JustWatch","text":"Streaming availability data: JustWatch"}]}
dopo : {"kind":"tmdb_calls","title":"TMDB-ANFRAGEN","calls":[{"label":"Aufgerufen","url":"…"}],"attributions":[{"source":"JustWatch","text":"Daten zur Streaming-Verfügbarkeit: JustWatch"}]}
// step youtube_calls: labels{…} e kind_label tradotti ("director interviews" → "Interviews mit der Regie")
// messaggio francese: story e step identici a prima (inglese), solo language è "fr"
// retrieval/rerank, titolo: "WEITES K — 3 CHUNKS ABGERUFEN" (de), "WIDE K — 3 CHUNKS RETRIEVED" (en/altre), "K LARGO — 3 CHUNK RECUPERATI" (it)
```
Dati che il server NON traduce: titoli di film/video, nome del canale, nomi propri, `url`, testo di `lists`.

### 2.3 Testi liberi: risposta, blocco, chiarimento, ripiego
Scritti **nella lingua dell'ultimo messaggio** (per qualsiasi lingua il modello capisca):
- risposta (`answer_delta`), con un'istruzione esplicita al modello; titoli originali e nomi propri invariati;
- domanda di chiarimento (arriva come `answer_delta`, nessuna chiamata finale);
- messaggio di blocco non cinematografico (`blocked: true`): lo scrive il classificatore; se manca, testo fisso
  it/en/de (altre lingue: inglese). Esempio reale (messaggio tedesco, nessun testo dal classificatore):
  prima `"I do not answer non-film questions"` con `language:"en"`, dopo `"Ich beantworte keine Fragen, die nichts mit Film zu tun haben"` con `language:"de"`;
- testo di ripiego quando la risposta fallisce (`answer_end.replace` o delta): fisso it/en/de, altre lingue inglese.
Il campo `reason` di `lists[].items` è anch'esso nella lingua della risposta.

### 2.4 Wikipedia (step `wikipedia_calls`)
L'edizione letta è **inglese per default**, qualunque sia la lingua dell'utente. Solo per un tema molto locale
(opera o persona legata a un Paese) il planner può scegliere l'edizione `it` o `de` (nuova: `de.wikipedia.org`):
decide il **Paese del tema**, mai la lingua dell'utente. Quindi `pages[].language` e il host di `pages[].url`
possono essere `en`, `it` o `de` e **non indicano la lingua della risposta**. Etichette e licenza dello step
seguono la lingua del turno. Il testo della pagina viene sempre riformulato nella lingua della risposta.

### 2.5 Dati TMDb
Per un turno tedesco i dati localizzati (titoli, trame, nomi dei provider) arrivano in `de-DE` (prima `en-US`);
`it` resta `it-IT`; ogni altra lingua `en-US`. La regione dei provider di streaming resta `IT` (non dipende dalla lingua).

## 3. Cosa deve decidere il front-end
- Non usare `language` in un `switch` chiuso né rifiutare valori sconosciuti: tipo `string`, ammetti qualunque codice ISO.
- Se mostra il nome della lingua: `new Intl.DisplayNames([uiLocale], {type:"language"}).of(language)`.
- Lingua delle **proprie** stringhe statiche (pulsanti, placeholder): del browser/utente o dell'ultima risposta? Decisione sua.
- Mix visibile possibile: risposta in francese con etichette degli step in inglese (lingue senza tabella). Valutare se mostrare/nascondere le etichette tecniche.
- Scritture non latine e RTL (ja, ar, he…): il server non garantisce nulla, solo il codice e il testo UTF-8 del modello. Font e `dir="auto"` sul contenitore della risposta.
- Un utente che cambia lingua a metà conversazione vedrà etichette e risposta cambiare lingua da un turno all'altro: nessuna ricarica della conversazione necessaria.

## 4. Garanzie e limiti da dichiarare
- `language` è la lingua rilevata dal classificatore sull'ultimo messaggio, con ripiego deterministico (marcatori it/en, poi `en`); su messaggi brevi o solo titoli ("Parasite") è meno affidabile: in quel caso il modello segue l'ultimo messaggio utente precedente, o `en` se il rilevamento fallisce.
- Che il modello **scriva davvero** nella lingua indicata è un comportamento del modello, non una garanzia del server (da osservare dal vivo).
- Le etichette fisse esistono solo in it/en/de; aggiungere una lingua richiede una colonna nelle tabelle del backend (`presenters/*_view.py`, `presenters/terminal/texts.py`, `orchestrator.py`).

## 5. Checklist di compatibilità lato front-end
1. `answer_end.language` trattato come stringa libera (nessun errore su `de`, `fr`, `ja`, né su un codice mai visto).
2. Risposta in una lingua diversa dalle etichette (es. `fr` con etichette inglesi) mostrata senza errori.
3. Cambio lingua a metà conversazione (it → de → en → fr): ogni turno usa la propria `language`.
4. Blocco non-cinema in tedesco: testo in `answer_delta`, `blocked: true`, `lists: []`.
5. Chiarimento in tedesco: solo `answer_delta`, nessun evento `step`.
6. Step `tmdb_calls` / `youtube_calls` / `wikipedia_calls` / `retrieval` / `rerank` con `labels` e `title` tedeschi.
7. Pagina Wikipedia `en` per una domanda in italiano/tedesco; pagina `it` o `de` per un tema locale: nessuna deduzione della lingua della risposta dalla lingua della pagina.
8. Eventuali tipi TypeScript: `language: string` (non `"it" | "en"`).

## 6. File di contratto modificati
`web_api/contracts/chat_stream.md` (descrizione di `story`, `answer_end`, regola sulla lingua), `web_api/schemas/events.py`
(`AnswerEnd.language: str`), `presenters/web/payload.py` (docstring del payload). `settings.md` e `fields.json` invariati.

## 7. Come sono stati generati gli esempi
Script offline (nessuna rete, orchestratore finto): stessi 4 turni (it, de, fr, blocco in de) serializzati con
`git archive HEAD` prima della modifica e con l'albero modificato, via `TestClient` di FastAPI e `parse_sse`.
Gli unici campi diversi sono quelli elencati sopra (più `conversation_id`, casuale).
