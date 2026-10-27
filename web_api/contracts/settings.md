# NetflixScout — Impostazioni utente (contratto frontend)

Le impostazioni personalizzano il comportamento del bot **per ogni messaggio**. Il frontend non conosce le
istruzioni interne: riceve dal backend solo ciò che serve a disegnare la modale e invia i valori correnti insieme alla
domanda. Gli altri endpoint e gli eventi SSE sono in `chat_stream.md`.

Fonte unica: `preferences/fields.json` (servito così com'è da `GET /settings`). Non copiare opzioni o default nel
frontend: leggerli dalla risposta.

## 1. Quando chiamare cosa

1. **All'apertura della schermata chat**: `GET /settings` (una volta). Costruire la modale **mentre è nascosta**
   (`display: none`) con i campi, le opzioni e i default ricevuti.
2. **A ogni invio di messaggio**: `POST /conversations/{id}/messages` con `content` e `preferences` (i valori
   correnti della modale). Il backend li applica a quel turno, senza riavvii; non vengono salvati nella conversazione,
   quindi ogni messaggio può avere scelte diverse.

## 2. `GET /settings`

`200`, nessun parametro, nessuna autenticazione. I campi a scelta multipla (`type: "choice"`) vanno mostrati come
segmenti affiancati; `boolean` come interruttore. `label` e `options[].label` hanno cinque lingue: `en`, `it`, `es`, `de`, `fr` (`en` sempre presente, da usare come
ripiego). Il client sceglie la lingua da solo: l'endpoint non prende parametri né header e manda sempre tutte le
lingue, quindi cambiare lingua aggiorna il form senza nuove richieste.

```json settings
{
  "version": 1,
  "fields": [
    {"id": "spoiler_plot", "type": "boolean", "default": false,
     "label": {"en": "Plot spoilers", "it": "Spoiler sulla trama", "es": "Spoilers de la trama",
               "de": "Handlungs-Spoiler", "fr": "Spoilers de l'intrigue"}},
    {"id": "response_length", "type": "choice", "default": "medium",
     "label": {"en": "Response length", "it": "Lunghezza della risposta", "es": "Longitud de la respuesta",
               "de": "Länge der Antwort", "fr": "Longueur de la réponse"},
     "options": [
       {"value": "in-depth", "label": {"en": "In-depth", "it": "Approfondita", "es": "Detallada",
                                       "de": "Ausführlich", "fr": "Approfondie"}},
       {"value": "medium", "label": {"en": "Medium", "it": "Media", "es": "Media",
                                     "de": "Mittel", "fr": "Moyenne"}},
       {"value": "short", "label": {"en": "Short", "it": "Breve", "es": "Breve",
                                    "de": "Kurz", "fr": "Courte"}}
     ]}
  ]
}
```

Le etichette del tono `Homie` sono `Homie` (en), `Bro` (it), `Tío` (es), `Digga` (de), `Gars` (fr); il `value` resta `"Homie"`.
L'esempio è abbreviato: la risposta reale ha **sei** campi (`spoiler_plot`, `response_length`, `response_tone`,
`approach`, `content_type`, `preferred_sources`). I valori (`value`) sono quelli da rimandare, esattamente come
ricevuti (maiuscole e spazi inclusi, per esempio `"Homie"`, `"direct advice"`).

| Campo | Tipo | Valori | Default |
|---|---|---|---|
| `spoiler_plot` | boolean | `true`, `false` | `false` |
| `response_length` | choice | `in-depth`, `medium`, `short` | `medium` |
| `response_tone` | choice | `technician`, `Homie` | `technician` |
| `approach` | choice | `direct advice`, `alternatives comparison` | `alternatives comparison` |
| `content_type` | choice | `film`, `series`, `both` | `both` |
| `preferred_sources` | choice | `reviews`, `interviews`, `official information`, `user ratings` | `official information` |

La tabella è solo per leggere: la fonte è la risposta di `GET /settings`. Un campo o un valore **sconosciuto** al
frontend va ignorato (il contratto può crescere; `version` cambia solo per modifiche incompatibili).

**Errore di caricamento.** Se `GET /settings` fallisce, la chat deve restare usabile: non mostrare campi, inviare i
messaggi **senza** `preferences` (si applicano tutti i default) e offrire un "riprova". Non inventare uno schema locale.

## 3. Invio dei messaggi

```json
POST /conversations/e2c6b0d7663e4af6a8061e24d0e6a544/messages
{
  "content": "Consigliami un thriller psicologico",
  "preferences": {
    "spoiler_plot": false,
    "response_length": "short",
    "response_tone": "Homie",
    "approach": "direct advice",
    "content_type": "film",
    "preferred_sources": "user ratings"
  }
}
```

`preferences` è **facoltativo**: un client che non lo invia funziona come prima, con tutti i default. Si possono
inviare solo alcuni campi: gli altri usano il default.

## 4. Validazione e fallback (backend)

Il backend valida sempre, indipendentemente dal frontend:

| Caso | Effetto |
|---|---|
| `preferences` assente o `null` | tutti i default |
| `preferences` non è un oggetto (stringa, lista…) | tutti i default |
| campo mancante | default di quel campo |
| tipo errato (`"true"` invece di `true`, numero, `null`) | default di quel campo |
| valore non ammesso (`"loud"`, o `"homie"` con la `h` minuscola) | default di quel campo |
| chiave sconosciuta | ignorata |

Gli altri campi validi restano applicati. Ogni fallback è registrato nel log del server (campo e motivo) e **non**
interrompe la richiesta. Le classi di errore restano distinte:

| Classe | Come la vede il client |
|---|---|
| Preferenze non valide | nessun errore: si usa il default; il campo compare in `ignored_preferences` di `turn_start` |
| Richiesta strutturale non valida (body non JSON, `content` vuoto o troppo lungo, campo extra a livello di body) | HTTP 422 `invalid_request` / `message_too_long` |
| Errore interno del bot | evento SSE `error` |

## 5. Effetto sul flusso SSE e sulla conversazione

- Gli eventi non cambiano. `turn_start` ha due campi in più: `preferences` (le impostazioni applicate) e
  `ignored_preferences` (i campi caduti sul default): usarli per riallineare la modale se non coincidono con ciò
  che l'utente ha scelto.
- La cronologia contiene le risposte dei turni precedenti, scritte con le impostazioni di allora: ogni turno applica
  solo quelle del proprio messaggio.
- Le impostazioni orientano la scelta tra tool già adatti e la forma della risposta e non aggiungono chiamate, tranne
  `preferred_sources: "interviews"`: per un film o una serie identificati da un titolo il bot cerca anche i video di
  interviste su YouTube, e i video compaiono nell'evento `lists` (e negli eventi `step` `youtube_calls`) come per ogni
  altra ricerca di video. Il turno dura quindi un passo in più e consuma ricerche YouTube.
- Gli spoiler disattivati sono una richiesta al modello, non un filtro sui dati: se l'utente chiede esplicitamente uno
  spoiler, la risposta non lo rivela e dice che la richiesta contraddice l'impostazione.
- Il tono non si applica ai messaggi fissi (domanda di chiarimento, blocco di una domanda non cinematografica, testo
  di ripiego), che restano neutri.

## 6. Dati pubblici e configurazione interna

`GET /settings` restituisce solo `fields.json`: id, tipo, opzioni, etichette, default. Le istruzioni che il backend
associa a ogni scelta non escono mai dal server e il frontend non deve cercare di riprodurle.
