# NetflixScout — API per il frontend

Contratto effettivamente implementato in `web_api/` (FastAPI + Server-Sent Events). Gli esempi sono
prodotti dal codice reale con un bot finto; i blocchi ` ```json event=<nome> ` sono validati dai test
(`tests/web_api/test_web_api_doc.py`) contro i modelli di `web_api/schemas/events.py`.

## 1. Avvio e configurazione

Dalla **root del repository** (i percorsi dei dati sono relativi alla cartella corrente), con **un solo worker**
(le conversazioni stanno nella memoria del processo):

```bash
source .venv/bin/activate
uvicorn web_api.main:app --reload --host 127.0.0.1 --port 8000
```

All'avvio il server fa gli stessi controlli del terminale: la collection vettoriale e il database MovieLens
devono esistere, altrimenti si ferma con un messaggio operativo. Le chiavi (`OPENAI_API_KEY`, `COHERE_API_KEY`,
`VUE_APP_TMDB_API_KEY`, `YOUTUBE_API_KEY`) stanno nel `.env` del backend: il frontend non invia nessuna chiave e
non c'è autenticazione.

URL base di sviluppo: `http://localhost:8000`. La documentazione OpenAPI della parte REST è su `/docs`.

| Variabile | Default | Significato |
|---|---|---|
| `WEB_API_CORS_ORIGINS` | `http://localhost:8080,http://localhost:5173` | origini ammesse (lista separata da virgole) |
| `WEB_API_CONVERSATION_TTL_SECONDS` | `3600` | una conversazione ferma da più di così viene dimenticata |
| `WEB_API_MAX_CONVERSATIONS` | `200` | oltre questo numero si dimentica la conversazione ferma meno recente |
| `WEB_API_MAX_MESSAGE_CHARS` | `2000` | lunghezza massima di un messaggio |
| `WEB_API_HEARTBEAT_SECONDS` | `15` | pausa di silenzio dopo cui lo stream invia una riga di commento |

CORS ammette `GET`, `POST`, `DELETE` e l'header `Content-Type`.

## 2. Endpoint

| Metodo e percorso | Scopo | Risposta |
|---|---|---|
| `POST /conversations` | apre una conversazione | `201 {"conversation_id", "created_at"}` |
| `POST /conversations/{id}/messages` | invia un messaggio; la risposta è uno **stream SSE** | `200 text/event-stream` |
| `GET /conversations/{id}` | stato della conversazione | `200 {"conversation_id", "busy", "turns_completed"}` |
| `DELETE /conversations/{id}` | chiude la conversazione | `204` |
| `GET /health` | verifica | `200 {"status": "ok"}` |

Body di `POST …/messages`: `{"content": "testo"}` (non vuoto, al massimo `WEB_API_MAX_MESSAGE_CHARS`, nessun altro campo).

Errori HTTP (sempre `{"error": {"code", "message"}}`):

| Stato | `code` | Quando |
|---|---|---|
| 404 | `conversation_not_found` | id sconosciuto o conversazione scaduta |
| 409 | `turn_in_progress` | un messaggio della stessa conversazione è ancora in elaborazione (anche dopo che lo stream è stato chiuso); `DELETE` durante un turno |
| 422 | `invalid_request` | body non valido o `content` vuoto |
| 422 | `message_too_long` | `content` oltre il massimo |

Gli errori **durante** il turno non sono HTTP (lo stream ha già risposto `200`): arrivano come evento `error`.

## 3. Come inviare un messaggio

`EventSource` non può fare `POST`: usare `fetch` e leggere lo stream.

```js
const res = await fetch(`${BASE}/conversations/${id}/messages`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ content }),
});
if (!res.ok) throw (await res.json()).error;           // 404 / 409 / 422
const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
let buffer = "";
for (;;) {
  const { value, done } = await reader.read();
  if (done) break;
  buffer += value;
  let end;
  while ((end = buffer.indexOf("\n\n")) >= 0) {          // un evento = blocco fino alla riga vuota
    const block = buffer.slice(0, end); buffer = buffer.slice(end + 2);
    const event = /^event: (.*)$/m.exec(block)?.[1];
    const data = /^data: (.*)$/m.exec(block)?.[1];        // una sola riga di JSON compatto
    if (event && data) handle(event, JSON.parse(data));   // le righe che iniziano con ":" sono heartbeat
  }
}
```

Per continuare la conversazione si invia il messaggio successivo con lo **stesso** `conversation_id`, dopo che il
precedente è finito (`done` o `error`). La cronologia la tiene il server: il frontend non la rinvia.

## 4. Gli eventi

Ogni evento ha `id:` (intero crescente nel turno, da 1), `event:` e una riga `data:` di JSON.
Non c'è ripresa: `Last-Event-ID` non è supportato.

Ordine di un turno riuscito:

```
turn_start
( status | story | step )*          ← avanzamento live: cosa si cerca, dove, esito
answer_delta+                        ← il testo della risposta, mentre il modello lo scrive
( story )?                           ← solo un avviso, se la risposta è rimasta incompleta
answer_end
lists
done
```

Un turno fallito è `turn_start`, eventuale avanzamento, poi `error`; **dopo `error` non arriva altro** (né `answer_end`,
né `lists`, né `done`). Una riga `: ping` ogni `WEB_API_HEARTBEAT_SECONDS` di silenzio tiene viva la connessione:
va ignorata. Il testo e `lists` sono generati dalla **stessa** chiamata del modello: `lists` arriva sempre
dopo il testo perché si conosce solo a risposta finita.

### `turn_start`
```json event=turn_start
{"conversation_id":"e2c6b0d7663e4af6a8061e24d0e6a544","turn":1}
```

### `status`
Fase di attesa senza passo proprio: `understanding` (analisi della domanda), `answering` (scrittura della risposta).
```json event=status
{"stage":"understanding"}
```

### `story`
Una frase non tecnica, già localizzata (it/en come la domanda). `level`: `progress`, `info`, `ok`, `warn` (scegliere l'icona).
Ogni `status` è accompagnato da una `story` di livello `progress`.
```json event=story
{"level":"ok","text":"TMDb: trovato, meno di 1 s","tool":"tmdb_search"}
```

### `step`
Il risultato di un tool, già serializzato per il web; `kind` è `retrieval`, `rerank`, `db_query`, `tmdb_calls` o
`youtube_calls`; gli altri campi dipendono dal tipo (sono quelli di `presenters/web/<tool>/serializer.py`).
Un `kind` sconosciuto va mostrato in modo generico o ignorato.
```json event=step
{"kind":"tmdb_calls","title":"CHIAMATE TMDB","calls":[{"label":"Chiamato","url":"https://api.themoviedb.org/3/movie/157336?api_key=***"}],"attributions":[{"source":"JustWatch","text":"Dati sulla disponibilità in streaming: JustWatch"}]}
```

### `answer_delta`
Un pezzo di testo (Markdown) **già decodificato**: mai JSON, virgolette di chiusura o sequenze di escape. Si concatenano
nell'ordine in cui arrivano. Un pezzo è un frammento di token, non una parola.
```json event=answer_delta
{"text":"Ti consiglio **Interstel"}
```

### `answer_end`
Chiude il testo. `replace` è `null` nel caso normale: il testo concatenato **è** la risposta. Se è una stringa, è
la risposta completa e **sostituisce** tutto il testo mostrato (succede per testi di ripiego o in casi anomali). Il
confronto lato server ignora solo gli spazi iniziali e finali; il frontend mostra il testo con un `trim()` dei bordi e
non lo altera in altro modo.
```json event=answer_end
{"blocked":false,"language":"it","tool":"tmdb_search","tools":["tmdb_search"],"history_compacted":false,"replace":null}
```
`blocked: true`: domanda non cinematografica, il testo è il messaggio di blocco. `history_compacted` è informativo.

### `lists`
Output strutturato **solo web**: liste tematiche di film, serie e video che la risposta presenta, già verificate contro i
risultati dei tool del turno. Sempre presente; `lists` è `[]` se la risposta non presenta titoli, se il turno è stato
bloccato o se la verifica è fallita. Non ripete il testo della risposta. I campi non identitari possono essere `null`.
```json event=lists
{"lists":[{"list_id":"film-di-nolan","title":"Film di Nolan","kind":"mixed","items":[{"key":"tmdb:movie:157336","id":157336,"media_type":"movie","title":"Interstellar","overview":"Space.","vote_average":8.4,"release_date":"2014-11-05","original_language":"en","poster_path":"/gEU2.jpg","youtube_key":null,"reason":"Spazio.","links":[{"label":"TMDb","url":"https://www.themoviedb.org/movie/157336"}],"attribution":"JustWatch"}]}]}
```

### `done`
Fine del turno riuscito: la cronologia è stata registrata e la conversazione accetta un nuovo messaggio.
```json event=done
{}
```

### `error`
Il turno è fallito; `code` è `turn_failed` o `internal_error`. La cronologia **non** è cambiata: lo stesso messaggio può essere
rinviato. Il messaggio è generico (nessun dettaglio interno).
```json event=error
{"code":"turn_failed","message":"The turn failed; try again."}
```

## 5. Chiusura della connessione e retry

- Se il client chiude lo stream, **il turno prosegue fino alla fine sul server** e, se termina correttamente, la sua
  cronologia viene registrata: il contesto non si perde. Finché dura, la conversazione risulta `busy` e un nuovo messaggio
  riceve `409 turn_in_progress`.
- Dopo una disconnessione usare `GET /conversations/{id}`: se `busy` è `true` il lavoro è ancora in corso, quando torna
  `false` confrontare `turns_completed` con il valore precedente. Se è aumentato il messaggio è stato elaborato (e il suo
  testo, per ora, non è recuperabile): non reinviarlo.
- Dopo `error` la cronologia è invariata e il messaggio si può rinviare.
- Non esiste la cancellazione di un turno in corso.
- Una conversazione non usata per `WEB_API_CONVERSATION_TTL_SECONDS` viene dimenticata: un `404` richiede di aprirne una nuova.

## 6. Cosa il frontend deve rispettare

- **Attribuzioni**: mostrare le `attributions` (JustWatch) degli step `tmdb_calls` accanto ai dati di streaming. Per i
  video YouTube (step `youtube_calls` e video in `lists`) mostrare titolo, canale e URL esattamente come ricevuti e
  indicare YouTube come fonte.
- Concatenare i `answer_delta` senza riscriverli; applicare `replace` se non è `null`; mostrare `lists` dopo `answer_end`.
- Ignorare gli eventi e i campi sconosciuti (il contratto può aggiungerne) e le righe di commento `:`.
- Un solo messaggio alla volta per conversazione.
- Il testo della risposta è Markdown; la lingua segue la domanda (`language` in `answer_end`).
