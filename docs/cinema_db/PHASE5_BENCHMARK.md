# Benchmark della fase 5: `cinema_sql` sul database reale

Generato da `python -m cinema_db.harness.tool_eval.run_benchmark` (offline, gratuito, nessuna rete, nessun LLM). **Misurato**: query SQL eseguite dal tool e tempi (mediana di 5 esecuzioni, connessione aperta a ogni esecuzione); correttezza rispetto al database, ricalcolata con SQL indipendente sulle **tabelle di base** (non sulle viste e non attraverso la guardia). **Non misurato**: il planner. Le sequenze di passi sono scritte a mano (come le scriverebbe un planner), quindi quale piano scriva davvero un planner LLM **non** è provato qui. La colonna «lettura manuale» è la mia lettura del risultato contro ciò che so del mondo, scritta dopo aver visto l'output: non è un controllo automatico.

Database: digest `b3b0de5122e82432…`. Domande: 39 (30 eseguite, 9 non applicabili al database locale).

## 1. Esiti

| Esito | Domande |
|---|---|
| corretta | 22 |
| alternative (è la risposta) | 2 |
| non trovato (corretto) | 1 |
| corretta dopo la scelta tra omonimi | 5 |
| non applicabile | 9 |

Query SQL totali sulle 30 domande eseguite: **116** (mediana 3 per domanda). Tempo di una domanda (tutti i passi, connessione compresa): mediana **33 ms**, massimo **83 ms**.

## 2. Domande, risposte e verifica

| Chiave | Domanda | Risposta ottenuta (sintesi) | Esito | Passi | Query | ms | Lettura manuale e limiti dei dati |
|---|---|---|---|---|---|---|---|
| B01 | Quali film ha diretto Denis Villeneuve? | Denis Villeneuve: 9 opere, es. Maelström (2000); La donna che canta (2010); Enemy (2013); Prisoners (2013); Sicario (2015) | corretta | 1 | 4 | 34 | Corretto rispetto al database (9 film, 2000-2024). Rispetto al mondo reale ne mancano almeno 2 (Un 32 août sur terre, 1998; Polytechnique, 2009): non sono nel catalogo locale. |
| B02 | Chi ha scritto la sceneggiatura di Blade Runner? | Blade Runner: writer: David Webb Peoples, Hampton Fancher | corretta | 1 | 3 | 34 | Coincide con quanto noto (Hampton Fancher, David Webb Peoples). |
| B03 | Film con Cillian Murphy diretti da Christopher Nolan | Christopher Nolan + Cillian Murphy: 6 opere: Batman Begins (2005); Il cavaliere oscuro (2008); Inception (2010); Il cavaliere oscuro - Il ritorno (2012); Dunkirk (2017); Oppenheimer (2023) | corretta | 1 | 3 | 33 | Coincide con quanto noto: i 6 film di Nolan con Cillian Murphy. |
| B04 | Da quale libro è tratto Blade Runner? | Blade Runner: is based on Il cacciatore di androidi (other); is followed by Blade Runner 2049 (film) | corretta | 1 | 3 | 31 | Fonte registrata: «Il cacciatore di androidi» (titolo italiano del romanzo di Dick) e il seguito Blade Runner 2049: coerente; il tipo di legame non è distinto. |
| B05 | Esiste un remake di The Thing? | ambiguous: La cosa (1982); La cosa (2011) → La cosa: is based on La cosa da un altro mondo (other); is followed by La cosa (film) | corretta dopo la scelta tra omonimi | 2 | 5 | 52 | Il database non dice «remake»: La cosa (1982) risulta basata sul film del 1951 e seguita dal film del 2011. Remake o prequel non si può affermare (nota relations): risposta parziale, la conferma richiede Wikipedia o Wikidata. |
| B06 | Quali film fanno parte della saga di Alien? | Alien: Alien, Aliens - Scontro finale, Alien³, Alien - La clonazione, Prometheus, Alien: Covenant | corretta | 1 | 3 | 23 | 9 membri registrati, tra cui un cortometraggio (Prologue: The Crossing) e una serie del 2025; i crossover con Predator non ci sono (non fanno parte della saga su Wikidata). Corretto rispetto al database. |
| B07 | Quanti Oscar ha vinto Parasite? | ambiguous: Mutanti (1982); Parasite (2019) → Parasite: 14 risultati, es. Dorian Award for Film of the Year 2019 won Parasite; Gilde Film Price 2019 won Parasite; Palma d'oro 2019 won Parasite | corretta dopo la scelta tra omonimi | 2 | 6 | 57 | 4 Oscar vinti (film, regista, sceneggiatura originale, film internazionale) più altri premi: coincide con il mondo reale. Senza l'anno il titolo è ambiguo (Mutanti, 1982, ha Parasite come titolo originale). |
| B08 | Chi ha vinto l'Oscar come miglior film nel 1995? | per nome: 2 risultati, es. Oscar al miglior film 1995 won Forrest Gump; Oscar al miglior film in lingua straniera 1995 won Sole ingannatore | corretta | 1 | 2 | 36 | Forrest Gump (cerimonia 1995, film del 1994): corretto; compare anche il film in lingua straniera (Sole ingannatore), giusto ma da distinguere per categoria. |
| B09 | Distingui i film intitolati Crash (anno, regista, ID) | ambiguous: Crash (1996); Crash - Contatto fisico (2004); Crash (2008) | alternative (è la risposta) | 1 | 2 | 26 | Alternative corrette: Crash 1996 (Cronenberg), Crash 2004 (Haggis), serie del 2008. |
| B10 | Qual è l'ID IMDb di Parasite? | ambiguous: Mutanti (1982); Parasite (2019) → Parasite (2019), regia Bong Joon-ho, imdb tt6751668 | corretta dopo la scelta tra omonimi | 2 | 4 | 45 | tt6751668 coincide. Il titolo è ambiguo: serve un secondo passo dopo le alternative. |
| B11 | Quanti film ha diretto Federico Fellini? | Federico Fellini: 23 opere, es. Luci del varietà (1950); Lo sceicco bianco (1952); I vitelloni (1953); L'amore in città (1953); La strada (1954) | corretta | 1 | 4 | 35 | 23 opere come regista nel catalogo (cortometraggi ed episodi di film collettivi inclusi): non confrontato con una filmografia esterna. |
| B12 | Chi ha composto la colonna sonora di Inception? | Inception: composer: Hans Zimmer | corretta | 1 | 3 | 30 | Hans Zimmer: coincide. |
| B13 | Punteggi della critica per i film di Villeneuve (preferenza reviews, 5 candidati) | Denis Villeneuve: 9 opere, es. Dune - Parte due (2024); Dune (2021); Blade Runner 2049 (2017); Arrival (2016); Sicario (2015) | corretta | 1 | 4 | 33 | Gli ultimi 5 film con gli id IMDb e TMDb pronti per OMDb coincidono con la filmografia recente reale di Villeneuve (Dune 2, Dune, Blade Runner 2049, Arrival, Sicario). |
| B14 | Che Rotten Tomatoes ha Oppenheimer? | Oppenheimer (2023), regia Christopher Nolan, imdb tt15398776 | corretta | 1 | 2 | 25 | L'id IMDb è corretto; il punteggio resta esterno (1 richiesta a OMDb per id invece di 2 per titolo). |
| B15 | Regista, cast e punteggi della critica di Oppenheimer | Oppenheimer: scrittori ['Christopher Nolan'], musica ['Ludwig Göransson'], generi ['Biography', 'Drama', 'Historical', 'Thriller'], paesi ['United Kingdom', 'United States'] → Oppenheimer: 59 nel cast, es. Alden Ehrenreich, Benny Safdie, Cillian Murphy, Dane D | corretta | 2 | 11 | 83 | Regia, sceneggiatura, musica, generi, paesi e il cast (59 nomi, parziale) coincidono con quanto noto; i punteggi sono esterni. |
| B16 | Da cosa è tratto Oppenheimer e che punteggi ha? | Oppenheimer: is based on Robert Oppenheimer, il padre della bomba atomica (other) | corretta | 1 | 3 | 30 | La fonte registrata è il libro «American Prometheus» col titolo italiano («Robert Oppenheimer, il padre della bomba atomica»): corretto. |
| B17 | Remake di Solaris e relativo punteggio Metascore | ambiguous: Solaris (1972); Solaris (2002) → Solaris: is based on Solaris (other) | corretta dopo la scelta tra omonimi | 2 | 5 | 55 | Il database registra Solaris (2002) come «basato su» il romanzo Solaris, non sul film del 1972: nessuna relazione di remake, quindi la domanda non è risolta dal solo database (resta Wikidata o Wikipedia). |
| B18 | Interviste a Villeneuve su Dune e suoi premi | Denis Villeneuve: 1 risultati, es. Oscar al miglior regista 2017 nominated Arrival | corretta | 1 | 3 | 27 | Un solo risultato (candidatura all'Oscar per Arrival): nel mondo reale i premi di Villeneuve sono molti di più. I premi registrati solo sul film non sono attribuiti alla persona (nota awards_person_scope): l'assenza non prova nulla. |
| B19 | Dove vedo Dune in streaming in Italia? | — (non risponde il database locale) | non applicabile | 0 | 0 | 0 | streaming availability is not in the local database |
| B20 | Mostrami il trailer di Aftersun | — (non risponde il database locale) | non applicabile | 0 | 0 | 0 | videos are not in the local database |
| B21 | Quali film escono questo mese? | — (non risponde il database locale) | non applicabile | 0 | 0 | 0 | recent and upcoming releases are not in the local catalogue |
| B22 | Che voto medio ha Pulp Fiction? | — (non risponde il database locale) | non applicabile | 0 | 0 | 0 | audience ratings are MovieLens, which the local cinema database does not contain |
| B23 | Quali sono i 10 film più votati di sempre? | — (non risponde il database locale) | non applicabile | 0 | 0 | 0 | rankings by votes are MovieLens |
| B24 | Consigliami un film malinconico ambientato in Giappone | — (non risponde il database locale) | non applicabile | 0 | 0 | 0 | semantic recommendation is the film index (RAG), not SQL |
| B25 | Film come Arrival ma senza alieni | — (non risponde il database locale) | non applicabile | 0 | 0 | 0 | semantic recommendation is the film index (RAG), not SQL |
| B26 | Quante stagioni ha Breaking Bad? | Breaking Bad: 5 stagioni S1=8/7, S2=13/13, S3=13/13, S4=13/11, S5=18/0 | corretta | 1 | 4 | 38 | 5 stagioni: corretto. I conteggi degli episodi NON sono affidabili (S1 8 righe/7 numerate contro 7 reali, S4 13/11 contro 13, S5 18/0 contro 16): lo dice la nota episode_duplicates. |
| B27 | Quando esce il prossimo episodio di Severance? | — (non risponde il database locale) | non applicabile | 0 | 0 | 0 | future episodes are live data (TVmaze) |
| B28 | Storia della Nouvelle Vague | — (non risponde il database locale) | non applicabile | 0 | 0 | 0 | encyclopedic prose is Wikipedia |
| B29 | Interviste al regista di Parasite | ambiguous: Mutanti (1982); Parasite (2019) → Parasite (2019), regia Bong Joon-ho, imdb tt6751668 | corretta dopo la scelta tra omonimi | 2 | 4 | 46 | Bong Joon-ho: corretto (dopo la scelta tra gli omonimi). |
| B30 | Cast e episodi della seconda stagione di Dark | Dark: 15 nel cast, es. Andreas Pietschmann, Angela Winkler, Antje Traue, Carlotta von Falkenhayn → Dark S2: 8 episodi None:Fine e principio, None:I viaggiatori, None:Il diavolo bianco | corretta | 2 | 9 | 74 | Cast di 15 nomi (parziale) e 8 episodi della seconda stagione di Dark (il numero coincide con la realtà) ma senza numerazione né date: la numerazione resterebbe da TVmaze. |
| E01 | Con quali attori ha lavorato di più Christopher Nolan? | Christopher Nolan: Michael Caine (8); Cillian Murphy (6); Christian Bale (4); Gary Oldman (4); John Nolan (4) | corretta | 1 | 2 | 30 | Michael Caine 8: coincide con i film reali di Nolan con Caine. |
| E02 | Chi è John Williams? | ambiguous: John Williams (1903); John Williams (1932) | alternative (è la risposta) | 1 | 2 | 23 | John Williams 1903 e 1932: corretto, due persone distinte (il compositore del 1932 ha 107 crediti). |
| E03 | Chi recita ne Il padrino? | Il padrino: 40 nel cast, es. Abe Vigoda, Al Lettieri, Al Martino, Al Pacino | corretta | 1 | 4 | 35 | 40 nomi: il cast è parziale rispetto al film reale e senza ordine di rilievo (nota cast_order). |
| E04 | Chi ha prodotto Il padrino? | Il padrino: distribution: Ivi.ru, Paramount Pictures, Paramount+, Xfinity Streampix; production: Alfran Productions, Paramount Pictures | corretta | 1 | 3 | 30 | Alfran Productions e Paramount: coincide; tra i distributori ci sono servizi di streaming, come registrati. |
| E05 | Dimmi di Inception | Inception: scrittori ['Christopher Nolan'], musica ['Hans Zimmer'], generi ['Action', 'Adventure', 'Crime', 'Drama', 'Heist', 'Mystery', 'Science fiction', 'Thriller'], paesi ['United Kingdom', 'United States'] | corretta | 1 | 7 | 50 | Scheda coerente con quanto noto; i generi sono quelli registrati (compaiono anche Heist e Mystery). |
| E06 | Quali candidature all'Oscar ha avuto Christopher Nolan? | Christopher Nolan: 6 risultati, es. Oscar alla migliore sceneggiatura originale 2002 nominated Memento; Oscar alla migliore sceneggiatura originale 2011 nominated Inception; Oscar al miglior film 2011 nominated Inception | corretta | 1 | 3 | 27 | Solo candidature (Memento, Inception, Dunkirk): mancano le vittorie di Oppenheimer (film e regia), che il database ha sul film ma non sul nominato. Caso tipico in cui l'assenza non prova nulla: la nota awards_person_scope lo dice. |
| E07 | Elenco degli episodi della seconda stagione di Breaking Bad | Breaking Bad S2: 13 episodi 1:Tutto cambia, 2:Grigliato, 3:Punto da un'ape morta | corretta | 1 | 5 | 44 | 13 episodi: corretto. |
| E08 | Parlami del film Zzyzx Qwerty | not_found [title_unknown] | non trovato (corretto) | 1 | 2 | 32 | Not found, senza dedurre che non esista. |
| E09 | Quanti film italiani del 1960 ci sono? | [{"n": 99}] | corretta | 1 | 1 | 22 | 99 film italiani del 1960 nel catalogo: il numero reale è maggiore, il catalogo è incompleto. |

## 3. Confronto con la baseline (30 domande di `BASELINE.md`)

«Copertura teorica» = cosa il tool può dare per costruzione (completa, parziale, nessuna). «Verificato» = esito del benchmark. Le richieste HTTP «oggi» e «dopo (baseline)» sono quelle di `baseline.json` (per le operazioni con fixture sono misurate sui transport finti, per le altre stimate dal codice); «dopo (verificato)» applica la stessa riduzione solo alle domande con copertura non nulla il cui risultato locale è stato verificato corretto (anche dopo la scelta tra omonimi) **e** risolve davvero la domanda secondo la mia lettura manuale (B05 e B17 no: il database non dice «remake»), altrimenti resta il valore di oggi.

| # | Domanda | Copertura teorica | Verificato | HTTP oggi | HTTP dopo (baseline) | HTTP dopo (verificato) | Tool esterni ancora necessari | Passi cinema_sql | Query | ms |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Quali film ha diretto Denis Villeneuve? | full | corretta | 2 | 0 | 0 | — | 1 | 4 | 34 |
| 2 | Chi ha scritto la sceneggiatura di Blade Runner? | full | corretta | 2 | 0 | 0 | — | 1 | 3 | 34 |
| 3 | Film con Cillian Murphy diretti da Christopher Nolan | full | corretta | 2 | 0 | 0 | — | 1 | 3 | 33 |
| 4 | Da quale libro è tratto Blade Runner? | full | corretta | 3 | 0 | 0 | — | 1 | 3 | 31 |
| 5 | Esiste un remake di The Thing? | full | corretta dopo la scelta tra omonimi | 3 | 0 | 3 | — | 2 | 5 | 52 |
| 6 | Quali film fanno parte della saga di Alien? | full | corretta | 3 | 0 | 0 | — | 1 | 3 | 23 |
| 7 | Quanti Oscar ha vinto Parasite? | full | corretta dopo la scelta tra omonimi | 2 | 0 | 0 | — | 2 | 6 | 57 |
| 8 | Chi ha vinto l'Oscar come miglior film nel 1995? | full | corretta | 2 | 0 | 0 | — | 1 | 2 | 36 |
| 9 | Distingui i film intitolati Crash (anno, regista, ID) | full | alternative (è la risposta) | 1 | 0 | 0 | — | 1 | 2 | 26 |
| 10 | Qual è l'ID IMDb di Parasite? | full | corretta dopo la scelta tra omonimi | 2 | 0 | 0 | — | 2 | 4 | 45 |
| 11 | Quanti film ha diretto Federico Fellini? | full | corretta | 2 | 0 | 0 | — | 1 | 4 | 35 |
| 12 | Chi ha composto la colonna sonora di Inception? | full | corretta | 2 | 0 | 0 | — | 1 | 3 | 30 |
| 13 | Punteggi della critica per i film di Villeneuve (preferenza reviews, 5 candidati) | partial | corretta | 12 | 5 | 5 | omdb_search | 1 | 4 | 33 |
| 14 | Che Rotten Tomatoes ha Oppenheimer? | partial | corretta | 2 | 1 | 1 | omdb_search | 1 | 2 | 25 |
| 15 | Regista, cast e punteggi della critica di Oppenheimer | partial | corretta | 4 | 1 | 1 | omdb_search | 2 | 11 | 83 |
| 16 | Da cosa è tratto Oppenheimer e che punteggi ha? | partial | corretta | 5 | 1 | 1 | omdb_search | 1 | 3 | 30 |
| 17 | Remake di Solaris e relativo punteggio Metascore | partial | corretta dopo la scelta tra omonimi | 5 | 1 | 5 | omdb_search, wikidata_search | 2 | 5 | 55 |
| 18 | Interviste a Villeneuve su Dune e suoi premi | partial | corretta | 4 | 2 | 2 | youtube_search | 1 | 3 | 27 |
| 19 | Dove vedo Dune in streaming in Italia? | none | non applicabile | 2 | 2 | 2 | — | 0 | 0 | 0 |
| 20 | Mostrami il trailer di Aftersun | none | non applicabile | 2 | 2 | 2 | — | 0 | 0 | 0 |
| 21 | Quali film escono questo mese? | none | non applicabile | 1 | 1 | 1 | — | 0 | 0 | 0 |
| 22 | Che voto medio ha Pulp Fiction? | none | non applicabile | 0 | 0 | 0 | — | 0 | 0 | 0 |
| 23 | Quali sono i 10 film più votati di sempre? | none | non applicabile | 10 | 10 | 10 | — | 0 | 0 | 0 |
| 24 | Consigliami un film malinconico ambientato in Giappone | none | non applicabile | 5 | 5 | 5 | — | 0 | 0 | 0 |
| 25 | Film come Arrival ma senza alieni | none | non applicabile | 5 | 5 | 5 | — | 0 | 0 | 0 |
| 26 | Quante stagioni ha Breaking Bad? | full | corretta | 3 | 3 | 3 | — | 1 | 4 | 38 |
| 27 | Quando esce il prossimo episodio di Severance? | none | non applicabile | 2 | 2 | 2 | — | 0 | 0 | 0 |
| 28 | Storia della Nouvelle Vague | none | non applicabile | 2 | 2 | 2 | — | 0 | 0 | 0 |
| 29 | Interviste al regista di Parasite | partial | corretta dopo la scelta tra omonimi | 2 | 2 | 2 | youtube_search | 2 | 4 | 46 |
| 30 | Cast e episodi della seconda stagione di Dark | partial | corretta | 4 | 4 | 4 | tvmaze_search | 2 | 9 | 74 |

### Totali

| Metrica | Valore |
|---|---|
| Richieste HTTP oggi (baseline) | 96 |
| Richieste HTTP dopo, assunte dalla baseline | 49 |
| Richieste HTTP dopo, **verificate** | 56 |
| Domande con copertura completa / parziale / nessuna | 13 / 8 / 9 |
| Copertura completa, verificata e che risolve la domanda (senza tool esterno) | 12 su 13 |
| Domande con almeno un omonimo da risolvere (un passo in più) | 5 |
| Query locali per le 21 domande con copertura completa o parziale (mediana) | 4 |

Cosa dice il confronto, con i limiti:

- La baseline assumeva 49 richieste dopo; con i piani scritti a mano il conteggio verificato è 56 (in più rispetto alla stima: sono le domande in cui il risultato locale non basta o non risolve la domanda): sono 40 richieste in meno su 96, ma contando solo il lato HTTP.
- **Passi di pianificazione**: 5 domande (B05, B07, B10, B17, B29) hanno un titolo omonimo e richiedono un secondo passo dopo le alternative; la baseline le contava a un solo passo. È un costo reale non incluso nella stima (un secondo passo del planner, stimato circa 2 s).
- **Dove il fallback esterno resta indispensabile**: punteggi (OMDb), interviste (YouTube), streaming, trailer, uscite recenti, classifiche per voto e consigli semantici (nessun dato locale); numerazione degli episodi (TVmaze); «remake» (B05, B17): il database non distingue remake, prequel e adattamento.
- **Dati incompleti**: il catalogo non ha tutti i film (mancano due film di Villeneuve), i premi assegnati alla persona sono solo quelli con il nominato registrato (le vittorie di Oppenheimer non compaiono tra quelle di Nolan), i conteggi degli episodi non sono affidabili (Breaking Bad S1, S4, S5). In questi casi una risposta locale può essere incompleta senza saperlo: per questo il tool la dichiara nelle note e non la presenta come completa.
- La riduzione delle richieste è la differenza di conteggio tra due piani scritti a mano: non è una misura di un turno reale con planner e modello.
