# Fase 4 — Audit di qualità del catalogo Wikipedia

Stato: **audit concluso, nessuna correzione applicata**. `films.jsonl`, lo snapshot Wikidata, gli shard degli embedding e la collezione `wikipedia_films_it` sono invariati; la collezione `netflix_scout` e il vecchio RAG non sono stati toccati. Tutto è calcolato da dati locali (nessuna richiesta di rete, nessuna API a pagamento). Codice in `audit/`, elenchi riproducibili in `audit/*.json`, dettaglio dei 246 record in `AUDIT_NOYEAR_246.md`. Il commento "misurato / interpretato" accompagna ogni numero.

## 0. Stato di partenza verificato

- **Nessun commit è stato fatto.** `git log` è fermo a `28889cc`, lo stesso di inizio lavoro; `pipelines/wikipedia_films/` è interamente non tracciata. Nelle sessioni precedenti non mi è stata chiesta un commit (ogni fase diceva "nessun commit"); non l'ho fatto. Se ne intendevi uno, va chiesto esplicitamente.
- Nessun processo della pipeline attivo (solo il server Qdrant, `bin/qdrant`).
- `netflix_scout`: 42.522 punti, green, invariata. `wikipedia_films_it`: 41.438 punti, green, `check` OK (id, vettori, payload, cinque film con tutti i chunk).
- Nessun embedding o indicizzazione ripetuti.

## 1. Esito in numeri [misurato sul catalogo, classificazione interpretata]

| | record | % |
|---|---|---|
| **film validi** (verdetto `film`) | **41.091** | 99,20% |
| **falsi positivi** (non sono un film) | **259** | 0,63% |
| **dubbi** da verificare | **71** | 0,17% |
| totale | 41.421 | |

I 259 falsi positivi: **181 serie** (63 manga, 63 miniserie, 20 con titolo che indica una serie, 15 serie TV, 12 anime, 3 romanzi a puntate, 2 cinegiornali, 2 programmi TV, 1 visual novel), **57 articoli di argomento** (25 generi, 9 pagine su una serie di film, 5 liste, 4 oggetti di fantasia come le USS Enterprise, 4 argomenti di cinema, 3 franchise, 2 tecniche, e 1 ciascuno per disturbo medico, organizzazione, professione, personaggio dei fumetti, set cinematografico) e **21 altre opere** (13 opere letterarie, 6 videogiochi, 1 balletto, 1 fumetto).

I 41.091 film includono i generi di opera cinematografica: lungometraggi 35.116, cortometraggi 3.430, film d'animazione 1.309, film per la televisione 912, film muti 209, speciali TV 29, film per l'home video 28, film musicali 7, serial 7, progetti non usciti 14 (*unreleased*, da guardare), non classificati per sottotipo 27 (il sottotipo è la prima classe `P31` riconosciuta: i documentari sono sottostimati, 3). Se il prodotto vuole solo lungometraggi, il filtro è il campo `subtype`.

**Affidabilità del verdetto "film"**: 39.799 hanno l'infobox `{{Film}}` (di questi 39.773, cioè il 99,8% di tutti i 39.842 record con infobox, hanno anche una classe Wikidata di film: confidenza alta; 27 non ne hanno e restano film a confidenza media); 1.292 sono entrati solo per una categoria "Film …" e sono stati accettati perché Wikidata li classifica come film e hanno IMDb, regia o un suffisso "(film …)" nel titolo (confidenza media). Quest'ultimo gruppo contiene soprattutto film per la televisione italiani (912 `tv_film` in tutto).

## 2. Come ho classificato [interpretato, spiegabile]

Lista di decisione (`audit/classify.py`), applicata a tutti i 41.421 record, con i motivi salvati per ciascuno:

1. classe Wikidata `P31` di argomento (genere, tecnica, lista, franchise, oggetto di fantasia…) → articolo di argomento;
2. titolo "(serie di film)", "(franchise)", "(saga)" → pagina su una serie di film;
3. videogioco, opera letteraria, fumetto senza classe di film → altra opera;
4. classe di serie (serie TV, miniserie, manga, anime) senza classe di film → serie (se ha anche l'infobox `{{Film}}` resta **dubbio**: la pagina è di un film ma l'elemento Wikidata è della serie);
5. suffisso nel titolo ("miniserie televisiva", "serie animata", "manga") → serie;
6. classe di film → film (con l'infobox: alta; solo categoria: media se ha IMDb o regia o "(film …)", altrimenti dubbio);
7. nessuna classe utile: con l'infobox film → film (media), altrimenti dubbio.

I valori `P31` sono stati interpretati guardando i titoli che raggruppano (per esempio `Q201658` raccoglie *Splatter*, *Cinepanettone*, *Film commedia*; `Q53710030` le USS Enterprise), non dalla memoria; i codici ora sono tabelle esplicite in `classify.py`. Dopo la regola ho **riletto a mano** titolo, generi e inizio trama di tutti i casi senza anno e dei dubbi, e preso 39 decisioni che correggono le regole (`audit/manual_review.py`, ognuna con la motivazione; ogni titolo corrisponde a un solo record, verificato dal codice). Non è una verifica esterna: è lettura del testo locale.

## 3. I 246 record senza anno [misurato / interpretato]

Elenco completo con `film_id`, titolo, sottotipo e motivo: `AUDIT_NOYEAR_246.md`.

| esito | n | di cui |
|---|---|---|
| **non sono film: serie** | 118 | 54 manga, 30 miniserie, 14 serie TV, 12 anime, 3 romanzi a puntate, 2 cinegiornali, 3 altro |
| **non sono film: articoli di argomento** | 50 | 25 generi, 5 liste, 4 oggetti di fantasia, 4 argomenti di cinema, 4 pagine su serie di film… |
| **non sono film: altre opere** | 4 | 2 opere letterarie, 1 balletto, 1 fumetto |
| **film** | 63 | 31 lungometraggi, 20 film per la TV, 4 animazione, 4 speciali TV, 2 cortometraggi, 2 documentari |
| **dubbi** | 11 | 4 OVA (*ÉX-Driver*, *Macross Plus*, *Armitage III*, *Maetel Legend*), 2 serie di film d'animazione (*Kara no kyōkai*, *Bungaku shōjo*), 3 progetti mai usciti (*Ronnie Rocket*, *Night Skies*, *The Works*), *Love Like Aliens*, *L'audacia degli X-Men* |

Quindi l'anno nullo è un buon indizio ma **non basta**: solo il 70% dei 246 non è un film, e 63 film veri (soprattutto film per la TV) hanno anno nullo perché Wikidata non ne registra la data. Di questi, **20 hanno l'anno nel titolo** ("Turandot (film 1974)", "Ruby (film 2021)") e potrebbe essere recuperato dal titolo (`anomalies.json`, `year_missing_but_in_title`). Il rovescio: 238 dei 246 sono entrati solo per la categoria (flag `no_infobox`), 2 per l'infobox.

## 4. I cinque casi eccezionali [misurato]

| film_id | titolo | token | verdetto | causa |
|---|---|---|---|---|
| Q36479 | *Il re leone* (1994) | 12.069 | **film valido** | trama contaminata: la sezione catturata include personaggi, produzione, uscita, DVD, accoglienza, remake |
| Q572165 | *Quinto potere* (1976) | 9.227 | **film valido** | idem (produzione, distribuzione, accoglienza, premi) |
| Q200092 | *Cinema dell'orrore* | 8.355 | **non è un film**: genere (`film_genre`) | articolo di storia del genere |
| Q229390 | *Cinema tridimensionale* | 11.554 | **non è un film**: tecnica (`film_technique`) | articolo sulla tecnica |
| Q970153 | *Attore bambino* | 21.896 | **non è un film**: professione (`occupation`) | articolo sul mestiere |

Cioè **due dei cinque erano film con un'estrazione errata, tre non sono film**. La causa dell'eccesso di lunghezza è la stessa per i due film veri (vedi sezione 5).

## 5. Difetto trovato nell'estrazione della Fase 1: sezioni accorpate [misurato]

`find_plot_section` (Fase 1) usa `mwparserfromhell.get_sections()`. Su alcune pagine (provato su *Il re leone* e *Quinto potere*, testo riletto dal dump locale) la libreria riconosce tutte le intestazioni (36 su 36) ma `get_sections()` restituisce solo 5 sezioni: la "Trama" assorbe tutte le sezioni sorelle fino a "Note". Per *Il re leone* la sezione catturata ha 73.377 caratteri di wikitext grezzo, contro circa 8.000 caratteri puliti della trama corretta.

Ho riletto il dump locale (≈19 minuti, nessuna rete) e rifatto la stessa estrazione su tutte le 41.421 pagine candidate, controllando se la sezione catturata contiene intestazioni di livello pari o superiore a quella della trama: **25 record contaminati (0,06%)**, tutti film veri. Con un taglio corretto la trama passa da 230.752 a 92.333 caratteri in totale; nessuno scenderebbe sotto i minimi di Fase 1. I casi peggiori: *Il re leone* 41.768 → 8.067 caratteri (2.469 token), *Quinto potere* 32.657 → 2.277 (640 token), *…e tu vivrai nel terrore! – L'aldilà* 22.299 → 6.553, *Exodus* 12.875 → 7.117, *Grease* 11.526 → 5.453. L'elenco con le trame corrette: `audit/synopsis_contamination.json` (le trame in `data/audit/section_fix.jsonl`).

Conseguenze: i due film veri entrano **interi in un embedding** (nessun chunk necessario); l'eccezione dei cinque film multi-chunk della Fase 3 sparirebbe del tutto. Rifare gli embedding dei 25 testi corretti costerebbe 27.042 token ≈ **0,0035 $** (misurato sui testi corretti, prezzo standard di `text-embedding-3-large`). Nessuno di questi 25 compare nelle top 10 delle 72 query della Fase 2 sulla collezione completa (misurato).

*Limite*: il controllo trova l'accorpamento di sezioni **sorelle** (stessa profondità o superiore). Non verifica altri difetti dell'estrazione né il contenuto delle trame corrette; una verifica sul testo corretto di una decina di casi è consigliabile prima di sostituirle.

## 6. Altre anomalie [misurato]

(`audit/anomalies.json`, con gli id.)

| controllo | esito |
|---|---|
| IMDb condiviso da più film | 2 coppie: *Apocalypse Now* / *Apocalypse Now Redux*; *Dreams Realized* / *In the Vale of Sorrow* (1915) |
| stesso titolo e anno | 1 coppia: *È primavera…* / *È primavera* (1950), probabile duplicato |
| trame identiche | 10 trame condivise da 66 film (remake/adattamenti, già noto) |
| anno nel titolo diverso dall'anno del record (>1) | 15 (per esempio *La Gioconda (film 1912)* con anno 1910) |
| anno nullo ma presente nel titolo | 20 (recuperabili) |
| anno dell'infobox lontano >3 anni da quello di Wikidata | 62 (segnale di pagina collegata all'elemento sbagliato; molti sono serie/manga) |
| regista dell'infobox senza alcuna parola in comune con quello di Wikidata | 234, ma per lo più traslitterazioni e produttori scritti come registi: **bassa gravità** |
| senza elemento Wikidata (`film_id` di ripiego `wp-…`) | 26 (dai primi esempi, per lo più film italiani recenti, anche documentari) |
| durata mancante / sotto 5 min / sopra 400 min | 3.624 / 118 / 17 (le 17 sopra 400 sono opere davvero lunghe, come *Heimat*, *Guerra e pace* e *Shoah*, o miniserie: non errori) |
| anno ≥ 2026 / prima del 1895 | 188 / 7 (cortometraggi del 1874–1894, legittimi) |
| sezione intitolata "Storia" (invece di "Trama") | 80 record: 51 solo-categoria e 29 con infobox; per verdetto 37 articoli di argomento, 33 film, 10 dubbi |
| regia / cast / IMDb mancanti | 665 / 4.029 / 492 |

Nota sulle trame molto lunghe: tra i verdetti `film`, le trame oltre 20.000 caratteri sono i due contaminati più alcuni film con trame davvero lunghe (*I dieci comandamenti*, *La meglio gioventù*, 21–25 k caratteri; non contaminati).

## 7. Impatto sul retrieval [misurato]

- Sulle 72 query narrative della Fase 2: **3 risultati su 720 (0,4%)** nella top 10 non sono film (la stessa miniserie *La donna del treno*, tre volte).
- Sulle richieste di genere o formato l'impatto è reale: "storia del cinema horror e dei suoi sottogeneri" → 3 articoli di argomento su 10 (*Cinema dell'orrore*, *Splatter*, *Analog horror*); "anime giapponese con ragazzi al liceo" → 5 serie su 10; "cinema muto delle origini" → 3 articoli su 10. È il comportamento atteso: un articolo che parla di un genere somiglia molto alla richiesta del genere.
- Il costo di tenerli: raccomandare *Splatter* o una miniserie come film. Il costo di toglierli: nessun film perso (i 259 non sono film), ma 71 dubbi da decidere.

## 8. Strategia di pulizia consigliata (da approvare, non applicata)

Principi: dataset originale intatto, lista esplicita di esclusi con motivo, ricostruzione possibile, ritorno indietro immediato.

1. **Mai modificare `films.jsonl`**: resta la fonte immutabile (SHA-256 nel manifest della Fase 1).
2. **Lista di esclusione versionata** (`audit/exclusions.json`, 259 record con `verdict`, `subtype`, `reasons`; più `audit/review_needed.json` per i 71 dubbi). La decisione sulle sotto-categorie è tua: per esempio le 63 miniserie potrebbero restare se le consideri film televisivi in più parti (ho scelto di escluderle perché la fonte stessa le classifica come miniserie).
3. **Correzione delle trame** per i 25 contaminati (`synopsis_contamination.json` / `section_fix.jsonl`): ricalcolo deterministico, nessuna modifica alla pipeline della Fase 1.
4. **Catalogo derivato**: un comando (da scrivere) produce `films.clean.jsonl` = `films.jsonl` meno gli esclusi, con le 25 trame corrette e i campi aggiuntivi `kind`, `subtype`, `needs_review`; il suo hash e quelli di sorgente, lista di esclusione e correzioni vanno in un manifest.
5. **Nuova collezione, non modifica della vecchia**: `wikipedia_films_it_v2` costruita dagli shard esistenti, riusando i vettori di ogni testo non cambiato (chiave: hash del testo) e facendo embedding solo dei 25 testi corretti (≈0,0035 $); punti attesi ≈ 41.162 (41.421 − 259, tutti a un vettore). Poi un **alias Qdrant** (`wikipedia_films`) punta alla versione attiva: passaggio e ritorno indietro in un'operazione, la vecchia collezione resta finché non decidi di toglierla.
6. **Scorciatoia reversibile (solo in attesa di 4–5)**: `set_payload` di un campo `excluded: true` sui 259 punti e `must_not` nei filtri di ricerca; non richiede embedding ma lascia le 25 trame contaminate.
7. **Verifiche dopo la ricostruzione**: `check` come in Fase 3, le 72 query della Fase 2 (P@5 e P@10 non devono calare), e le 8 richieste di genere della sezione 7 (gli articoli di argomento devono sparire dalle top 10).
8. **Per i 71 dubbi**: lasciarli nel catalogo ma segnalati (`needs_review`) e fuori dalle ricerche per default, finché non si decide. Una verifica incrociata con TMDb (`/find` per IMDb ID, già usata dal progetto per distinguere film e serie) risolverebbe molti dei 1.292 solo-categoria e dei dubbi, ma i Termini TMDb limitano l'uso con applicazioni AI (AGENTS.md): non la propongo senza una tua scelta.

## 9. Riproduzione

```bash
# dalla radice del repository (venv del progetto)
python -m pipelines.wikipedia_films.audit.section_scan   # rilegge il dump locale (≈19 min, nessuna rete) → data/audit/section_scan.jsonl, section_fix.jsonl
python -m pipelines.wikipedia_films.audit.anomalies      # audit/anomalies.json
python -m pipelines.wikipedia_films.audit.run_audit      # classificazione, esclusioni, dubbi, riepilogo e AUDIT_NOYEAR_246.md
python -m pytest pipelines/wikipedia_films/tests/test_audit.py -q
```


## 10. Obiettivo corretto: sostituzione del vecchio RAG, stime dopo la pulizia [misurato]

Il nuovo RAG sostituisce il vecchio; questo vale prima di ogni integrazione. Il vecchio resta intatto solo per confronti. Nessuna esclusione è applicata, Qdrant non è toccato, nessun embedding rifatto, nessuna API a pagamento.

**Stime distinte** (punti = 41.438 oggi, di cui 17 chunk extra: 12 delle tre voci non film, 5 dei due film con trama contaminata):

| Scenario | Record | Punti Qdrant |
|---|---|---|
| Oggi | 41.421 | 41.438 |
| A. Via solo i 259 certamente non film | 41.162 | 41.167 (41.162 dopo il taglio corretto delle 25 trame) |
| B. A più i 71 dubbi | 41.091 | 41.096 (41.091 dopo il taglio) |
| C. Solo esclusioni di confidenza alta (207) | 41.214 | 41.219 |

Raccomando A: i 71 dubbi restano nel catalogo, marcati, finché non decidi caso per caso (elenco in `audit/review_needed.json`: 16 manga, 12 film TV, 6 OVA, 6 anime, 5 lungometraggi, ecc.).

**Certi vs dubbi.** Certi non film: 259 (207 alta confidenza, 31 media, 21 decisi a mano dopo lettura). Dubbi: 71. Le 52 esclusioni non di alta confidenza vanno rilette da te se vuoi il massimo rigore. Le 63 miniserie sono televisione ma non film: le tengo tra gli esclusi certi, **decisione tua**.

**Non esclusi per principio**: cortometraggi (3.430), animazione (1.309), film TV (912), muti (209), documentari e speciali restano validi.

**Anno valorizzato ≠ film**: 63 serie, 17 altre opere e 7 voci di argomento hanno un anno, più 60 dubbi. Il controllo vale per l'intero catalogo, non solo per i 246.

**Controlli sull'intero dataset (41.091 film)**: nessuna trama sotto 100 caratteri; 62 titoli con parole come «cinema», «festival», «lista» ispezionati: film veri (es. *Nuovo Cinema Paradiso*, *Schindler's List*). Restano 27 film senza P31 Wikidata e 1.319 film di confidenza non alta (735 film TV, 301 lungometraggi, 180 animazione) da campionare.

**Procedura riproducibile proposta**
1. `films.jsonl` e lo snapshot restano intatti.
2. `python -m pipelines.wikipedia_films.audit.run_audit` rigenera classificazione ed `exclusions.json` (con motivo, regole e 39 decisioni manuali versionate).
3. Un comando deterministico produce `films.clean.jsonl` con trame corrette per le 25 pagine e la lista esclusioni; verifica offline byte per byte.
4. Nuova collezione `wikipedia_films_it_v2` da shard esistenti (solo i 25 testi cambiati costano ≈ 0,0035 USD, da autorizzare), alias per scambio e ritorno.
5. Controlli dopo la ricostruzione: `check`, 72 query, query di genere/formato.
6. Reversibilità: togliere un id dalla lista e ricostruire; la v1 resta.

**Cambiamenti rispetto all'integrazione.** Spariscono fusione, crosswalk e doppia fonte. Restano da progettare, ma non ora: adattare `rag_search` al nuovo indice (query in italiano, nessuna `semantic_query` inglese), la regola di routing 3 e `data_coverage.py` («fermo al 2012»), il reranker e i metadati TMDb. Prima serve una valutazione di qualità nuovo-vs-vecchio su query reali, per sapere se perdere il vecchio corpus fa perdere qualcosa.
