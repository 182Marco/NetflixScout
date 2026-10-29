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
non c'è autenticazione. Wikipedia non richiede nessuna chiave.

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
| `GET /settings` | definizione pubblica delle impostazioni utente (vedi `settings.md`) | `200 {"version", "fields"}` |

Body di `POST …/messages`: `{"content": "testo"}` (non vuoto, al massimo `WEB_API_MAX_MESSAGE_CHARS`) e, facoltativo,
`"preferences": {...}` (le impostazioni correnti: schema, validazione e fallback in `settings.md`). Nessun altro campo.
Un `preferences` sbagliato o incompleto **non** è mai un errore HTTP: i campi non validi usano il default.

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
`preferences` sono le impostazioni applicate a questo turno (con i default dove mancavano o erano invalide);
`ignored_preferences` elenca i campi il cui valore non era valido (vuoto nel caso normale). Il client può usarli
per riallineare la modale. Vedi `settings.md`.
```json event=turn_start
{"conversation_id":"e2c6b0d7663e4af6a8061e24d0e6a544","turn":1,"preferences":{"spoiler_plot":false,"response_length":"medium","response_tone":"technician","approach":"alternatives comparison","content_type":"both","preferred_sources":"official information"},"ignored_preferences":[]}
```

### `status`
Fase di attesa senza passo proprio: `understanding` (analisi della domanda), `answering` (scrittura della risposta).
```json event=status
{"stage":"understanding"}
```

### `story`
Una frase non tecnica, già localizzata nella lingua dell'ultimo messaggio per it/en/de (inglese per ogni altra lingua). `level`: `progress`, `info`, `ok`, `warn` (scegliere l'icona).
Ogni `status` è accompagnato da una `story` di livello `progress`.
```json event=story
{"level":"ok","text":"TMDb: trovato, meno di 1 s","tool":"tmdb_search"}
```

### `step`
Il risultato di un tool, già serializzato per il web; `kind` è `retrieval`, `rerank`, `db_query`, `tmdb_calls`,
`youtube_calls`, `wikipedia_calls`, `omdb_calls`, `tvmaze_calls` o `wikidata_calls`; gli altri campi dipendono dal tipo (sono quelli di
`presenters/web/<tool>/serializer.py`). Un turno può avere **più passi dello stesso tool** (per esempio due
`wikipedia_calls`: prima l'introduzione, poi altre sezioni della pagina): ognuno è un evento `step` a sé.
Un `kind` sconosciuto va mostrato in modo generico o ignorato.
```json event=step
{"kind":"tmdb_calls","title":"CHIAMATE TMDB","calls":[{"label":"Chiamato","method":"GET","url":"https://api.themoviedb.org/3/movie/157336?language=it-IT&api_key=***"}],"attributions":[{"source":"JustWatch","text":"Dati sulla disponibilità in streaming: JustWatch"}]}
```

#### Le chiamate HTTP dei tool (`calls`)
Gli step dei tool che fanno richieste HTTP (`tmdb_calls`, `youtube_calls`, `wikipedia_calls`, `omdb_calls`, `tvmaze_calls`, `wikidata_calls`) hanno tutti
`calls`: una voce per **ogni** richiesta realmente inviata in quel passo, nell'ordine in cui è avvenuta, `{"method","url"}`
(TMDb aggiunge `label`). `url` è l'URL completo (path e tutti i parametri) esattamente come inviato; il backend sostituisce
con `***` solo il **valore** delle credenziali (`apikey=***`, `api_key=***`, `key=***`, anche user:password nell'URL): il
frontend non maschera né ricostruisce nulla. `calls` vuoto = nessuna richiesta in questo passo (dati già in cache). Le
richieste servite da cache o da memo non sono chiamate. Più passi dello stesso tool nello stesso turno sono più eventi
`step`, ciascuno con le proprie `calls`. RAG (Qdrant, SDK) e MovieLens (SQL) non hanno `calls`. Esempio, `omdb_calls`
con una ricerca per titolo e la lettura del record per IMDb ID (oltre a `calls` ci sono `status`, `ratings` e
`candidates`, vedi «Cosa il frontend deve rispettare»):
```json step=omdb_calls
{"kind":"omdb_calls","title":"OMDB","source":"Fonte: OMDb API (uso non commerciale; non affiliata a IMDb)","labels":{"title":"OMDB","source":"Fonte: OMDb API (uso non commerciale; non affiliata a IMDb)","called":"Chiamato","no_calls":"Nessuna chiamata a OMDb in questo turno.","imdb":"IMDb","metascore":"Metascore","rotten_tomatoes":"Rotten Tomatoes","audience":"pubblico","critics":"critica","not_available":"non disponibile","unparsed":"valore non leggibile","votes":"voti","candidates":"Opere con titolo simile","ok":"Punteggi trovati","empty":"Nessun punteggio disponibile per questo titolo","ambiguous":"Più opere corrispondono: nessun punteggio assegnato","unverified":"Titolo non verificato: nessun punteggio assegnato","not_found":"Titolo non trovato","error":"Errore"},"calls":[{"method":"GET","url":"https://www.omdbapi.com/?s=Sample+Movie&r=json&type=movie&apikey=***"},{"method":"GET","url":"https://www.omdbapi.com/?i=tt1000001&r=json&apikey=***"}],"status":"ok","status_label":"Punteggi trovati","reason":null,"work":"Sample Movie (2016)","imdb_id":"tt1000001","ratings":[{"source_label":"IMDb","kind_label":"pubblico","value":"7.9/10","available":true,"votes":"720.000 voti"},{"source_label":"Metascore","kind_label":"critica","value":"81/100","available":true,"votes":null},{"source_label":"Rotten Tomatoes","kind_label":"critica","value":"non disponibile","available":false,"votes":null}],"candidates":[]}
```
`tvmaze_calls` (nessuna chiave: gli URL non hanno nulla da mascherare) con la ricerca per titolo e la lettura della
scheda della serie con cast e prossimo episodio; oltre a `calls` ci sono `source` (con il nome della licenza),
`status`, `show` (`url` della pagina TVmaze), `read`, `license` (`url` della licenza) e `candidates`:
```json step=tvmaze_calls
{"kind":"tvmaze_calls","title":"TVMAZE","source":"Fonte: TVmaze, dati riformulati dall'assistente, licenza CC BY-SA 4.0","labels":{"title":"TVMAZE","source":"Fonte: TVmaze, dati riformulati dall'assistente, licenza {license}","called":"Chiamato","no_calls":"Nessuna chiamata a TVmaze in questo turno.","page":"Pagina della serie","license":"Licenza","read":"Letto","info":"scheda","cast":"cast","seasons":"stagioni","episodes":"episodi","next":"prossimo episodio","candidates":"Serie con titolo simile","ok":"Serie trovata","ambiguous":"Più serie corrispondono: nessun dato assegnato","unverified":"Titolo non verificato: nessun dato assegnato","not_found":"Serie non trovata","error":"Errore"},"calls":[{"method":"GET","url":"https://api.tvmaze.com/search/shows?q=Sample+Show"},{"method":"GET","url":"https://api.tvmaze.com/shows/1?embed%5B%5D=cast&embed%5B%5D=nextepisode"}],"status":"ok","status_label":"Serie trovata","reason":null,"show":{"name":"Sample Show (2016)","url":"https://www.tvmaze.com/shows/1/sample-show","summary":"Running, Sample Net"},"read":["scheda","cast","prossimo episodio"],"license":{"name":"CC BY-SA 4.0","url":"https://creativecommons.org/licenses/by-sa/4.0/"},"candidates":[]}
```

`wikidata_calls` (nessuna chiave) con la ricerca del titolo e la lettura delle relazioni dell'opera identificata; ogni
richiesta SPARQL ha il testo della query dentro l'URL, esattamente come inviata (è lunga: il frontend la mostra intera,
va a capo e non la accorcia né la riscrive). Oltre a `calls` ci sono `source` (con il nome della licenza), `status`,
`work` (`url` della pagina Wikidata), `groups` (relazioni con il link di ogni opera), `candidates`, `partial` (e `partial_label`), `unavailable` e
`license` (`url` della licenza):
```json step=wikidata_calls
{"kind":"wikidata_calls","title":"WIKIDATA","source":"Fonte: Wikidata, dati riformulati dall'assistente, licenza CC0 1.0","labels":{"title":"WIKIDATA","source":"Fonte: Wikidata, dati riformulati dall'assistente, licenza {license}","called":"Chiamato","no_calls":"Nessuna chiamata a Wikidata in questo turno.","license":"Licenza","page":"Pagina","work":"Opera","director":"regia","candidates":"Opere con titolo simile","ok":"Opera identificata","no_relations":"Opera identificata: nessuna relazione registrata","ambiguous":"Più opere corrispondono: nessun dato assegnato","unverified":"Titolo non verificato: nessun dato assegnato","not_found":"Opera non trovata","error":"Errore","unavailable":"Non letto","source_group":"Basata su","derived":"Opere basate su questa","previous":"Precedente nella serie","next":"Successiva nella serie","franchise":"Franchise o serie","more":"altre non mostrate","partial":"Elenco parziale: possono esistere altre opere con questo titolo"},"calls":[{"method":"GET","url":"https://www.wikidata.org/w/api.php?action=wbsearchentities&search=Sample+Film&language=en&type=item&limit=10&format=json"},{"method":"GET","url":"https://query.wikidata.org/sparql?query=SELECT+%3Fo+WHERE+%7B+...+%7D&format=json"}],"status":"ok","status_label":"Opera identificata","reason":null,"operation":"relations","work":{"name":"Sample Film (1982)","url":"https://www.wikidata.org/wiki/Q9000001","summary":"film, IMDb tt9000001, TMDb 9001"},"groups":[{"label":"Basata su","items":[{"text":"Sample Novel (1968, opera letteraria)","url":"https://www.wikidata.org/wiki/Q9000010"}]},{"label":"Opere basate su questa","items":[{"text":"Sample Remake (2017, film)","url":"https://www.wikidata.org/wiki/Q9000011"}]}],"candidates":[],"partial":false,"partial_label":null,"unavailable":[],"license":{"name":"CC0 1.0","url":"https://creativecommons.org/publicdomain/zero/1.0/"}}
```

Lo step `wikipedia_calls` porta le fonti del testo di Wikipedia: `pages[]` (`title`, `language`, `url` pubblico di
Wikipedia, `verification` `confirmed` o `to_verify`, `notes`, `sections` lette, `omitted` = numero di sezioni non lette,
`chars` = caratteri letti sul totale della pagina), `source` (riga di fonte già scritta), `license` (`name` e `url`
della licenza CC BY-SA), `calls` (le richieste inviate in questo passo: vuoto se i dati vengono dalla cache, e allora
`reused` è maggiore di 0), `searches`, `opens` e `hints`. Esempio (in italiano):
```json step=wikipedia_calls
{"kind":"wikipedia_calls","title":"WIKIPEDIA — 1 pagina","source":"Fonte: Wikipedia, testo riformulato e abbreviato, licenza CC BY-SA 4.0","labels":{"title":"WIKIPEDIA","page":"pagina","pages":"pagine","called":"Chiamato","none":"Nessuna chiamata a Wikipedia in questo passo: dati già in cache.","search":"Ricerca","open":"Pagina aperta","received":"ricevuti","kept":"tenuti","dropped":"scartati","error":"errore","notes":"note","sections":"Sezioni lette","omitted":"sezioni non lette","license":"Licenza","to_verify":"Da verificare (pagina non confermata):","no_pages":"Nessuna pagina da mostrare.","specify_year":"Indica l'anno del film per scegliere la pagina giusta.","add_context":"Aggiungi un dettaglio (ruolo, nazionalità, anno) per distinguere le pagine omonime."},"calls":[{"method":"GET","url":"https://it.wikipedia.org/w/api.php?action=query&gsrsearch=%22Park+Chan-wook%22"}],"reused":0,"searches":[{"language":"it","q":"\"Park Chan-wook\"","summary":"3 ricevuti, 2 tenuti; scartati: pagina di disambiguazione 1","error":null}],"opens":[{"language":"it","title":"Park Chan-wook","result":"letta","error":null}],"pages":[{"title":"Park Chan-wook","language":"it","url":"https://it.wikipedia.org/wiki/Park_Chan-wook","verification":"confirmed","notes":[],"sections":["Introduzione","Biografia","Carriera"],"omitted":6,"chars":"5230/18420"}],"license":{"name":"CC BY-SA 4.0","url":"https://creativecommons.org/licenses/by-sa/4.0/"},"hints":[]}
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
`language` è il codice ISO 639-1 (`it`, `en`, `de`, `fr`, …) della lingua dell'**ultimo** messaggio dell'utente, qualunque fosse la lingua dei messaggi precedenti: può cambiare da un turno al successivo. Non è limitato a `it`/`en`: il frontend non deve rifiutare né mappare con un `switch` chiuso i codici sconosciuti. `labels`, `title`, `hints` e `source` degli step e le righe di `story` usano la lingua del turno per `it`, `en` e `de`, inglese per le altre; il testo della risposta, il messaggio di blocco e la domanda di chiarimento sono scritti dal modello nella lingua del turno.

`blocked: true`: domanda non cinematografica, il testo è il messaggio di blocco. `history_compacted` è informativo.
Un turno bloccato emette **solo** `turn_start`, un `answer_delta` con il messaggio, `answer_end` (`tool` null, `tools` vuoto),
`lists` con `lists: []` e `done`: mai `status`, `story` né `step` (nessun tool, nessuna chiamata HTTP, nessun dettaglio di
tracing); la cronologia della conversazione non cambia.

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

- **Chiamate HTTP**: mostrare tutte le `calls` di ogni step, una riga `METODO URL` ciascuna, come ricevute (vedi «Le chiamate
  HTTP dei tool»): non nascondere parametri, non riordinare, non cercare né mostrare la chiave.
- **Attribuzioni**: mostrare le `attributions` (JustWatch) degli step `tmdb_calls` accanto ai dati di streaming. Per i
  video YouTube (step `youtube_calls` e video in `lists`) mostrare titolo, canale e URL esattamente come ricevuti e
  indicare YouTube come fonte. Per le pagine Wikipedia (step `wikipedia_calls`) mostrare titolo, lingua e link di
  ogni pagina, la riga `source` e la licenza (`license.name` con il link `license.url`): il testo è CC BY-SA e chiede
  di accreditare le pagine, indicare la licenza e dire che il testo è stato riformulato. I link vanno aperti in una
  nuova scheda (`target="_blank" rel="noopener noreferrer"`). Per i punteggi OMDb (step `omdb_calls`) mostrare la riga
  `source` e, per ogni elemento di `ratings`, il valore con `kind_label` (pubblico o critica) oppure il testo di
  `value` quando non è disponibile (`available` false): mai un punteggio assente sostituito da un altro. Con
  `status` `ambiguous` o `unverified` mostrare `candidates` e nessun punteggio. Per i dati delle serie TVmaze
  (step `tvmaze_calls`) mostrare la riga `source` (TVmaze come fonte, licenza e riformulazione), il nome della serie
  con il link alla pagina TVmaze (`show.url`), la licenza (`license.name` con il link `license.url`) e `read`; nessuno
  di questi link va costruito dal frontend. Con `status` `ambiguous` o `unverified` mostrare `candidates` e nessun
  dato della serie. Se la serie non è su TVmaze (`not_found`) la risposta può comunque arrivare da un altro passo.
  Campi di `tvmaze_calls`: `status` è uno tra `ok`, `ambiguous` (più serie con quel titolo), `unverified` (solo titoli
  simili), `not_found` ed `error`; `status_label` è il testo già tradotto. `reason` è `null` con `ok`, altrimenti
  il motivo già tradotto (per esempio troppe richieste, tempo scaduto, serie non trovata). `show` è `null` finché la
  serie non è identificata (quindi con `ambiguous`, `unverified`, `not_found`, `error`); altrimenti ha `name`
  (con l'anno), `summary` (stato e rete, come li dà TVmaze, non tradotti) e `url`, che è `null` se la pagina non
  è su `www.tvmaze.com`. `read` elenca cosa è stato letto (scheda, cast, stagioni, episodi, prossimo episodio) e
  resta vuoto senza una serie identificata. `candidates` contiene le alternative (`text`: nome, anno e canale) solo
  con `ambiguous` o `unverified`. `license` (`name` e `url`) è `null` se il link alla licenza non è su `creativecommons.org`: in quel
  caso il frontend non deve costruirlo. `calls` può essere vuoto (turno senza richieste a
  TVmaze, per esempio `invalid_request`): `source` resta comunque da mostrare. Il frontend `marco-m-netflix`
  (`render.js`: `tvmazeLines`, `tvmazeLinks`) mostra queste righe, la fonte e i due link in https; non servono
  altri campi né un trattamento diverso per stato.
  Per le relazioni tra opere (step `wikidata_calls`) mostrare la riga `source` (Wikidata come fonte, licenza e
  riformulazione), il nome dell'opera con il link alla pagina Wikidata (`work.url`), i `groups` (ciascuno con
  `label` e le opere in `items`, ognuna con `text` e, se presente, `url` verso Wikidata) e la licenza (`license.name` con
  il link `license.url`); nessuno di questi link va costruito dal frontend. `status` è uno tra `ok`, `no_relations`
  (opera identificata, nessuna relazione registrata: non prova che non esistano), `ambiguous` (più opere con quel
  titolo), `unverified`, `not_found` ed `error`; con `ambiguous` o `unverified` mostrare `candidates` (`text` con anno,
  tipo, regia e ID IMDb e TMDb) e nessun dato dell'opera. `work` è `null` finché l'opera non è identificata; `summary`
  riporta il tipo e gli ID IMDb e TMDb. `unavailable` elenca ciò che non è stato letto (per esempio il franchise per il
  limite di chiamate); `groups` ha fino a quattro gruppi di relazioni (basata su, opere basate su questa, precedente e
  successiva nella serie) più un gruppo per franchise, con una voce finale «altre non mostrate» quando l'elenco è tagliato. Anche `candidates` ha, quando ne ha omesse, una voce finale «+N altre non mostrate»; `partial` è `true` (con `partial_label` già tradotto, da mostrare) quando le alternative non sono tutte, perché alcune non sono elencate o perché la ricerca era tagliata al limite: serve a distinguere un elenco completo da uno parziale.
  Le relazioni sono quelle registrate su Wikidata: un elenco può essere incompleto. Il frontend `marco-m-netflix`
  (`render.js`: `wikidataLines`, `wikidataLinks`) mostra le righe, la fonte e i link in https.
- Concatenare i `answer_delta` senza riscriverli; applicare `replace` se non è `null`; mostrare `lists` dopo `answer_end`.
- Ignorare gli eventi e i campi sconosciuti (il contratto può aggiungerne) e le righe di commento `:`.
- Un solo messaggio alla volta per conversazione.
- Il testo della risposta è Markdown; la lingua segue l'ultimo messaggio dell'utente (`language` in `answer_end`, codice ISO libero), non la lingua delle fonti: la lingua di una pagina Wikipedia (`pages[].language`, di norma `en`, `it` o `de` per temi locali) non è la lingua della risposta.
