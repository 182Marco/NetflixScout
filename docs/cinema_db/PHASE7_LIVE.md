# Valutazione live della Fase 7: DB-first con affidabilità per campo, confronto ripetuto

Generata da `python -m cinema_db.harness.tool_eval.run_live7` con il planner, il classificatore, i tool e il modello di risposta reali. Stesse domande e condizioni della fase 6 (47 domande, `rag_search` escluso) più 8 domande della fase 7; ogni domanda è eseguita più volte per modalità (il planner è stocastico). **Spento** = `cinema_db` disattivato, come prima della fase 6. **Acceso** = routing DB-first della fase 7. Colonna «Fase 6»: l'esecuzione unica della fase 6 con il routing precedente (riferimento, non ripetuta).

Quattro cose separate: **misurato** (tool, richieste HTTP davvero inviate, query SQL, secondi), **controllo meccanico** (parole attese nella risposta), **giudice** (`gpt-5.5` a ciechi, diverso dal modello che risponde) e **lettura manuale** (la mia). Le richieste interne del controllo del tipo di opera di MovieLens non sono nelle `calls`.

## 1. Totali (somma su tutte le esecuzioni, misurati)

Domande: 55; esecuzioni per modalità: 165.

| | Spento | Acceso | Differenza |
|---|---|---|---|
| Richieste HTTP | 222 | 116 | -106 (-48 %) |
| Richieste HTTP per esecuzione | 1.35 | 0.70 | |
| Passi di tool | 221 | 250 | +29 |
| Query SQL | 0 | 391 | +391 |
| Tempo totale (s) | 1865 | 1950 | +85 (+5 %) |
| Fatti attesi presenti | 77/111 | 100/111 | |

`cinema_sql` scelto in 119 esecuzioni accese. Giudice, tutte le coppie: {'on': 27, 'off': 19, 'tie': 5}; sulle 10 domande peggiori della fase 6: {'off': 4, 'on': 5}.

## 2. Per domanda (media sulle ripetizioni)

| Chiave | Domanda | Tool spento | Tool acceso | HTTP s/a | SQL | s s/a | Fatti s/a | Giudice (a/p/s) | Fase 6 | Nota |
|---|---|---|---|---|---|---|---|---|---|---|
| B01 | Quali film ha diretto Denis Villeneuve? | tmdb | cinema_sql ×3 | 1/0 | 4 | 11/7 | 1/3/3/3 | 3/0/0 | on |  |
| B02 | Chi ha scritto la sceneggiatura di Blade Runner? | tmdb | cinema_sql ×3 | 0.67/0 | 3 | 6/8 | 3/3/3/3 | 0/1/2 | tie |  |
| B03 | Film con Cillian Murphy diretti da Christopher Nolan | tmdb | cinema_sql ×3 | 1.33/0 | 2.33 | 13/9 | 0/3/3/3 | 3/0/0 | on |  |
| B04 | Da quale libro è tratto Blade Runner? | wikidata → wikipedia → wikipedia | cinema_sql ×3 | 3/0 | 3 | 26/6 | 1/3/3/3 | 0/0/3 | off |  |
| B05 | Esiste un remake di The Thing? | wikidata | cinema_sql ×2; cinema_sql → wikipedia ×1 | 1/0.67 | 2 | 9/13 | —/— | 3/0/0 | on |  |
| B06 | Quali film fanno parte della saga di Alien? | tmdb | cinema_sql ×3 | 1/0 | 3 | 7/7 | 0/3/3/3 | 3/0/0 | on |  |
| B07 | Quanti Oscar ha vinto Parasite? | wikipedia | cinema_sql ×3 | 0.33/0 | 2 | 8/7 | —/— | 0/0/3 | on |  |
| B08 | Chi ha vinto l'Oscar come miglior film nel 1995? | wikipedia | cinema_sql ×3 | 1.33/0 | 2 | 11/7 | 2/3/3/3 | 1/1/1 | tie |  |
| B09 | Distingui i film intitolati Crash (anno, regista, ID) | wikidata | cinema_sql ×3 | 1/0 | 2 | 9/7 | —/— | 3/0/0 | on |  |
| B10 | Qual è l'ID IMDb di Parasite? | wikidata | cinema_sql ×3 | 1/0 | 2 | 9/6 | —/— | 0/0/3 | on |  |
| B11 | Quanti film ha diretto Federico Fellini? | tmdb | cinema_sql ×3 | 0.67/0 | 4 | 7/7 | 0/3/0/3 | 3/0/0 | off |  |
| B12 | Chi ha composto la colonna sonora di Inception? | tmdb | cinema_sql ×3 | 0.67/0 | 3 | 6/6 | 3/3/3/3 | 0/3/0 | tie |  |
| B13 | Punteggi della critica per i film di Villeneuve (preferenza reviews, 5 candidati | tmdb → omdb → omdb → omdb → omdb → omdb → omdb → omdb | cinema_sql → tmdb → omdb → omdb → omdb → omdb → omdb ×1; cinema_sql → tmdb → omdb → tmdb → omdb → omdb → omdb → omdb → omdb ×1 | 7/9 | 3.33 | 27/41 | 2/3/1/3 | 2/0/1 | on |  |
| B14 | Che Rotten Tomatoes ha Oppenheimer? | omdb | omdb ×3 | 2/1 | 0 | 6/7 | 3/3/3/3 | 0/0/3 | on |  |
| B15 | Regista, cast e punteggi della critica di Oppenheimer | tmdb | cinema_sql → omdb → tmdb ×2; cinema_sql → tmdb ×1 | 0.67/1.33 | 3 | 11/20 | 3/3/3/3 | 3/0/0 | on |  |
| B16 | Da cosa è tratto Oppenheimer e che punteggi ha? | wikidata → movie_db → wikipedia → omdb | cinema_sql → omdb ×2; cinema_sql → movie_db ×1 | 5/0.67 | 3 | 36/14 | 3/3/3/3 | 1/0/2 | on |  |
| B17 | Remake di Solaris e relativo punteggio Metascore | wikidata → omdb | cinema_sql → omdb ×2; wikidata → omdb ×1 | 2.67/2 | 1.33 | 16/16 | —/— | 2/0/1 | off |  |
| B18 | Interviste a Villeneuve su Dune e suoi premi | youtube → wikipedia | cinema_sql → youtube → wikipedia ×3 | 2.67/2.67 | 3 | 19/28 | 2/3/3/3 | 0/0/0 | off |  |
| B19 | Dove vedo Dune in streaming in Italia? | tmdb | tmdb ×3 | 0.67/0.67 | 0 | 9/8 | —/— | 0/0/0 | tie |  |
| B20 | Mostrami il trailer di Aftersun | tmdb | tmdb ×3 | 0.67/0.67 | 0 | 8/8 | —/— | 0/0/0 | off |  |
| B21 | Quali film escono questo mese? | tmdb | tmdb ×3 | 1/1 | 0 | 10/11 | —/— | 0/0/0 | on |  |
| B22 | Che voto medio ha Pulp Fiction? | movie_db | movie_db ×3 | 0/0 | 0 | 8/8 | —/— | 0/0/0 | on |  |
| B23 | Quali sono i 10 film più votati di sempre? | movie_db | movie_db ×3 | 0/0 | 0 | 11/12 | —/— | 0/0/0 | on |  |
| B26 | Quante stagioni ha Breaking Bad? | tvmaze | cinema_sql ×3 | 2/0 | 4 | 5/6 | 3/3/3/3 | 0/0/0 | tie |  |
| B27 | Quando esce il prossimo episodio di Severance? | tvmaze | tvmaze ×3 | 2/2 | 0 | 6/7 | —/— | 0/0/0 | tie |  |
| B28 | Storia della Nouvelle Vague | wikipedia | wikipedia ×3 | 0.67/0.67 | 0 | 19/19 | —/— | 0/0/0 | tie |  |
| B29 | Interviste al regista di Parasite | youtube | youtube ×3 | 2/2 | 0 | 9/11 | 3/3/3/3 | 0/0/0 | on |  |
| B30 | Cast e episodi della seconda stagione di Dark | tvmaze | tmdb → tvmaze ×2; tvmaze ×1 | 3/3.33 | 0 | 9/14 | 3/3/3/3 | 0/0/0 | tie |  |
| E01 | Con quali attori ha lavorato di più Christopher Nolan? | tmdb | cinema_sql ×3 | 4/0 | 2 | 16/10 | 1/3/3/3 | 0/0/0 | on |  |
| E02 | Chi è John Williams? | wikipedia | cinema_sql ×2; cinema_sql → cinema_sql ×1 | 1.33/0 | 2 | 17/11 | —/— | 0/0/0 | on |  |
| E03 | Chi recita ne Il padrino? | tmdb | tmdb ×3 | 0.67/0.67 | 0 | 8/19 | 3/3/3/3 | 0/0/0 | on |  |
| E04 | Chi ha prodotto Il padrino? | tmdb | cinema_sql ×3 | 0/0 | 3 | 7/6 | 0/3/0/3 | 0/0/0 | on |  |
| E05 | Dimmi di Inception | tmdb | tmdb ×2; cinema_sql → tmdb ×1 | 0/0.67 | 2.33 | 7/10 | —/— | 0/0/0 | off |  |
| E06 | Quali candidature all'Oscar ha avuto Christopher Nolan? | wikipedia → wikipedia | cinema_sql → wikipedia ×3 | 0.67/0.67 | 3 | 18/19 | 3/3/3/3 | 0/0/0 | off |  |
| E07 | Elenco degli episodi della seconda stagione di Breaking Bad | tvmaze | tvmaze ×3 | 2/2 | 0 | 7/8 | 3/3/3/3 | 0/0/0 | tie |  |
| E08 | Parlami del film Zzyzx Qwerty | tmdb → wikipedia | tmdb → wikipedia → cinema_sql ×2; cinema_sql → tmdb → wikipedia ×1 | 0.67/0.67 | 2 | 11/17 | —/— | 0/0/0 | off |  |
| E09 | Quanti film italiani del 1960 ci sono? | tmdb | cinema_sql ×3 | 1/0 | 1 | 8/7 | 0/3/3/3 | 0/0/0 | on |  |
| X01 | Chi ha diretto Dune del 2021 e chi ha scritto la sceneggiatura? | tmdb | cinema_sql ×3 | 0.67/0 | 3 | 7/8 | 2/3/3/3 | 0/0/0 | tie |  |
| X02 | Quali sono gli ultimi film con Timothée Chalamet? | tmdb | cinema_sql ×1; cinema_sql → tmdb ×1 | 0.67/1 | 2.67 | 9/14 | —/— | 0/0/0 | on | recent works: not the local archive |
| X03 | Con quali registi ha lavorato di più Michael Caine? | tmdb | cinema_sql ×3 | 1/0 | 2 | 7/10 | 0/3/3/3 | 0/0/0 | tie |  |
| X04 | Elencami i film della saga de Il padrino | tmdb | cinema_sql ×3 | 0.67/0 | 4.33 | 7/8 | 3/3/3/3 | 0/0/0 | tie |  |
| X05 | Quanti Oscar ha vinto Parasite? / Intendevo quello del 2019 di Bong Joon-ho | wikipedia → wikipedia | cinema_sql → cinema_sql ×3 | 1/0 | 7 | 18/15 | 3/3/3/3 | 0/0/0 | off | the namesake is asked, then settled by the user |
| X06 | Quali film ha diretto Denis Villeneuve? | tmdb | cinema_sql ×3 | 0.67/0 | 4 | 11/8 | —/— | 0/0/0 | on | the reviews preference is not a conflict for a filmography |
| X07 | Quali film ha diretto Christopher Nolan? | tmdb | cinema_sql → tmdb ×3 | 0.67/0.67 | 3 | 10/15 | —/— | 0/0/0 | tie | the content type prevails over the request |
| X08 | Chi ha scritto Il cavaliere oscuro e da quale opera è tratto? | tmdb → wikidata → wikipedia | cinema_sql → cinema_sql → wikipedia → wikipedia ×1; cinema_sql → cinema_sql ×1 | 5/1 | 6 | 23/21 | 3/3/3/3 | 0/0/0 | off |  |
| X10 | Which films did Federico Fellini direct? | tmdb | cinema_sql ×3 | 0.67/0 | 4 | 9/9 | 0/3/3/3 | 0/0/0 | on |  |
| X11 | Wer hat die Musik zu Inception komponiert? | tmdb | cinema_sql ×3 | 0.67/0 | 3 | 6/6 | 3/3/3/3 | 0/0/0 | tie |  |
| P01 | Chi sono gli attori protagonisti di Inception, chi lo ha diretto e quali premi h | tmdb → wikipedia | cinema_sql → tmdb → cinema_sql → wikipedia ×2; cinema_sql → tmdb → cinema_sql → wikipedia → wikipedia ×1 | 1.67/0.67 | 7 | 16/30 | 3/3/3/3 | 0/0/0 | — | the example of the phase: director and awards from the database, the lead actors from TMDb (the database cast has no order) |
| P02 | Chi ha recitato in Heat di Michael Mann? | tmdb | tmdb ×3 | 0.67/0.67 | 0 | 8/9 | 3/3/3/3 | 0/0/0 | — | the whole cast, no lead order asked: the database alone |
| P03 | Quanti Oscar ha vinto Christopher Nolan e per quali film? | wikipedia | cinema_sql → wikipedia ×3 | 0/0 | 3 | 10/16 | 3/3/3/3 | 0/0/0 | — | person awards: winners named by the source |
| P04 | Quali candidature all'Oscar ha avuto Denis Villeneuve? | wikipedia | cinema_sql → wikipedia ×3 | 0.33/0 | 3 | 14/15 | 3/3/3/3 | 0/0/0 | — | person nominations are only partly recorded |
| P05 | Quanti episodi ha la prima stagione di Friends? | tvmaze | tvmaze ×3 | 1/1 | 0 | 6/6 | 0/3/0/3 | 0/0/0 | — | episode counts are uncertain locally: TVmaze verifies |
| P06 | Chi ha diretto Oppenheimer e dove posso vederlo in streaming in Italia? | tmdb | cinema_sql → tmdb ×3 | 0.67/0.33 | 3 | 10/10 | 3/3/3/3 | 0/0/0 | — | director local, streaming external |
| P07 | Chi ha scritto Pulp Fiction e chi ha composto la colonna sonora? | tmdb | cinema_sql ×3 | 0.67/0 | 3 | 7/10 | 3/3/3/3 | 0/0/0 | — |  |
| P08 | Dimmi il regista e l'anno di Il Padrino e dammi il punteggio Metascore | omdb → tmdb → omdb | cinema_sql → omdb ×3 | 2/1 | 7 | 16/11 | 3/3/3/3 | 0/0/0 | — | structured facts local, score external |
