# wikipedia_films — Fase 1: dump di Wikipedia italiana → `films.jsonl`

Pipeline **offline** e indipendente dalla RAG esistente (`tool/rag/`): non è registrata in `app.py`, nessun
modulo del progetto la importa. Scarica il dump di Wikipedia italiana, individua gli articoli sui singoli
film, estrae e pulisce la **trama**, arricchisce i metadati con Wikidata e scrive un record per film in
`data/processed/films.jsonl`.

**Fuori da questa fase** (solo documentato più sotto): chunking, embedding, Qdrant, retrieval.

> **`PROGRESS.md` è il documento di continuità**: stato, decisioni definitive e aperte, vincoli e prossimi passi per riprendere il lavoro. Va letto per primo.

## Stato effettivo (aggiornato il 2026-11-04)

| Fase | Stato |
|---|---|
| Download del dump `20261101` | **completo**, SHA-1 verificato contro quello ufficiale |
| Estrazione | **completa**: 4.154.227 pagine lette, **41.421 film con trama** |
| Arricchimento Wikidata | **completo**: 829 blocchi su 829, 41.421 film, 0 record rifiutati |
| `films.jsonl`, manifest, `verify`, ricostruzione offline a rete bloccata | **completi**: 130.333.071 byte, SHA-256 `684959213d86f0167c4fc08deacc7bda8da1c7504b4726d3b5c094557004949d`, ricostruzione identica byte per byte con 0 richieste di rete |

| Pulizia del catalogo (Fasi 4–7) | **completa**: `data/clean/films.clean.jsonl`, **41.137 film** (284 esclusi, 65 `unverified`, 25 trame corrette), `build_clean verify` OK |
| Collezione Qdrant `wikipedia_films_it_v2` | **creata e verificata**: 41.137 punti (uno per film), `text-embedding-3-large` a 1.536 dimensioni, cosine; `wikipedia_films_it` (v1, 41.438 punti) e `netflix_scout` invariate |
| Integrazione nell'applicazione | **non fatta**. Un solo RAG a regime: il nuovo sostituirà il vecchio (nessun retriever parallelo, nessuna fusione). Piano: `INTEGRATION_PLAN.md`; strategia d'uso: `RAG_USAGE_STRATEGY.md` |

Dettagli, comandi per riprendere e prossime operazioni: `PROGRESS.md`; rapporti di fase: `PHASE2_BENCHMARK.md`, `AUDIT_REPORT.md`, `PHASE5_REPORT.md`, `PHASE6_REPORT.md`, `PHASE7_REPORT.md`, `PHASE8_REPORT.md`. Le cifre misurate sono nella sezione 8.

## Fase 2 (benchmark, concluso) e Fase 3 (embedding e collezione Qdrant, completata)

Il benchmark è in `PHASE2_BENCHMARK.md` (codice in `benchmark/`, dati in `benchmark/results/`, ignorata da git). Le decisioni approvate sono state applicate nella Fase 3: **`text-embedding-3-large` a 1.536 dimensioni** (parametro `dimensions` dell'API), **trama integrale, un vettore per film**, nessuna sintesi LLM, nessun chunking generalizzato. Le sezioni 1–11 qui sotto descrivono la Fase 1 e non sono cambiate. Dettagli e numeri della Fase 3: sezione 12 in fondo a questo file. **Fase 4** (audit di qualità del catalogo e proposta di integrazione, nessuna correzione applicata): sezione 13, `AUDIT_REPORT.md` e `INTEGRATION_PROPOSAL.md`.

## 1. Prerequisiti e installazione

- Python **3.11 o superiore** (il progetto usa il `.venv` 3.11; il codice non usa sintassi 3.12+).
- Dipendenze: `pyyaml`, `mwparserfromhell`, `pydantic` (v2). Le versioni esatte con cui la pipeline è stata
  provata sono in `requirements.lock`; `requirements.txt` dice solo quali pacchetti servono.

```bash
# dalla radice del repository
python3.11 -m venv pipelines/wikipedia_films/.venv        # oppure usa il .venv del progetto e installa i pacchetti
source pipelines/wikipedia_films/.venv/bin/activate
pip install -r pipelines/wikipedia_films/requirements.lock pytest
```

Tutti i comandi si lanciano **dalla radice del repository** come modulo
(`python -m pipelines.wikipedia_films.pipeline ...`). I percorsi dei dati sono relativi a `pipelines/wikipedia_films/`.

Nota: `python -m pytest -q` dalla radice raccoglie anche questi test e richiede `mwparserfromhell`; il comando
di test del progetto (AGENTS.md) elenca invece i file e non li include.

## 2. Comandi

| Fase | Comando | Rete | Output |
|---|---|---|---|
| Download | `python -m pipelines.wikipedia_films.pipeline download` | sì (~4,3 GB) | `data/raw/itwiki-<data>-pages-articles.xml.bz2` |
| Estrazione | `... extract` | no | `data/processed/candidates.jsonl`, `rejected.jsonl` |
| Arricchimento | `... enrich` | solo se `wikidata.mode=online` | `data/processed/films.jsonl` |
| Manifest | `... manifest` | no | `manifests/build_manifest.json` |
| Verifica | `... verify` | no | esito del confronto col manifest |
| Confronto | `... compare A.jsonl B.jsonl` | no | differenze per record e campo |
| Tutto | `... --set wikidata.mode=online --set wikidata.snapshot_id=<id nuovo> run` | sì | download + extract + enrich + manifest |

**`enrich` (e quindi `run`) è offline per default**: senza uno snapshot già presente fallisce con
`SnapshotMiss`. La prima volta serve `--set wikidata.mode=online`, un `wikidata.snapshot_id` nuovo (altrimenti si
scrive nello snapshot `itwiki-20261101-a` di `config.yaml`) e il contatto, vedi sotto.
Le opzioni globali (`--config`, `--set`, `--log-level`) vanno **prima** del nome del comando.

Opzioni globali: `--config FILE`, `--set sezione.chiave=valore` (ripetibile), `--log-level`.
Prima di un'acquisizione online imposta un contatto per lo User-Agent (policy Wikimedia). **Non è nel
repository**: passalo con `--set wikidata.contact=...` o la variabile `RAGWIKI_WIKIDATA_CONTACT`.
Il download e l'estrazione sono **in streaming**: il dump compresso non viene mai decompresso su disco e la
memoria resta limitata. Download e estrazione riprendono dopo un'interruzione (file `.part`, `Range`,
checkpoint); un'interruzione di connessione a metà corpo viene riconosciuta e ripresa.

Prova rapida su un frammento del dump (non è il dump completo; il file `.sample` non viene mai scambiato per
quello vero):

```bash
python -m pipelines.wikipedia_films.pipeline download --max-bytes 80000000
python -m pipelines.wikipedia_films.pipeline extract --dump pipelines/wikipedia_films/data/raw/itwiki-20261101-pages-articles.xml.bz2.sample --allow-truncated
```

## 3. Come funziona

1. **download.py**: URL datato, `.part` + ripresa, verifica SHA-1 contro `itwiki-<data>-sha1sums.txt` ufficiale.
2. **extract_films.py**: `iterparse` sullo stream bz2. Un articolo è un film se ha l'infobox `{{Film}}`
   (oppure una categoria `Film ...`, e allora ha il flag `no_infobox`). Esclusi: redirect, pagine fuori dal
   namespace 0, disambigue, liste e filmografie (prefissi del titolo in `config.yaml`), pagine senza trama.
3. **clean_plot.py**: individua la sezione (Trama, Plot, Sinossi, ... con le sue sottosezioni) e la pulisce
   sul **nodo-albero di `mwparserfromhell`**, non con regex sul markup: via template, `<ref>`, commenti,
   tabelle, immagini, categorie; i wikilink diventano testo; parentesi, ordine e paragrafi sono conservati.
   Trame sotto `min_plot_chars`/`min_plot_words` sono scartate e registrate in `rejected.jsonl`.
4. **enrich_metadata.py**: regista, cast, generi, paesi, lingue, anno, durata, IMDb e titolo originale da
   Wikidata: le entità con `wbgetentities` a blocchi da 50 titoli; le **etichette** (persone, generi, paesi,
   lingue) dal Query Service SPARQL, fino a 1.000 entità per richiesta POST (misurato: ~7 s per 1.000 etichette
   contro ~3 s per 50 con `wbgetentities`, quindi circa 9 volte più veloce); nella query entrano solo QID e codici
   lingua validati. Dove Wikidata manca si usa l'infobox; date e durate segnaposto di Wikidata (per esempio
   `+0001-00-00`) sono ignorate e si ripiega sull'infobox. Dati sconosciuti: `null` o lista vuota, mai inventati.
5. **schema.py**: ogni record è validato (`extra=forbid`, QID, IMDb, data ISO-8601, intervalli plausibili).

## 4. Schema di `films.jsonl`

Un oggetto JSON per riga, chiavi ordinate alfabeticamente, ordinato per `wikipedia_page_id`.

| Campo | Tipo | Significato |
|---|---|---|
| `film_id` | string | QID Wikidata; se manca, `wp-<id pagina>` (stabile) |
| `wikidata_id` | string \| null | QID |
| `wikipedia_page_id` | int | ID pagina itwiki |
| `title` | string | titolo della pagina |
| `original_title` | string \| null | titolo originale (Wikidata P1476, altrimenti infobox) |
| `year` | int \| null | anno di uscita (Wikidata: la data più antica con precisione ≥ anno; altrimenti infobox) |
| `director` | `[{name, wikidata_id}]` | registi (`wikidata_id` null se da infobox) |
| `duration_minutes` | int \| null | durata |
| `actors` | `[{name, wikidata_id, character}]` | cast (al massimo `wikidata.max_actors`) |
| `genres`, `country`, `language` | `[string]` | etichette in italiano, con ripiego sull'inglese |
| `synopsis` | string | trama pulita, paragrafi separati da riga vuota |
| `imdb_id` | string \| null | `tt` + 7–9 cifre |
| `wikipedia_url` | string | URL della pagina |
| `source_revision_id` | string | revisione presente nel dump |
| `retrieved_at` | string | **data del dump** a mezzanotte UTC (`2026-11-01T00:00:00Z`), non l'orologio: vedi §6 |

`rejected.jsonl` e `rejected_records.jsonl` elencano pagine scartate e record non validi con il motivo.

## 5. Licenze e attribuzione

- **Wikipedia**: testo CC BY-SA 4.0 (e GFDL). I dati derivati (trame) restano sotto la stessa licenza:
  conserva `wikipedia_url` e `source_revision_id` per l'attribuzione e indica che il testo è stato modificato.
- **Wikidata**: CC0.
- Le chiamate alle API devono avere uno User-Agent con un contatto (policy Wikimedia); la pipeline rifiuta di
  andare online se `wikidata.contact` è vuoto e rispetta `Retry-After` e `maxlag`.
- Il `.gitignore` di questa cartella (e quello del progetto) esclude `data/`, il manifest della tua build e il
  venv: **dump, snapshot, JSONL, embedding e database vettoriale non
  vanno su GitHub**.

## 6. Riproducibilità completa

Si versionano solo codice, `config.yaml`, `requirements.lock` e i manifest; tutto ciò che è generato si
ricostruisce. Si distinguono due livelli.

### Livello A — riproducibilità esatta
Stesso dump + stesso snapshot Wikidata + stessa `config.yaml` + stesse versioni delle dipendenze ⇒
`films.jsonl` **identico byte per byte**, verificabile con SHA-256.

### Livello B — ricostruzione con nuove acquisizioni
Un nuovo snapshot Wikidata, un altro dump o altre versioni delle librerie possono dare un dataset **diverso**.
Non è un errore: `compare` dice quali record e campi sono cambiati.

### 6.1 Il dump
Usa sempre un dump **datato** (mai `latest`). La data è `dump.date` in `config.yaml` (oggi `20261101`; il
file è `https://dumps.wikimedia.org/itwiki/20261101/itwiki-20261101-pages-articles.xml.bz2`, 4.286.436.387
byte, SHA-1 ufficiale `53d757d92a4f3956880586074008f08a08760641`, letto il 2026-11-03). Il download verifica
lo SHA-1 e registra anche lo SHA-256 in `data/raw/*.info.json`. Wikimedia conserva solo i dump più recenti:
se la data non è più disponibile, cercala in un archivio (per esempio archive.org) con lo stesso nome file e
controlla lo SHA-1 pubblicato; senza lo stesso dump si è nel livello B.

### 6.2 Determinismo di `films.jsonl`
Ordine per `wikipedia_page_id`, JSON canonico (chiavi ordinate, senza spazi), nessuna casualità,
`retrieved_at` derivato dalla data del dump. L'orario reale dell'esecuzione sta solo nel manifest. I test
verificano che due esecuzioni sullo stesso input producano gli stessi byte.

### 6.3 Identità della build: `manifests/build_manifest.json`
Generato da `manifest`: SHA-1/SHA-256 e dimensione del dump, SHA-256 di `config.yaml`, identità
dello snapshot Wikidata, SHA-256 e numero di record di `candidates.jsonl` e `films.jsonl`, conteggi degli
scarti, versioni di Python e dei pacchetti, commit git. Il manifest dei tuoi dati **non è versionato**
(contiene le tue misure); `manifests/build_manifest.example.json` ne mostra la forma, ricavata da un campione
di 80 MB. `verify` ricalcola tutto e segnala ogni differenza (config, dump, snapshot, file, versioni).

### 6.4 Wikidata in modo riproducibile
Lo **snapshot** `data/cache/wikidata/<snapshot_id>/` conserva le **risposte originali complete**
(corpo JSON integrale, compresso gzip, con claim, qualificatori, `lastrevid`, sitelink; SHA-256 del corpo non
compresso) e un indice `requests.jsonl` con i parametri esatti, lo stato HTTP e l'istante di acquisizione. I
metadati dei film sono sempre **derivati** dallo snapshot da funzioni pure: nessun dato già elaborato è fonte
di verità. Lo snapshot contiene due tipi di risposte originali: `wbgetentities` (GET, una per blocco di film) e
SPARQL per le etichette (POST; la chiave della richiesta comprende il testo completo della query). Due modalità (`wikidata.mode`):

- `offline` (predefinita): nessuna rete; una risposta mancante dà un errore esplicito (`SnapshotMiss`).
- `online`: usa lo snapshot se ha la risposta, altrimenti la scarica e la **aggiunge** (rate limit,
  backoff, `Retry-After`, `maxlag`).

Per una nuova acquisizione scegli un `snapshot_id` nuovo (`--set wikidata.snapshot_id=...`): non tocca i vecchi.
Lo snapshot è CC0 e si può condividere fuori da GitHub, ma questo progetto non lo pubblica. **Chi parte da
zero ottiene uno snapshot nuovo** (livello B): Wikidata cambia, quindi il suo `films.jsonl` può differire dal
nostro; per un confronto esatto serve lo stesso snapshot (stesso `content_sha256` nel manifest).

### 6.5 Ricostruire da zero
```bash
git clone <repo> && cd NetflixScout
python3.11 -m venv pipelines/wikipedia_films/.venv && source pipelines/wikipedia_films/.venv/bin/activate
pip install -r pipelines/wikipedia_films/requirements.lock
export RAGWIKI_WIKIDATA_CONTACT="<il tuo contatto: URL o e-mail>"
python -m pipelines.wikipedia_films.pipeline download
python -m pipelines.wikipedia_films.pipeline extract
python -m pipelines.wikipedia_films.pipeline --set wikidata.mode=online --set wikidata.snapshot_id=<id nuovo> enrich
python -m pipelines.wikipedia_films.pipeline manifest
```
Con lo snapshot di qualcun altro, copiato in `data/cache/wikidata/<id>/`, usa `enrich` offline con quell'id e
`verify` contro il suo manifest.

### 6.6 Confronto tra due ricostruzioni
`verify` (build ↔ manifest) e `compare A B` (per record e per campo, `only_in_left/right`). Confronta il
`sha256` di `films.jsonl`; se differisce, `compare` e il `content_sha256` dello snapshot dicono se la causa è
Wikidata, il dump o il codice.

### 6.7 Differenze attese
Wikidata modificato (nuovo snapshot); dump diverso o ritirato; versione di `mwparserfromhell`, Python o
`config.yaml` diversa (la pulizia può cambiare: il manifest le registra e `verify` le segnala); API non
raggiungibile (errore, mai dati parziali silenziosi).

## 7. Embedding e database vettoriale (realizzati nelle Fasi 3 e 7)

Questa sezione descriveva il processo previsto; è stato realizzato e documentato nelle sezioni 12 e 14. Valgono ancora due principi:

- **Verifica di due ricostruzioni**: nessuna metrica decide da sola. Si confrontano (1) l'identità dei testi (hash), (2) l'identità degli ID dei punti, (3) i vettori con coseno e una soglia configurabile (0,9999 è solo indicativa: dipende da modello, versione, provider e batching; riporta anche minimo e percentili), (4) i top-k su query fisse.
- **Differenze attese**: i vettori di un'API non sono garantiti identici nel tempo, un modello aggiornato o ritirato dà vettori diversi (non confrontare modelli diversi), il non-determinismo numerico richiede una tolleranza e non l'uguaglianza. Per questo i vettori verificati si **riusano** (per `film_id` e hash del testo) invece di rigenerarli.

## 8. Spazio su disco e quantità: misure e stime

**Misurato sul dump completo `20261101`** (macchina di sviluppo, un solo processo, 2026-11-03/04):

| Voce | Misura |
|---|---|
| Download | 4.286.436.387 byte in 1.705 s (28 min, ≈ 2,5 MB/s); SHA-1 coincidente con quello ufficiale |
| Estrazione | 4.154.227 pagine in ≈ 34,5 min (con il prefiltro sul testo grezzo) |
| Film con trama (`candidates.jsonl`) | **41.421**, 149.027.467 byte (≈ 3,6 KB/film); trama: mediana 1.263 caratteri, media 2.002, massimo 74.239 |
| Pagine scartate | non film 1.906.750, non articoli 1.024.079, redirect 1.136.691, **trama troppo corta 38.424**, liste/filmografie 3.659, senza sezione trama 3.203 |
| `rejected.jsonl` | 3.489.773 byte (41.627 righe: trama troppo corta e senza sezione) |
| Flag in `candidates.jsonl` | 1.579 senza infobox (categoria `Film ...`), 215 con più sezioni trama |
| Arricchimento (misurato) | 807 blocchi online in 17.642 s (4 h 54 min, 2026-11-04 01:56–06:51), 1.154 richieste di rete; ≈ 22 s a blocco in media, ≈ 5 s nei tratti regolari e sette pause di circa 30 minuti dovute a timeout di rete, recuperate dai retry (502, 429 con `Retry-After`, JSON non valido, timeout, `IncompleteRead`) |
| Snapshot Wikidata (829 blocchi) | 1.676 risposte, 2,30 GB non compressi, 344 MB su disco |
| `films.jsonl` | **41.421 record, 130.333.071 byte (≈ 3,1 KB/film)**, 0 `rejected_records`, 0 `film_id` duplicati |
| Ricostruzione offline | 4 min 53 s, 1.676 risposte dallo snapshot, 0 richieste di rete, file identico byte per byte |

Nota sulle statistiche: dopo l'introduzione del prefiltro le pagine di disambiguazione senza segnali di film
sono contate in `non film` (prima: `disambigue`); l'insieme dei film estratti non cambia (verificato sul
campione: stesso SHA-256 di `candidates.jsonl`).

**Copertura dei metadati sui 41.421 film**: `wikidata_id` 41.395, `year` 41.175, `duration_minutes` 37.797,
`imdb_id` 40.929, `original_title` 38.830, `director` 40.756, `genres` 41.056, `country` 41.349,
`language` 39.227, `actors` 37.392; personaggio presente per 66.612 attori su 358.903. 26 film hanno il
`film_id` di ripiego `wp-<id>` (titolo senza sitelink Wikidata).

**Ancora stimati** (non misurati): embedding futuri (1536 float32 ≈ 6 KB per chunk × numero di chunk) e
database vettoriale.

**Misure del primo campione** (primi 80.000.000 byte del dump, ~1,9%; 19.368 pagine, 108 film, 40 arricchiti)
restano valide come prova di fattibilità ma non sono rappresentative del dump intero: ≈ 5.800 film estrapolati
contro i 41.421 reali.

## 9. Limiti noti

- Il riconoscimento dei film dipende dall'infobox `{{Film}}`; altre infobox (cortometraggi, film TV) sono escluse.
- Soglie sulla trama (400 caratteri, 60 parole) arbitrarie: film con trame brevi sono scartati (`rejected.jsonl`).
- Titoli omonimi: l'associazione a Wikidata usa il titolo esatto della pagina itwiki (sitelink), quindi un
  titolo senza sitelink resta con `film_id` `wp-<id>` e metadati dall'infobox.
- I personaggi del cast sono spesso `null` (Wikidata li registra di rado); le etichette di genere mescolano
  italiano e inglese quando manca la traduzione (esempio: "arthouse science fiction film").
- `year` può differire dall'infobox: Wikidata usa la data più antica registrata.
- Template inline non elencati in `clean_plot.INLINE_TEMPLATES` perdono il loro testo; un `{{spoiler}}` o simili sono scartati.
- Se la sezione trama non esiste ma la trama è nell'introduzione, il film è scartato.
- La durata dall'infobox si legge solo se espressa in minuti (`100 min`).

- **Trame troppo corte**: 38.424 pagine con infobox `{{Film}}` sono scartate perché la sezione trama ha meno di
  400 caratteri o 60 parole (controllo a mano su 8 casi: trame davvero di una o due frasi o sezioni vuote; la
  pulizia non perde testo). Abbassare le soglie in `config.yaml` recupera film con trame brevi ma cambia la build.
- **Date segnaposto di Wikidata**: ignorate (anno fuori da 1850–2100, durata fuori da 1–2000 minuti), ripiego sull'infobox.
- **Prefiltro**: una pagina viene analizzata solo se contiene `{{Film` o una categoria `Film`; un'infobox con un
  nome di template diverso, o con spazi nella categoria (`[[ Categoria:Film`), è esclusa senza essere analizzata.
- **Velocità di Wikidata**: 2–4 s a richiesta anche con connessione persistente; il collo di bottiglia è il server.

## 10. Test

```bash
python -m pytest pipelines/wikipedia_films/tests -q     # offline, nessuna rete
```
Coprono pulizia (markup reale di un articolo e casi limite), classificazione e streaming su un mini dump,
ripresa dopo interruzione, snapshot e replay offline, retry/rate limit, schema, manifest e confronto, e un
download con ripresa su un server HTTP locale.

## 11. Interruzione e ripresa

- **Estrazione**: checkpoint ogni `checkpoint_every_pages` pagine in `data/processed/extract_checkpoint.json`;
  rilanciando lo stesso comando riprende e tronca i file al punto registrato.
- **Arricchimento**: checkpoint dopo ogni blocco di 50 film in `data/processed/enrich_checkpoint.json` (blocchi
  fatti, record scritti, byte dei file, impronta dell'input). Il checkpoint è valido solo per lo stesso
  `candidates.jsonl`, lo stesso `--limit`, lo stesso `snapshot_id`, la stessa dimensione di blocco e la stessa
  `DERIVATION_VERSION` (costante in `enrich_metadata.py`); altrimenti si riparte dal primo blocco, e il costo è
  trascurabile perché i blocchi già acquisiti si leggono dallo snapshot, senza rete (22 blocchi in 3,5 s).
- **Interruzione sicura**: ogni richiesta è registrata nello snapshot prima di essere usata; l'unica perdita
  possibile è il blocco in corso. Per fermare un'esecuzione lunga: prima il ciclo che la rilancia, poi
  `SIGINT` al processo Python quando il checkpoint è appena avanzato (è in attesa della rete, non scrive).
  La procedura è stata provata: dopo l'arresto, stato e snapshot erano coerenti (file `.part` uguale ai byte
  del checkpoint, 0 corpi corrotti, ogni riga dell'indice valida).
- **Ripresa provata**: con rete bloccata e modalità `offline` la ripresa ricostruisce i blocchi acquisiti e si
  ferma alla prima risposta mancante (`SnapshotMiss`, blocco 23), senza modificare i file di stato.

### Ricostruzione offline con rete bloccata (come è stata provata)

Salva come `nonet.py` nella radice del repository (non è versionato) e lancia `python nonet.py`: ogni tentativo
di aprire un socket solleva un errore, quindi un successo prova che non c'è stata rete.

```python
import sys; sys.path.insert(0, ".")
import socket, runpy
def deny(*a, **k): raise RuntimeError("NETWORK ACCESS ATTEMPTED")
socket.socket.connect = deny; socket.create_connection = deny; socket.getaddrinfo = deny
sys.argv = ["pipeline", "--set", "wikidata.mode=offline",
            "--set", "wikidata.snapshot_id=itwiki-20261101-a", "enrich"]
runpy.run_module("pipelines.wikipedia_films.pipeline", run_name="__main__")
```

Il riepilogo stampato deve avere `"network_requests": 0`; poi confronta con `cmp` e `shasum -a 256`.


## 12. Fase 3: embedding completi e collezione Qdrant `wikipedia_films_it`

Codice in `indexing/` (legge solo `data/processed/films.jsonl`; non tocca la pipeline della Fase 1, il suo `config.yaml` né il suo manifest, e non tocca mai la collezione `netflix_scout`: ogni scrittura passa da `settings.assert_own_collection`). Le scelte fisse stanno in `indexing/settings.py`, non in `config.yaml` (cambiarlo cambierebbe lo SHA-256 registrato nel manifest della Fase 1).

**Configurazione**: `text-embedding-3-large`, `dimensions=1536`, un'unità di embedding per film = la trama originale integrale. Eccezione: le **5 trame oltre il limite di 8.191 token** sono divise in chunk di ≈3.000 token (frasi intere, una frase di sovrapposizione), tutti con lo stesso `film_id`: nessuna troncatura. I 5 film sono *Il re leone* (12.069 token, 4 chunk), *Quinto potere* (9.227, 3), *Cinema dell'orrore* (8.355, 3), *Cinema tridimensionale* (11.554, 4), *Attore bambino* (21.896, 8): 22 chunk in tutto, 41.438 unità per 41.421 film. **Nota di qualità sui dati della Fase 1**: tre dei cinque (*Cinema dell'orrore*, *Cinema tridimensionale*, *Attore bambino*, tutti con `year` nullo) sono articoli di argomento e non film; li ho trattati come richiesto, ma sono falsi positivi del riconoscimento per infobox (246 film hanno `year` nullo) e andrebbero esaminati prima di mostrarli come film.

```bash
# dalla radice del repository, con il .venv del progetto (tiktoken: pip install -r pipelines/wikipedia_films/indexing/requirements.txt)
python -m pipelines.wikipedia_films.indexing plan        # unità, token e costo previsto (nessuna rete); si ferma se > 5 USD con `embed`
python -m pipelines.wikipedia_films.indexing embed       # a pagamento; legge OPENAI_API_KEY da .env (mai stampata né salvata)
python -m pipelines.wikipedia_films.indexing verify      # offline: controlli e manifests/embeddings_manifest.json
./scripts/start_qdrant.sh                        # terminale a parte: server Qdrant 1.20.0 su 127.0.0.1:6333 (se non è già acceso)
python -m pipelines.wikipedia_films.indexing index       # crea la collezione e carica i punti (idempotente: upsert con id deterministici)
python -m pipelines.wikipedia_films.indexing index --recreate   # ricostruisce SOLO wikipedia_films_it
python -m pipelines.wikipedia_films.indexing check       # coerenza sorgente ↔ embedding ↔ Qdrant (sola lettura)
python -m pipelines.wikipedia_films.indexing retrieval   # 72 query della Fase 2 sulla collezione completa
python -m pipelines.wikipedia_films.indexing.retrieval_judge   # precisione della top 10 con il giudice della Fase 2 (~0,1 USD)
```

**Ripresa**: gli embedding sono salvati a shard (un file `.npz` per richiesta API, scritto in modo atomico) in `data/embeddings/itwiki-20261101-large1536/shards/` (326 shard, ≤128 testi e ≤120.000 token ciascuno). `embed` rilanciato salta ogni shard presente, leggibile e coerente con il piano (hash di tutti gli id e testi); uno shard corrotto viene richiesto di nuovo, uno con testo sorgente cambiato fa fallire `verify`. Retry con backoff esponenziale su errori transitori, pausa condivisa tra i worker sui rate limit, tetto di spesa (5 USD) controllato prima di ogni richiesta. Ricostruire la collezione da zero non richiede nessuna chiamata API (usa gli shard). Log: `data/embeddings/<run>/embed.log`.

**Collezione Qdrant `wikipedia_films_it`** (stesso server dell'RAG esistente, 1.20.0, stile della collezione `netflix_scout`): vettori 1.536, distanza **coseno** (i vettori dell'API sono già a norma ≈1, il coseno è la metrica del benchmark e quella della collezione esistente; Qdrant li normalizza all'inserimento), HNSW di default (m=16, ef_construct=100), `on_disk_payload`. Id punto = `uuid5(namespace fisso, "<film_id>:<chunk_index>")`. Payload: **l'intero record del film** (titolo, titolo originale, anno, regia, cast con personaggi, generi, paesi, lingue, durata, IMDb, URL Wikipedia, revisione, trama integrale), più `unit_id`, `chunk_index`, `chunk_count`, `chunked`, `chunk_text` (solo i 5 film con più chunk), `title_norm`, `director_names`, `actor_names`. Indici sul payload: `film_id`, `wikipedia_page_id`, `year`, `genres`, `country`, `language`, `director_names`, `imdb_id`, `title_norm`, `chunked`. Ricerca con un risultato per film: `indexing/wiki_search.py` (`search_films` usa le query a gruppi per `film_id`; `get_film` restituisce tutti i chunk). La collezione NON è collegata all'orchestratore né al chatbot.

**Misure reali** (2026-11-04):

| voce | valore |
|---|---|
| film / unità / vettori / punti Qdrant | 41.421 / 41.438 / 41.438 / 41.438 |
| token e costo API | 23.927.168 token (uguali al conteggio locale), **3,1105 USD** (budget 5 USD); `plan` aveva stimato 3,1105 |
| tempo di embedding | 1.810 s (30 min) con 6 richieste in parallelo, 326 richieste, 0 errori finali; 30 retry transitori (connessione e timeout) |
| `verify` | 28 s; norme dei vettori 0,9993–1,0008; nessun NaN, infinito o vettore nullo; nessun id duplicato |
| shard su disco | 257.248.868 byte (246 MB) |
| collezione su disco | 526.448 KB (≈514 MB), stato green, 41.438 vettori indicizzati |
| caricamento in Qdrant | 138 s (upsert a lotti di 256 più costruzione dell'indice) |
| `netflix_scout` dopo il lavoro | invariata: 42.522 punti, 491.112 KB |

**Vettori identici**: 56 film hanno un testo identico a quello di un altro (10 trame condivise da 66 film: remake e adattamenti della stessa opera, per esempio *Senza famiglia* 1913/1925/1934). Sono record distinti della Fase 1 con `film_id` diversi e restano separati.

**Test**: `python -m pytest pipelines/wikipedia_films/tests -q` → 59 passati (42 della Fase 1, 14 offline in `test_indexing.py` con API finta e Qdrant in memoria e su cartella locale, 3 in `test_indexing_server.py` sul server reale, che si saltano se il server o i dati mancano). `check` sul server: 41.438 punti, 41.421 film distinti, 1.536 dimensioni, coseno, tutti gli id uguali al piano, 300 punti campione con vettore e payload uguali alla sorgente, 5 film con tutti i chunk. Retrieval con le 72 query della Fase 2: ristretto al pool di 1.000 film dà gli stessi numeri della Fase 2 (Hit@10 0,708, MRR 0,443 contro 0,442); sul corpus completo Qdrant coincide al 99,7% con la ricerca esatta, nessun duplicato per film nella top 10, **precisione P@5 0,703, P@10 0,650** (Fase 2 sul pool: 0,706 e 0,624) mentre Hit@10 sul film sorgente scende a 0,181 (con 41 volte più film simili il film d'origine è uno tra molti candidati validi). I vettori della Fase 3 (parametro `dimensions`) hanno coseno medio 0,99996 (minimo 0,9977) con quelli della Fase 2 (troncati).


## 13. Fase 4: audit del catalogo (nessuna correzione applicata in quella fase)

Rapporto completo: `AUDIT_REPORT.md`; i 246 record senza anno, classificati uno per uno: `AUDIT_NOYEAR_246.md`; il piano di sostituzione del vecchio RAG (che ha preso il posto della prima proposta di integrazione, eliminata) è `INTEGRATION_PLAN.md`. Codice in `audit/` (sola lettura su `films.jsonl`, snapshot Wikidata, shard e Qdrant). Le note della sezione 12 sulle "false positive" e sui cinque film oltre il limite sono qui spiegate e quantificate; i risultati storici delle Fasi 1–3 non cambiano.

**Esito** (41.421 record; classificazione da dati locali, interpretata): **41.091 film validi** (99,2%), **259 falsi positivi** (181 serie, 57 articoli di argomento, 21 altre opere) e **71 dubbi**. Dei 246 senza anno, 172 non sono film, 63 sì e 11 sono dubbi. Dei cinque film oltre il limite, *Il re leone* e *Quinto potere* sono film con la trama estratta male, gli altri tre (*Cinema dell'orrore*, *Cinema tridimensionale*, *Attore bambino*) non sono film. Difetto della Fase 1 trovato: in 25 pagine (0,06%) `find_plot_section` accorpa alla trama le sezioni sorelle (produzione, accoglienza…); con un taglio corretto i due film grandi entrano interi in un embedding (2.469 e 640 token) e rifare i 25 embedding costa ≈0,0035 $.

```bash
python -m pipelines.wikipedia_films.audit.section_scan   # rilegge il dump locale (~19 min, nessuna rete)
python -m pipelines.wikipedia_films.audit.anomalies
python -m pipelines.wikipedia_films.audit.run_audit      # → audit/exclusions.json, review_needed.json, synopsis_contamination.json, AUDIT_NOYEAR_246.md
python -m pytest pipelines/wikipedia_films/tests/test_audit.py -q
```

## 14. Fasi 5–8: dataset definitivo, collezione v2, strategia d'uso

**Dataset definitivo.** `python -m pipelines.wikipedia_films.audit.reconcile` riconcilia le liste delle Fasi 4–6 e le decisioni approvate in un manifesto per `film_id` (`audit/decisions_manifest.json`, 377 record, un'unica decisione ciascuno) e in `audit/plan_overrides.json`. `python -m pipelines.wikipedia_films.audit.build_clean build|verify` genera, senza toccare `films.jsonl`, in `data/clean/`: `films.clean.jsonl` (**41.137 film**, 131,5 MB), `excluded.jsonl`/`excluded_list.json` (284 esclusi con motivo), `unverified.json` (65), `corrections.json` (25 trame con hash dell'originale), `category_counts.json`, `clean_manifest.json` (SHA-256). Deterministico, offline, reversibile (`verify` ricostruisce byte per byte e controlla che clean + esclusi riproducano `films.jsonl`).

**Collezione.** `python -m pipelines.wikipedia_films.indexing.v2 plan|embed|index|check`: riusa 41.112 vettori verificati e ne calcola 25 (0,003492 USD); crea `wikipedia_films_it_v2` (41.137 punti, indici di payload anche su `catalog_status` e `unverified`); `python -m pipelines.wikipedia_films.indexing.v2_eval` controlla ogni punto contro il suo record e le 72 query di Fase 2. Occupa 536 MiB su disco (v1: 514 MiB): dettaglio nel rapporto di Fase 8.

**Film e serie.** Il catalogo è di film; non c'è un campo «tipo di opera» nel payload. I casi dubbi (65) sono `unverified`; dettagli e proposta (`work_format`) in `RAG_USAGE_STRATEGY.md` sezione 4.

**Benchmark e limiti.** Sulle 72 query la v2 dà Hit@5/Hit@10/MRR@10 = 0,167/0,181/0,106 (v1: 0,153/0,181/0,105): i valori assoluti sono bassi perché il corpus ha 41 volte i distrattori del benchmark di Fase 2 e i giudizi LLM coprono solo il 3% delle top 10. Le query di genere e formato con testo nuovo non sono state rilanciate (richiederebbero embedding a pagamento). Preferenze negative: `indexing/negative.py` e `negative_eval.py` (11 scenari locali, proxy oggettivi, nessun giudice umano né LLM).

**Decisioni ancora non verificate.** 65 record `unverified` (44 dubbi non riesaminati, 8 sospesi, 9 ibridi sospesi, 4 incerti reinseriti); 7 film TV in due serate esclusi come miniserie, ancora da confermare (vedi `PHASE8_REPORT.md`).

**Stato dell'integrazione.** Nessuna. Il vecchio RAG, l'orchestratore, `app.py`, il frontend e `web_api` non sono stati toccati. Il nuovo RAG sostituirà il vecchio senza retriever paralleli né fusioni: `INTEGRATION_PLAN.md` e `RAG_USAGE_STRATEGY.md`.

```bash
python -m pipelines.wikipedia_films.audit.reconcile && python -m pipelines.wikipedia_films.audit.build_clean build && python -m pipelines.wikipedia_films.audit.build_clean verify
python -m pipelines.wikipedia_films.indexing.v2 plan        # embed / index / check solo con autorizzazione e server Qdrant acceso
python -m pipelines.wikipedia_films.indexing.negative_eval  # scenari di preferenze negative, nessuna chiamata API
python -m pytest pipelines/wikipedia_films/tests -q
```
