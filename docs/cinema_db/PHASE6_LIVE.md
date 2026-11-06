# Valutazione live della Fase 6: l'applicazione reale con `cinema_sql` spento e acceso

Generata da `python -m cinema_db.harness.tool_eval.run_live` con il **planner, il classificatore, i tool e il modello di risposta reali** (OpenAI, TMDb, OMDb, YouTube, Wikipedia, TVmaze, Wikidata): ogni domanda è eseguita due volte, con il flag spento (come prima della fase) e acceso. Nessun embedding: `rag_search` è tolto dai tool ammessi e le due domande che lo userebbero (B24, B25) non sono eseguite. **Misurato**: tool chiamati, richieste HTTP realmente inviate (le `calls` di ogni passo dei tool), query SQL, secondi. **Controllo dei fatti**: parole chiave che devono comparire nella risposta (da database e dalla mia conoscenza), controllo meccanico. **Giudizio**: un secondo modello (`gpt-5.5`, diverso da quello che risponde) confronta alla cieca le due risposte. **Lettura manuale**: la mia, dopo aver letto le risposte. Sono quattro cose diverse e restano separate.

Limiti: una sola esecuzione per domanda e modalità (il planner è stocastico: un'altra esecuzione può scegliere altro); i tempi dipendono dalla rete e dalle API del momento; le richieste HTTP interne del controllo del tipo di opera di MovieLens non sono nelle `calls`; il giudice usa la propria conoscenza e può sbagliare.

## 1. Totali (misurati)

| | Flag spento | Flag acceso | Differenza |
|---|---|---|---|
| Domande | 47 | 47 | |
| Richieste HTTP | 104 | 56 | -48 |
| Passi di tool (tool_selection) | 64 | 66 | +2 |
| Query SQL locali | 0 | 98 | +98 |
| Tempo totale (s) | 524.3 | 482.5 | -41.8 |

`cinema_sql` è stato scelto dal planner in **31** domande su 47. Fatti attesi presenti: spento 19 (assenti 10), acceso 26 (assenti 3). Giudice (a ciechi): {'on': 23, 'tie': 14, 'off': 10}.

## 1b. Prima esecuzione completa e correzioni

La prima esecuzione completa (flag acceso) ha mostrato tre difetti di integrazione, corretti subito (commit «fix what the live evaluation found»): (1) `awards` rifiutava un titolo o una persona insieme a un nome di premio («quanti Oscar ha vinto X»: il planner li dà insieme) e la risposta diceva solo «richiesta non riuscita»; (2) con `crew` e più ruoli il planner chiedeva solo `role=director` e la risposta diceva che gli sceneggiatori non comparivano; (3) il modello citava l'ID interno invece degli ID IMDb e TMDb. Sono state rieseguite le 10 domande interessate (modalità accesa); il confronto sopra e sotto usa le esecuzioni dopo le correzioni. Prima delle correzioni: richieste HTTP acceso 56, query 87, giudice a favore dell'acceso 23, parità 12, a favore dello spento 12; dopo: query 98, a favore dell'acceso 23, parità 14, a favore dello spento 10. Le esecuzioni originali restano in `cinema_db/data/phase6_live/runs_first.jsonl` (ignorato da git).

## 2. Per domanda

| Chiave | Domanda | Tool spento | Tool acceso | HTTP s/a | SQL | s s/a | Fatti s/a | Giudice | Lettura manuale |
|---|---|---|---|---|---|---|---|---|---|
| B01 | Quali film ha diretto Denis Villeneuve? | tmdb | CINEMA | 3/0 | 4 | 13/6 | NO/sì | on | Locale: 9 film, corretto rispetto al database e dichiarato «potrebbe essere incompleto» (nel mondo reale ne mancano 2); con TMDb l'elenco era sbagliato (cortometraggi e documentari, «44 risultati»). Miglioramento netto. |
| B02 | Chi ha scritto la sceneggiatura di Blade Runner? | tmdb | CINEMA | 2/0 | 3 | 6/6 | sì/sì | tie | Pari: gli stessi due sceneggiatori. |
| B03 | Film con Cillian Murphy diretti da Christopher Nolan | tmdb | CINEMA | 3/0 | 3 | 13/7 | NO/sì | on | Locale: i 6 film giusti; con TMDb il fatto atteso mancava. |
| B04 | Da quale libro è tratto Blade Runner? | wikidata | CINEMA | 3/0 | 3 | 13/5 | NO/sì | off | Locale dà il titolo italiano del romanzo («Il cacciatore di androidi»), Wikidata quello originale: leggermente meno preciso. |
| B05 | Esiste un remake di The Thing? | wikidata | CINEMA → wikipedia | 1/2 | 2 | 7/18 | —/— | on | Locale + Wikipedia: dice che il film del 2011 è un prequel; il flag spento inventava un «The Thing (1990) di Nanni Moretti» da un omonimo sbagliato. Miglioramento. |
| B06 | Quali film fanno parte della saga di Alien? | tmdb | CINEMA | 2/0 | 5 | 7/8 | NO/sì | on | Locale: 7 film più un cortometraggio e una serie dichiarati come tali; corretto rispetto al database. |
| B07 | Quanti Oscar ha vinto Parasite? | tmdb | CINEMA | 2/0 | 2 | 6/8 | —/— | on | Dopo la correzione del filtro sul premio il planner chiede quale Parasite si intende (1982 o 2019), come voluto; prima della correzione la richiesta era rifiutata e la risposta inutile. |
| B08 | Chi ha vinto l'Oscar come miglior film nel 1995? | wikipedia | CINEMA | 1/0 | 1 | 10/7 | sì/sì | tie |  |
| B09 | Distingui i film intitolati Crash (anno, regista, ID) | wikidata | CINEMA | 1/0 | 2 | 8/6 | —/— | on | Locale: i due film principali con ID IMDb, TMDb e Wikidata (prima della correzione citava l'ID interno); mancano omonimi minori; il flag spento ne dava 4 ma senza il film di Haggis. |
| B10 | Qual è l'ID IMDb di Parasite? | tmdb | CINEMA | 1/0 | 2 | 6/6 | —/— | on |  |
| B11 | Quanti film ha diretto Federico Fellini? | tmdb | CINEMA | 2/0 | 4 | 8/7 | NO/NO | off | Locale: «22 film più un film TV, 23 opere» come registrati; il flag spento non rispondeva. Il giudice preferisce il silenzio prudente al numero di un catalogo incompleto: giudizio discutibile, la risposta locale dichiara i limiti. |
| B12 | Chi ha composto la colonna sonora di Inception? | tmdb | CINEMA | 2/0 | 3 | 5/5 | sì/sì | tie |  |
| B13 | Punteggi della critica per i film di Villeneuve (preferenza reviews, 5 candidati) | tmdb → omdb → omdb → omdb → omdb → omdb → omdb | tmdb → omdb → omdb → omdb → omdb → omdb → omdb | 10/13 | 0 | 36/31 | sì/sì | on | Invariata (TMDb + OMDb per cinque candidati); la differenza di richieste è variabilità del planner, non del tool. |
| B14 | Che Rotten Tomatoes ha Oppenheimer? | omdb | omdb | 1/2 | 0 | 6/5 | sì/sì | on |  |
| B15 | Regista, cast e punteggi della critica di Oppenheimer | tmdb | CINEMA → tmdb | 2/1 | 4 | 11/17 | sì/sì | on | Locale per regia e cast, TMDb per il resto: 1 richiesta invece di 2. |
| B16 | Da cosa è tratto Oppenheimer e che punteggi ha? | wikidata → tmdb → movie_db → wikipedia → omdb | wikidata → omdb → wikipedia | 7/6 | 0 | 36/24 | sì/sì | on |  |
| B17 | Remake di Solaris e relativo punteggio Metascore | wikidata → omdb | CINEMA → wikipedia → omdb | 3/3 | 2 | 14/19 | —/— | off | Il tool locale non distingue il remake: la risposta locale dice «adattamento del film del 1972», impreciso (è un nuovo adattamento del romanzo); entrambe sbagliano il Metascore secondo il giudice (la fonte dà 67). |
| B18 | Interviste a Villeneuve su Dune e suoi premi | youtube → wikipedia | youtube → CINEMA | 4/2 | 3 | 20/17 | sì/sì | off | Regressione di completezza: il locale ha una sola candidatura di Villeneuve (Arrival) e lo dice; con Wikipedia la risposta sui premi è molto più ricca. Limite dei dati, già noto (premi per persona). |
| B19 | Dove vedo Dune in streaming in Italia? | tmdb | tmdb | 2/2 | 0 | 10/9 | —/— | tie |  |
| B20 | Mostrami il trailer di Aftersun | tmdb | tmdb | 2/2 | 0 | 7/7 | —/— | off |  |
| B21 | Quali film escono questo mese? | tmdb | tmdb | 1/1 | 0 | 10/9 | —/— | on |  |
| B22 | Che voto medio ha Pulp Fiction? | movie_db | movie_db | 0/0 | 0 | 8/7 | —/— | on |  |
| B23 | Quali sono i 10 film più votati di sempre? | movie_db | movie_db | 0/0 | 0 | 13/11 | —/— | on |  |
| B26 | Quante stagioni ha Breaking Bad? | tvmaze | CINEMA | 2/0 | 4 | 5/6 | sì/sì | tie | Locale: 5 stagioni e 7/13/13/13/16 episodi (esatti dopo la correzione), con l'avvertenza che possono differire. |
| B27 | Quando esce il prossimo episodio di Severance? | tvmaze | tvmaze | 2/2 | 0 | 6/5 | —/— | tie |  |
| B28 | Storia della Nouvelle Vague | wikipedia | wikipedia | 2/2 | 0 | 24/18 | —/— | tie |  |
| B29 | Interviste al regista di Parasite | youtube | youtube | 2/2 | 0 | 9/9 | sì/sì | on |  |
| B30 | Cast e episodi della seconda stagione di Dark | tvmaze | tvmaze | 3/3 | 0 | 9/10 | sì/sì | tie |  |
| E01 | Con quali attori ha lavorato di più Christopher Nolan? | tmdb | CINEMA | 1/0 | 2 | 8/9 | NO/sì | on | Locale: Caine 8, Murphy 7 (senza role=director conta anche Transcendence, prodotto da Nolan: corretto per «lavorato con»). |
| E02 | Chi è John Williams? | tmdb | wikipedia | 2/1 | 0 | 10/12 | —/— | on | Il planner ha scelto Wikipedia invece del locale: variabilità. |
| E03 | Chi recita ne Il padrino? | tmdb | CINEMA | 2/0 | 4 | 9/8 | sì/sì | on |  |
| E04 | Chi ha prodotto Il padrino? | tmdb | CINEMA | 0/0 | 3 | 7/6 | NO/NO | on | Locale: «prodotto da Albert S. Ruddy», corretto; il flag spento aggiungeva Coppola e Evans. |
| E05 | Dimmi di Inception | tmdb | tmdb | 0/2 | 0 | 6/7 | —/— | off |  |
| E06 | Quali candidature all'Oscar ha avuto Christopher Nolan? | wikipedia | CINEMA | 2/0 | 3 | 17/8 | sì/sì | off | Regressione di completezza dichiarata: 5 candidature all'Oscar attribuite a Nolan, mancano quelle di Oppenheimer (premi registrati sul film, non sul nominato); Wikipedia ne dà 8 e 2 vittorie. La regola chiede di aggiungere i premi del film: il planner non lo ha fatto in questa esecuzione. |
| E07 | Elenco degli episodi della seconda stagione di Breaking Bad | tvmaze | tvmaze | 2/2 | 0 | 8/10 | sì/sì | tie |  |
| E08 | Parlami del film Zzyzx Qwerty | tmdb → wikipedia | tmdb → wikipedia → CINEMA | 2/2 | 2 | 13/17 | —/— | off |  |
| E09 | Quanti film italiani del 1960 ci sono? | tmdb | CINEMA | 2/0 | 1 | 8/8 | NO/sì | on | Locale: 99 film italiani del 1960 (come registrati); il flag spento non sapeva rispondere. |
| X01 | Chi ha diretto Dune del 2021 e chi ha scritto la sceneggiatura? | tmdb | CINEMA | 2/0 | 3 | 7/7 | sì/sì | tie | Dopo la correzione di crew senza role: regista e i tre sceneggiatori; prima della correzione la risposta diceva che gli sceneggiatori non compaiono. |
| X02 | Quali sono gli ultimi film con Timothée Chalamet? | tmdb | tmdb | 2/2 | 0 | 9/11 | —/— | on |  |
| X03 | Con quali registi ha lavorato di più Michael Caine? | tmdb | CINEMA → tmdb | 2/2 | 2 | 11/13 | NO/NO | tie | Prima esecuzione: nessun collaboratore (planner con argomenti diversi); rilanciata a mano la stessa domanda il planner usa role_b=director e la risposta è giusta (Nolan 8, Gilbert 3...). Variabilità del planner. |
| X04 | Elencami i film della saga de Il padrino | tmdb | CINEMA | 3/0 | 5 | 8/7 | sì/sì | tie | Locale: 3 film della saga, con l'avvertenza che l'elenco può essere parziale. |
| X05 | Quanti Oscar ha vinto Parasite? / Intendevo quello del 2019 di Bong Joon-ho | wikipedia → wikipedia | CINEMA → CINEMA | 3/0 | 6 | 19/13 | sì/sì | off | Dopo la correzione: «4 Oscar» con le quattro categorie, in due passi (omonimo, poi anno). |
| X06 | Quali film ha diretto Denis Villeneuve? | tmdb | CINEMA | 2/0 | 4 | 10/8 | —/— | on | Con la preferenza «recensioni» la filmografia usa il locale senza conflitto e dice che non ha punteggi. |
| X07 | Quali film ha diretto Christopher Nolan? | tmdb | CINEMA → tmdb | 2/2 | 3 | 11/13 | —/— | tie | La frase di conflitto sul tipo di contenuto è la prima della risposta in entrambe le modalità; il locale ha ricevuto type=series dalla guardia. |
| X08 | Chi ha scritto Il cavaliere oscuro e da quale opera è tratto? | tmdb → wikidata → wikipedia → wikipedia | CINEMA → CINEMA | 5/0 | 6 | 25/14 | sì/sì | off | Locale elenca anche Bill Finger e Bob Kane tra gli scrittori (Wikidata) ma avverte che l'elenco comprende gli autori del materiale d'origine; TMDb dava solo i Nolan: meno preciso, dichiarato. |
| X10 | Which films did Federico Fellini direct? | tmdb | CINEMA | 2/0 | 4 | 9/9 | NO/sì | on | Risposta in inglese, 23 opere: la lingua dell'ultimo messaggio è rispettata. |
| X11 | Wer hat die Musik zu Inception komponiert? | tmdb | CINEMA | 2/0 | 3 | 6/6 | sì/sì | tie | Risposta in tedesco: la lingua è rispettata. |
