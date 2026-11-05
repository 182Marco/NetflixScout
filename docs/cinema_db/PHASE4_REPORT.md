# Fase 4 — arricchimento mirato da Wikidata (2026-11-05)

Risultati misurati sul file reale. Riproduzione: `python -m cinema_db.harness.enrich.fetch plan|status|run`, `python -m cinema_db.harness.build.build --force`, `python -m cinema_db.harness.enrich.compare PRIMA DOPO`. Il confronto è con la build della fase 3 (`build --no-phase4`, digest `d9d475d7…`, identico a quello registrato: la build senza snapshot della fase 4 è rimasta byte per byte quella di prima).

## 1. Cosa è stato richiesto
**1.129 richieste** a Wikidata (autorizzate dal proprietario), tutte riuscite, **nessuna fallita** (20 ritentate dopo 502 o `maxlag`); 526 MB di risposte originali (59 MB compressi) in `cinema_db/data/wikidata_phase4/` (stesso formato degli snapshot dei progetti film e serie: `requests.jsonl` + `bodies/<sha256>.json.gz`, letto da `build/snapshot.py`; ignorato da git, mai modificato dopo la scrittura). Dalle 20:53 alle 22:11 UTC, una richiesta alla volta, almeno 1,2 s tra l'una e l'altra, `maxlag=5`, `Retry-After` rispettato, interruttore dopo 4 fallimenti di fila; User-Agent col solo repository (nessuna e-mail).

| Categoria | Richieste | Elementi | Risposta |
|---|---|---|---|
| persone (SPARQL: etichette it/en/mul, nascita, morte con precisione e rango) | 712 (243 senza nome + 469 già nominate, per le date) | 142.156 | 222 MB |
| premi, categorie, cerimonie | 56 + 4 (premi madre dedotti dai dati) | 2.780 + 174 | 28 MB |
| società | 118 | 5.879 | 81 MB |
| bersagli delle relazioni | 174 | 8.678 | 1 MB |
| franchise | 21 | 1.002 | 0,1 MB |
| luoghi di uscita | 22 | 1.093 | 66 MB |
| paesi / lingue / valute | 4 / 6 / 1 | 194 / 270 / 42 | 90 / 12 / 3 MB |
| elementi usati sia come persona sia come società (classe) | 11 | 534 | 24 MB |

La stima di SURVEY era 1.031 richieste per il minimo e 3.119 per tutto; con 200 persone a richiesta (SPARQL) invece di 50 il completo è costato 1.129. Il minimo utile (premi, valute, persone senza nome) ne ha richieste 300 ed è stato misurato prima di proseguire.

## 2. Copertura aggiunta (prima = fase 3, dopo = fase 4)
| Misura | Prima | Dopo | Differenza |
|---|---|---|---|
| persons | 92,041 | 141,645 | +49,604 |
| persons_with_birth_date | 0 | 113,171 | +113,171 |
| persons_with_death_date | 0 | 40,550 | +40,550 |
| credits | 532,504 | 675,327 | +142,823 |
| credits_writer | 30,240 | 51,217 | +20,977 |
| credits_composer | 7,457 | 31,842 | +24,385 |
| credits_cinematographer | 5,335 | 25,440 | +20,105 |
| credits_editor | 3,757 | 19,086 | +15,329 |
| credits_producer | 16,051 | 37,061 | +21,010 |
| credits_cast | 416,981 | 441,298 | +24,317 |
| credits_director | 48,704 | 52,097 | +3,393 |
| films_with_writer | 20,329 | 28,087 | +7,758 |
| films_with_composer | 6,356 | 23,960 | +17,604 |
| films | 36,529 | 36,529 | +0 |
| awards | 0 | 1,060 | +1,060 |
| award_categories | 0 | 1,785 | +1,785 |
| ceremonies | 0 | 5,506 | +5,506 |
| award_results | 0 | 27,751 | +27,751 |
| award_results_won | 0 | 7,623 | +7,623 |
| works_with_an_award_result | 0 | 6,134 | +6,134 |
| countries | 183 | 229 | +46 |
| countries_with_iso2 | 0 | 179 | +179 |
| languages | 246 | 270 | +24 |
| languages_with_iso639_1 | 0 | 112 | +112 |
| financial_rows | 9,212 | 10,162 | +950 |
| financial_rows_not_usd | 0 | 950 | +950 |
| currencies | 1 | 38 | +37 |
| companies | 1,109 | 6,715 | +5,606 |
| companies_with_country | 0 | 4,346 | +4,346 |
| work_company | 8,490 | 103,155 | +94,665 |
| franchises | 86 | 1,071 | +985 |
| work_franchise | 198 | 5,107 | +4,909 |
| work_relation | 4,703 | 15,311 | +10,608 |
| work_relation_based_on | 1,638 | 10,513 | +8,875 |
| work_relation_follows | 3,065 | 4,798 | +1,733 |
| works | 293,447 | 301,860 | +8,413 |
| work_release | 50,740 | 51,028 | +288 |
| names | 739,048 | 804,772 | +65,724 |
| field_provenance | 0 | 158,067 | +158,067 |

Dei **144.630 crediti scartati** in fase 3 perché senza nome ne sono stati recuperati **142.823** (99 %): restano 154 persone senza etichetta in it/en/mul (conteggiate per ruolo nel rapporto della build) e le organizzazioni (vedi §4). Persone con data di nascita 113.171 su 141.645 (80 %), di morte 40.550; nessuna data è un valore indovinato (§3).

## 3. Regole e decisioni (tutte con test in `tests/test_cinema_build_phase4.py`)
- **Nessuna sovrascrittura**: i nomi delle fonti vecchie (etichette degli snapshot, catalogo) vengono prima; solo in mancanza di quelli si usa l'etichetta della fase 4 (it, poi en, poi `mul` senza lingua). Ogni nome porta la sua fonte (`wikidata-phase4-targeted`: 65.674 nomi).
- **Date di vita**: da `psv:` con precisione e rango; deprecate ignorate, preferita batte normale, la stessa data a precisioni diverse si risolve nella più precisa, **date diverse = ambiguo, non importato** (3.184 nascite e 1.589 morti: dato ambiguo, mai scelto a caso); precisione sotto l'anno o anno fuori da 1000–2100 scartati; morte prima della nascita: nessuna delle due. Provenienza in `field_provenance` (158.067 righe, con la data di acquisizione).
- **Premi**: premio madre = primo P361 della categoria (senza, la categoria è il proprio premio); categoria `person_for_work` se almeno un'asserzione ha il candidato (P2453), altrimenti `work` (derivato dai dati); cerimonia = l'elemento (P805), altrimenti l'anno dell'asserzione (la cerimonia con premio e anno uguali a un solo elemento viene riusata, 809 casi); senza cerimonia né anno **non si importa** (1.681 asserzioni contate); un risultato sia «vinto» sia «candidato» sulla stessa chiave tiene «vinto» (1.446, la chiave del database non contiene l'esito); nessun premio, categoria o cerimonia esiste senza un risultato (controllato). 27.751 risultati (7.623 vinti), 1.060 premi, 1.785 categorie, 5.506 cerimonie (4.811 solo da anno, senza edizione), 6.134 opere con almeno un risultato.
- **Importi**: nella valuta originale, codice ISO 4217 letto da Wikidata (P498) solo se unico; **nessuna conversione**: 950 righe in 37 valute; 11 importi restano fuori (unità senza codice unico o non una valuta, es. un paese usato come unità).
- **Paesi e lingue**: ISO 3166-1 alpha-2 su 179 paesi su 229, ISO 639-1 su 112 lingue su 270 (codici non unici o ripetuti non importati e contati). Un luogo di uscita diventa paese solo se Wikidata lo classifica paese o stato sovrano (46 paesi aggiunti, 288 uscite in più); festival e città (la grande maggioranza dei 6.106 luoghi non riconosciuti) non sono paesi e restano una lacuna dichiarata.
- **Società, franchise, relazioni**: i nomi arrivano dalla fase 4 (6.715 società, di cui 4.346 con paese da P17/P495 se non ambiguo; 1.071 franchise; 8.657 opere-bersaglio di relazioni «altro» con la loro etichetta).
- **Provenienza**: ogni riga conserva fonte e QID (`source_ref`); i risultati di premio restano attribuiti allo snapshot del film o della serie, i nomi, le date, i codici ISO e le righe di premio madre/categoria/cerimonia alla fase 4. Il paese e la lingua con codice dalla fase 4 hanno come fonte la fase 4 (le tabelle non hanno `field_provenance`).

## 4. Problemi trovati dalla verifica e corretti
1. **Organizzazioni come persone**: i nomi della fase 4 mostravano grandi società (Netflix, Warner Bros., Paramount) anche come «produttore» di persone: lo stesso QID come persona e come società (conflitti di identificativo da 180 a 439, duplicati). Regola: un elemento sia accreditato sia elencato come società è una **organizzazione**, salvo che Wikidata lo dica umano (P31 Q5). Misurato su 534 elementi (11 richieste): **164 sono persone** (Douglas Fairbanks, Georges Méliès, Jesse L. Lasky) e restano persone; per loro l'asserzione di società non si importa (277). Le altre 370 sono organizzazioni: 176 crediti «producer» e gli altri ruoli non diventano persone. Conflitti di QID finali 184 (180 in fase 3: i 4 in più sono opera/franchise).
2. Una categoria di premio nasceva senza risultati (candidato solo un'organizzazione): ora le asserzioni si controllano prima di creare qualsiasi cosa.
3. Chiave di unicità delle cerimonie (premio, anno, edizione) violata da due elementi con la stessa etichetta: un solo punto crea le cerimonie e li unisce (contato).

## 5. Tipo di uscita per paese (misura, nessuna modifica allo schema)
Dei 80.191 enunciati di data di pubblicazione dello snapshot film, 46.249 hanno il luogo; i qualificatori: P437 «formato di distribuzione» 1.067 (1,3 %; DVD, digitale…), nessun qualificatore del **tipo** (prima, sala, festival, streaming). Wikidata non fornisce il dato: lo schema (`work_release.kind`, oggi `unspecified`) **non cambia** e la colonna resta com'è finché non c'è una fonte che lo dica.

## 6. Verifiche
Offline e gratuite: `foreign_key_check` 0, `integrity_check` ok, FTS5 coerente, un solo nome primario per entità (tutte le entità, premi compresi), nessun credito duplicato, nessun QID Wikidata duplicato, nessuna categoria/cerimonia/premio orfani, nessuna riga senza fonte; la build **senza** snapshot della fase 4 dà ancora il digest della fase 3 `d9d475d7…`; la build con la fase 4: digest `b3b0de51…` (ricostruzione e verifica indipendente: `PHASE4_BUILD_REPORT.md`). Test: `tests/test_cinema_enrich.py` (13, client e archivio, trasporto finto, nessuna rete) e `tests/test_cinema_build_phase4.py` (21). Nessuna chiamata OpenAI o embedding; IMDb non importato; MovieLens, RAG e gli altri tool non toccati.

## 7. Limiti
- Una singola data per persona non è verificata contro un'altra fonte: è ciò che Wikidata dichiara (3.184 nascite ambiguità non risolte, non scelte).
- Il nome di 154 persone manca (nessuna etichetta it/en/mul); i luoghi festival/città non producono uscite per paese; 1.681 asserzioni di premio senza cerimonia né anno e 115 candidati senza nome non sono importati; 178 asserzioni puntano a elementi premio non presenti nello snapshot.
- Categorie di premio a livello di Wikidata: la gerarchia (premio madre, serie di cerimonie) è quella di P361/P179 e i premi madre possono avere più genitori (52, usato il primo); una stessa istituzione può comparire con due elementi.
- Le cerimonie senza elemento (4.811) non hanno edizione né data.
- La data di acquisizione e le cifre dipendono dallo stato di Wikidata il 2026-11-05; le richieste non si ripetono (ripresa), quindi un aggiornamento richiede un nuovo snapshot.
- Premi e persone riguardano il catalogo locale (film del catalogo e serie con QID affidabile), non tutto il cinema.

## 8. Decisioni per il proprietario
Proseguire verso la **Fase 5** (tool `cinema_sql`); fusione dei duplicati di Wikidata (184 conflitti di QID, 240 film in due QID); eventuale snapshot di aggiornamento; licenza del vocabolario dei generi; distinzione organizzazione/persona per i crediti rimasti (370 organizzazioni escluse dalle persone, i loro crediti `producer` non sono rappresentati: eventuale ruolo «produzione» verso la società).
