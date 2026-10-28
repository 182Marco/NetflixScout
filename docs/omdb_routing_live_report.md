# Verifica live del routing OMDb (10 domande) — 2026-10-28

> **Nota (aggiornamento successivo)**: tutto ciò che segue fino alla «Parte 2» è il report originale, con i risultati ottenuti **prima** di qualsiasi correzione, lasciato invariato. Il controllo negativo, le correzioni e le nuove verifiche sono nella «Parte 2» in fondo.

Una sola esecuzione per caso, nessuna ripetizione, nessuna modifica a codice o configurazioni. Campione piccolo e non
deterministico: il report non generalizza oltre queste 10 prove.

## Metodo
- **Sistema reale**: `uvicorn web_api.main:app` (1 worker) con la configurazione del progetto, Qdrant locale
  (`scripts/start_qdrant.sh`, 42.522 punti prima e dopo: nessun punto `tmdb:` scritto), classificatore e planner LLM reali,
  OMDb/TMDb/Wikipedia reali. La chiave OMDb è stata letta solo dall'ambiente del processo e non compare in SSE, log o report.
- **Preferenze**: il driver ha fatto `GET /settings` (campo `preferred_sources`, default `official information`, opzioni
  `reviews | interviews | official information | user ratings`) e ha inviato `preferences: {"preferred_sources": …}` nel corpo
  di ogni `POST /conversations/{id}/messages`, come fa il frontend. Non esiste un interruttore booleano `reviews`:
  «attiva» = `reviews`, «disattivata» = `official information` (il default). Il valore effettivo letto dal backend è nell'evento
  SSE `turn_start.preferences`.
- **Sessione pulita**: una conversazione nuova per domanda, 35 s tra un caso e l'altro. L'SSE grezzo di ogni caso è stato
  salvato (scratchpad della sessione, non versionato).
- **Frontend**: ognuno dei 10 SSE reali è passato dai moduli veri del frontend (`parseSse` → `eventToIntent` → reducer →
  `stepToEntry`, Node 22).

## Riepilogo
**PASS 10 / FAIL 0 / INCONCLUSIVE 0** sui criteri di routing. Parti INCONCLUSIVE (non sui casi): verifica DOM nel browser con le
impostazioni scelte dall'interfaccia (guasto del mio script di automazione, non del prodotto) e prova causale dell'effetto
della preferenza `reviews` (il disegno a 10 casi non ha un controllo negativo).

## I 10 casi
| # | Domanda | `reviews` inviata → letta | Atteso | Effettivo (tool, in ordine) | Chiamate HTTP | Esito |
|---|---|---|---|---|---|---|
| 1 | Metascore of The Godfather (1972) | reviews → reviews | OMDb | `omdb_search` | OMDb 2 | PASS |
| 2 | Oppenheimer (2023) received by professional critics | reviews → reviews | OMDb prioritario | `omdb_search` | OMDb 2 | PASS |
| 3 | Compare IMDb, Metascore, RT of Dune: Part Two (2024) | reviews → reviews | OMDb, solo dati disponibili | `omdb_search` | OMDb 2 | PASS |
| 4 | Shawshank (1994): critics or audiences? | reviews → reviews | OMDb, fonti distinte | `omdb_search` | OMDb 2 | PASS |
| 5 | Rotten Tomatoes score of Parasite (2019) | official information → official information | OMDb comunque | `omdb_search` | OMDb 2 | PASS |
| 6 | IMDb rating of Interstellar (2014) | official information → official information | OMDb comunque | `omdb_search` | OMDb 2 | PASS |
| 7 | Professional reviews of Poor Things (2023), praise/criticism | reviews → reviews | testi ≠ punteggi; OMDb non basta per i testi | `omdb_search`, `wikipedia_search` | OMDb 2 + Wikipedia 2 | PASS |
| 8 | Five recent sci-fi films with excellent reviews | reviews → reviews | OMDb solo se utile, nessuna chiamata per titolo | `tmdb_search` (discover) | TMDb 2, OMDb 0 | PASS (vedi A4) |
| 9 | Best sci-fi films of all time | reviews → reviews | nessun OMDb | `movie_db_search` | 0 (SQL) | PASS |
| 10 | Plot of Arrival (2016) and director | reviews → reviews | nessun OMDb | `tmdb_search` | TMDb 2 | PASS |

Nessun `ignored_preferences`, nessun evento `error`, nessuna risposta bloccata. Durata per turno 6–20 s; ogni richiesta OMDb < 1 s.
Totale: 20 richieste HTTP (OMDb 14 su 1.000/giorno, Wikipedia 2, TMDb 4), nessuna superflua.

## Routing e chiamate HTTP osservate
Tutte le richieste mostrate come nell'SSE (chiave `***`). Casi 1–6: prima la ricerca per titolo, poi il record per IMDb ID.
- Caso 1: `GET https://www.omdbapi.com/?s=The+Godfather&r=json&type=movie&apikey=***` → `GET …/?i=tt0068646&r=json&apikey=***` (The Godfather (1972): IMDb 9.2, Metascore 100, RT 97%).
- Caso 2: `s=Oppenheimer` (senza `type`) → `i=tt15398776` (IMDb 8.2, Metascore 90, RT 93%).
- Caso 3: `s=Dune%3A+Part+Two` → `i=tt15239678` (8.4 / 79 / 92%).
- Caso 4: `s=The+Shawshank+Redemption&type=movie` → `i=tt0111161` (9.3 / 82 / 89%).
- Caso 5: `s=Parasite&type=movie` → `i=tt6751668` (8.5 / 97 / 99%). Caso 6: `s=Interstellar&type=movie` → `i=tt0816692` (8.7 / 74 / 73%).
- Caso 7: OMDb (`s=Poor+Things&type=movie` → `i=tt14230458`: 7.7 / 88 / 92%), poi Wikipedia (`generator=search` e articolo «Poor Things (film)»).
- Caso 8: `GET /3/genre/movie/list` + `GET /3/discover/movie?…sort_by=vote_average.desc…primary_release_date.gte=2020-01-01&with_genres=878…`.
- Caso 9: solo SQL MovieLens (step `db_query`, nessuna chiamata HTTP). Caso 10: `search/movie?query=Arrival&year=2016` → `movie/329865`.

I `tool_selection` con gli argomenti del planner non arrivano al client: il routing è ricostruito da `story`, `answer_end.tools` e dagli step.

## Passaggio delle preferenze: API → planner
- Verificato: `GET /settings` espone `preferred_sources` con default `official information`; il valore inviato in `preferences`
  torna identico in `turn_start.preferences` (10/10, `ignored_preferences` vuoto). Il backend compone il blocco `planner`
  (`SOURCES_PLANNER["reviews"]` → rimando alla regola 1d) per i turni con `reviews`.
- **Non dimostrato**: che la preferenza cambi la scelta del planner. I casi 2 e 4 (critica generica, nessun punteggio nominato) sono
  andati a OMDb con `reviews` attiva, ma non c'è un controllo con `reviews` spenta sulle stesse domande; i casi 5–6 con la
  preferenza spenta sono andati a OMDb per la regola «punteggio nominato», quindi non dicono nulla sull'effetto. Il testo del
  prompt del planner non è registrato dal sistema. Per misurare l'effetto servirebbe almeno la domanda 2 (o 4) con `official information`.
- Frontend con selezione dall'interfaccia: INCONCLUSIVE (vedi sotto).

## Correttezza delle risposte
Per i casi 1–7 ogni numero scritto nella risposta (punteggi, voti, anno) compare nello step `omdb_calls` dello stesso turno: nessun
punteggio inventato, nessuna attribuzione a un film diverso (gli ID identificati coincidono con titolo e anno chiesti). I punteggi
reali di OMDb non sono stati confrontati con una seconda fonte. Nel caso 7 i nomi dei critici e le citazioni (Zacharek, Bradshaw,
Rooney, Lodge, Barber, Dargis, LaSalle, Bastién, Waddington; «virtuoso comic epic», «insanely enjoyable», «monotonal, flat and dull»,
«astonishing performance») compaiono tutti nel testo dell'articolo Wikipedia scaricato alla verifica; la risposta separa il testo delle
recensioni (Wikipedia) dagli aggregati (Metacritic 88, Rotten Tomatoes 92) e dice che questi ultimi non sono testo di recensioni.
Casi 2–4 e 7 distinguono pubblico (IMDb) e critica (Metascore, RT).

## Identificazione e dati mancanti
- 7 su 7 titoli identificati al primo tentativo; nessun `ambiguous`/`unverified`/`not_found`, nessun `N/A`: tutti e tre i punteggi
  erano disponibili in ogni caso, quindi la gestione dei mancanti non è stata esercitata dal vivo.
- Il planner ha usato `type=movie` in 5 richieste su 7 e mai un `imdb_id` nei passi iniziali (corretto: non era noto). L'anno scritto
  nella domanda non compare nell'URL (`year` è controllato solo in locale); non è visibile dall'SSE se il planner l'abbia passato.

## Propagazione SSE e frontend
- Eventi: in ogni turno `turn_start`, `status`, `story`, `step`, `answer_delta`…, `answer_end` (`tools` coerente), `lists` vuota, `done`.
- I 10 SSE reali attraverso i moduli veri del frontend: 10/10 OK — tutte le `calls` (20) renderizzate come `METODO URL` nello stesso ordine,
  nessuna credenziale non mascherata nello stato, risposta mostrata e turno chiuso.
- Verifica nel browser con impostazioni scelte dall'interfaccia: **INCONCLUSIVE**. Lo script di automazione (Chrome headless via DevTools,
  build di scratchpad con la correzione del template `<template v-else>` solo nella copia) è rimasto bloccato prima di aprire il drawer e
  non ha prodotto output; causa non analizzata a fondo, nessun segnale di un problema del prodotto. Una verifica nel browser con dati OMDb
  reali era già stata fatta nella sessione precedente (stesso flusso, domanda diversa, LLM scriptato).

## Anomalie, per gravità
1. **Bassa — formato di Rotten Tomatoes**: nei casi 2, 3, 4, 5 la risposta scrive «93/100%», «92/100%», «89/100%», «99/100%» e nel caso 7 «92/100 on Rotten Tomatoes»,
   mentre OMDb dà una percentuale (`93%`). Il numero è giusto, la scala scritta no. Il tool fornisce `scale: "0-100%"` e la regola finale chiede di riportare «la scala
   ricevuta»: il modello la rende male.
2. **Bassa — confronto tra scale (caso 4)**: la risposta conclude «più alto dal pubblico» confrontando 9,3/10 con 82/100 e 89%, avvertendo che le scale differiscono ma
   concludendo comunque. Non inventa dati, ma il verdetto è una conversione implicita che la regola finale vieta («non convertire scale»).
3. **Bassa — provenienza nominata (caso 8)**: «ordered by TMDb audience rating». `AGENTS.md` dice che il testo finale non nomina il servizio; è un residuo di regole preesistenti (non OMDb).
4. **Informativa — caso 8**: con `reviews` attiva e la richiesta «excellent reviews», il planner non ha usato OMDb (come atteso dal criterio) e ha ordinato per voto del pubblico TMDb
   (≥200 voti, dal 2020). La risposta lo dichiara («audience scores, not critic reviews»), quindi il vincolo di qualità critica non è verificato, solo dichiarato. Candidati recenti trovati
   (inclusi titoli 2026).
5. **Informativa — caso 9**: nella classifica MovieLens compare «I Am So Proud of You» (2008) tra i 10 migliori «sci-fi»: dato del database, non legato a OMDb; routing corretto.
6. **Informativa — osservabilità**: classificazione e argomenti del planner non sono visibili al client né registrati; la decisione si ricostruisce solo da story/step.
7. **Informativa — copertura**: nessun caso con titolo ambiguo, assente, o con punteggi `N/A`; nessuna chiamata a OMDb con `imdb_id` già noto da TMDb; nessun errore API live.

## Raccomandazione
Il routing osservato è **adeguato per i casi di questo campione**: OMDb parte quando la richiesta chiede punteggi o giudizio della critica su un titolo identificato (con e senza `reviews`
quando il dato è nominato), non parte per classifiche, trama/regia e raccomandazioni, e i testi delle recensioni vanno a Wikipedia. Prima di considerarlo affidabile:
1. misurare l'effetto della preferenza con un controllo negativo (stessa domanda generica sulla critica, `reviews` attiva e spenta, più ripetizioni);
2. correggere la resa di Rotten Tomatoes («93%», non «93/100%») e vietare esplicitamente il verdetto tra scale diverse;
3. esercitare dal vivo titoli ambigui («Dune» senza anno), assenti e con `N/A`, e il caso con `imdb_id` già noto;
4. decidere se registrare (non esporre) classificazione e argomenti del planner per poter spiegare una scelta di routing.


---

# Parte 2 — Controllo negativo, correzioni e nuove verifiche (dopo il report originale)

Le prove della Parte 2 sono state eseguite sul sistema reale come nella Parte 1 (stesso backend, planner e API reali, una conversazione
nuova per prova, nessuna cache oltre alle sessioni in memoria del processo). Le prove della sezione 2.1 sono **precedenti** alle correzioni;
quelle della sezione 2.3 sono **successive** (backend riavviato col codice corretto). Qdrant: nessuna scrittura.

## 2.1 Controllo negativo della preferenza `reviews` (codice invariato)
Stesse domande dei casi 2 e 4, cambiando solo `preferred_sources`. Prima di tutto la regola prevista (1d): con `reviews` attiva, una
domanda generica sulla critica va a OMDb; senza, segue le regole 1 e 2 (TMDb), salvo che la richiesta nomini Metascore, Rotten Tomatoes o IMDb.

| Prova | Domanda | `preferred_sources` | Tool | Chiamate HTTP | Risposta (sintesi) |
|---|---|---|---|---|---|
| C2-off | How was Oppenheimer (2023) received by professional critics? | official information | `tmdb_search` | TMDb 2 (`search/movie`, `movie/872585` con recensioni) | «Non si può stabilire come l'abbiano accolto i critici professionisti»: tre recensioni degli utenti TMDb, voto del pubblico 8.0/10 dichiarato non della critica |
| C2-on | stessa | reviews | `omdb_search` | OMDb 2 | Metascore 90/100, Rotten Tomatoes «93/100», IMDb 8.2/10 del pubblico |
| C4-off | Is The Shawshank Redemption (1994) better rated by critics or by audiences? | official information | `omdb_search` | OMDb 2 | IMDb 9.3/10, Metascore 82/100, RT «89/100%»; scale non comparabili ma «molto alto per entrambi» |
| C4-on | stessa | reviews | `omdb_search` | OMDb 2 | IMDb 9.3, Metascore 82, RT «89/100»; «i punteggi favoriscono il pubblico» |

**Conclusione**: la preferenza ha un effetto causale osservabile nella domanda generica (C2: stessa frase, tool diverso, OMDb solo con `reviews`),
esattamente come prevede la regola 1d. Nella C4 non lo ha: la domanda confronta «voti della critica» e «del pubblico», cioè nomina i dati
che OMDb fornisce, e il planner la manda a OMDb in entrambi i casi (coerente con la regola «richiesta che nomina il dato»). Il comportamento
non è errato e non è stato modificato: **nessuna correzione al routing della preferenza**, e le richieste che nominano esplicitamente
IMDb/Metascore/Rotten Tomatoes (casi 3, 5, 6 e C4-off) continuano ad andare a OMDb. Limite: una sola esecuzione per cella; il caso C2-off
mostra anche il costo della scelta di non forzare OMDb: senza la preferenza l'utente non riceve alcun dato della critica professionale.

## 2.2 Correzioni applicate
1. **Rotten Tomatoes** (anomalia 1): ogni punteggio disponibile porta `display` nei metadata (`9.3/10`, `82/100`, `93%`); la regola finale chiede di
   copiarlo e vieta «93/100» per Rotten Tomatoes (`tool/omdb/ratings.py`, `tool_final_instructions["omdb_search"]`).
2. **Confronto tra scale** (anomalia 2): la stessa regola chiede, per un confronto pubblico/critica, fonte, punteggio e scala per ogni voce e vieta di
   dichiarare più alto, migliore, favorito o vincente un valore; se è chiesto un verdetto, spiega che non sono comparabili.
3. **Caso 8** (anomalia 4): eccezione della regola 1d, solo con `reviews` attiva: per raccomandazioni «con ottime recensioni» candidati da
   `tmdb_search`, poi un passo `omdb_search` per ciascuno dei primi cinque (title e year dai risultati TMDb); `CONFIG["omdb"]["max_calls_per_turn"]` 4 → 10;
   la risposta ordina/filtra per critica solo i titoli che hanno il dato e dichiara gli altri; non presenta voti del pubblico come giudizio della critica
   (`SOURCES_PLANNER["reviews"]` rimanda all'eccezione). Con le altre fonti nulla cambia (test).
4. **Ambigui, non trovati, `N/A`** (punto 4): il codice li gestiva già; sono state aggiunte prove dal vivo (2.3) e test di regressione.
Non sono stati toccati: classificatore, orchestratore, altri tool, frontend.

## 2.3 Nuove verifiche dal vivo (dopo le correzioni, una esecuzione per prova)
| Prova | Domanda / `reviews` | Tool e chiamate | Esito |
|---|---|---|---|
| 81 (caso 8) | Recommend five recent science-fiction films with excellent reviews. / attiva | `tmdb_search` (2 richieste) poi 5 × `omdb_search` (10 richieste OMDb, ricerca + record per ciascun titolo: The Wild Robot, Across the Spider-Verse, Evangelion 3.0+1.0, Project Hail Mary, Brand New Day) | PASS parziale: i punteggi critici sono verificati e mostrati per titolo (Metascore/RT con formato corretto), nessun voto del pubblico presentato come critica, avvertenza che le scale non si confrontano. **Residuo**: i cinque candidati restano i primi per voto del pubblico TMDb; la critica non li ha scelti né ordinati (la risposta lo dichiara). 39,8 s |
| 44 (caso 4) | Shawshank: critici o pubblico? / attiva | `omdb_search`, 2 richieste | PASS: IMDb 9.3/10 (scala 0–10) · Metascore 82/100 · Rotten Tomatoes 89% (percentuale), «le scale non sono comparabili, i punteggi non stabiliscono chi l'abbia valutato meglio» |
| 33 (caso 3) | Dune: Part Two (2024), tre punteggi / attiva | `omdb_search`, 2 richieste | PASS: 8.4/10 · 79/100 · 92%, ciascuno con scala e natura |
| 91 | What is the Metascore of Dune? / attiva | `omdb_search`, 1 richiesta (`s=Dune`) | PASS: stato `ambiguous` (Dune 2021, 1984, serie 2000), nessun punteggio, chiede quale; la riga di storia dice «nessun risultato» (vedi residui) |
| 92 | What is the Metascore of Zorblax Quantum Heist (2031)? / attiva | `omdb_search`, 1 richiesta | PASS: `not_found`, «titolo non trovato», nessun dato inventato |
| 93 | What is the Metascore of Manos: The Hands of Fate (1966)? / attiva | `omdb_search`, 2 richieste | PASS: Metascore `not available` (IMDb 1.7/10 e RT 0% disponibili), la risposta dice solo che il Metascore non è disponibile |

Nessun evento `error`; chiave non presente negli URL mostrati (`apikey=***`).

## 2.4 Test
- Nuovi test di regressione: formato `display` (`93%`, `82/100`, `9.3/10`; nessun `display` se non disponibile o illeggibile), testi delle regole finali
  (formato RT, nessun vincitore tra scale, più titoli), eccezione della regola 1d e assenza di OMDb nei testi delle altre fonti, budget di 10 richieste per cinque
  titoli (e `turn_limit` al sesto), titolo senza punteggi e titolo non trovato in un turno a più titoli.
- Suite offline documentata: 1878 passati. `pytest tests` (senza `test_tool_contract.py`): 2247 passati, 22 saltati, 1 fallito
  (`test_qdrant_app_integration`, fallisce anche senza le modifiche di questa sessione).
- Gli esiti del planner reale sono osservazioni su una esecuzione, non test.

## 2.5 Verifica nel browser: causa del blocco
Il test browser inconcludente **non dipende dal prodotto né dalla logica dello script**: un minimo script DevTools (Chrome headless avviato come prima)
riesce a navigare su `about:blank` ma `Page.navigate` verso una pagina statica banale servita da `python -m http.server` su `127.0.0.1` non risponde mai,
nemmeno senza proxy e senza il prodotto. Quindi il blocco avviene in Chrome headless o nell'ambiente macchina, prima di caricare l'app. (Nel mio
script c'era anche un residuo di debug che trattava la domanda come espressione JavaScript; non era la causa del blocco ed è irrilevante per il prodotto.)
Il test con le impostazioni scelte dall'interfaccia resta INCONCLUSIVE; non è stato tentato nessun altro tentativo di correzione.

## 2.6 Stato finale
**Risolti**: formato di Rotten Tomatoes; verdetto tra scale non equivalenti; verifica critica dei candidati in una raccomandazione con `reviews` attiva;
ambigui, non trovati e `N/A` confermati dal vivo; causa causale della preferenza documentata (effetto nella domanda generica, nessun effetto dove il dato è nominato).
**Residui**:
1. Caso 8: la selezione dei candidati resta per voto del pubblico TMDb (OMDb non permette di cercare per punteggio): i film con ottima critica ma voto del pubblico più basso non entrano.
2. Con la preferenza spenta una domanda generica sulla critica non riceve dati della critica professionale (scelta del proprietario, vedi 2.1).
3. La riga di storia per un titolo ambiguo o non verificato dice «nessun risultato» (esito `empty` generico): non è sbagliata nei fatti ma poco precisa; non corretta.
4. «TMDb» nominato nel testo della risposta del caso 8 originale (anomalia 3) non affrontato in questa fase.
5. Osservabilità: classificazione e argomenti del planner ancora non registrati.
6. Verifica nel browser con impostazioni dall'interfaccia: INCONCLUSIVE (ambiente).
7. Un solo campione per prova; costo del caso 8 dopo la correzione: 5 passi di pianificazione e 12 richieste HTTP in circa 40 s.


---

# Parte 3 — Nome dei servizi nel testo (anomalia 3 del report originale)

**Causa**: la regola finale sui filtri TMDb diceva testualmente «i voti sono del pubblico TMDb» e altre istruzioni facevano nominare il servizio («titolo con cui TMDb registra il film»,
«MovieLens non distingue film e serie TV», «proponi di cercarli su YouTube»); il modello le ripeteva (caso 8: «ordered by TMDb audience rating»). I metadata OMDb portavano inoltre `source: "OMDb"` nel prompt.
**Correzione**: tolte quelle formulazioni e il campo `source`; aggiunto in `final_instructions` il divieto esplicito di nominare servizi, siti, provider o database (anche come aggettivo), con i nomi dei punteggi
ammessi solo come nome del punteggio. Routing e budget invariati.
**Interpretazione da confermare**: «Metascore», «Rotten Tomatoes» e «voto IMDb» sono stati lasciati come nomi dei punteggi (l'utente li chiede per nome; senza, pubblico e critica non si distinguono). Se vanno
vietati del tutto, basta togliere quell'eccezione dalla regola.
**Verifica dal vivo (5 turni, una esecuzione, dopo la correzione)**: caso 8 (TMDb + 5 × OMDb): nessun TMDb/OMDb/MovieLens/Wikipedia/YouTube nel testo; «Critics: Metascore 77/100; Rotten Tomatoes 95%. Audience: IMDb 8.2/10»,
formato `display` rispettato; caso 4: pubblico 9.3/10 e critica (Metascore 82/100, Rotten Tomatoes 89%) separati, «le scale non sono comparabili… nessuno può essere dichiarato meglio valutato»; caso 6: «IMDb audience rating of 8.7/10»;
caso 9 (classifica) e raccomandazione senza `reviews` (tmdb): nessun nome di servizio. **Osservazione non correlata**: «Recommend five recent science-fiction films» con `official information` ha restituito titoli annunciati 2028–2031
(ordinamento per data decrescente di TMDb): non corretto qui (fuori dal compito).
**Test**: `tests/test_answer_provenance_rules.py` (6 test sui prompt; non provano il comportamento del modello, osservato solo dal vivo).

---

# Parte 4 — Film futuri nelle richieste «recenti» (osservazione non correlata della Parte 3)

**Problema**: «Recommend five recent science-fiction films.» (con `official information`) restituiva titoli annunciati per il 2028–2031: il planner ordinava per data
di uscita decrescente e `discover_movies` non aveva un limite superiore.
**Correzione** (solo `tool/tmdb`, routing e budget invariati): `discover_*` limita le uscite a oggi (data corrente iniettabile), scarta dai risultati i titoli con data dopo
oggi e, nelle liste per date, quelli senza data; i titoli futuri solo con `include_unreleased` (richiesta esplicita), con inizio domani se manca `year_from`.
**Verifica dal vivo (una esecuzione per prova)**: «five recent science-fiction films» → `discover/movie?…sort_by=primary_release_date.desc&primary_release_date.lte=2026-10-28`,
cinque titoli datati al 28/10/2026, nessuno futuro. «Films announced for the next few years, even if not released yet» → prima della correzione del punto di partenza (prova intermedia) il
planner non impostava un inizio e tornavano film del 1895–1901; dopo (`primary_release_date.gte=2026-10-28` con una versione precedente che iniziava oggi) la lista partiva dalla data
corrente; il codice finale inizia **domani** ed è coperto da test, ma quella ultima modifica non è stata riprovata dal vivo. Nota: con l'ordinamento per data i titoli «recenti» sono quelli
usciti più di recente, non i più noti (i cinque risultati sono poco conosciuti): è la scelta del planner, non modificata.
**Test**: `tests/test_tmdb_released.py` (recenti, futuri espliciti, `year_to` passato/futuro, serie, titoli con data futura o mancante).
