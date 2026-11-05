# Indagine prima della build offline (fase 3)

Generata da `python -m cinema_db.harness.build.survey` leggendo **solo file locali** (nessuna rete, nessun credito). Tutti i numeri sono conteggi sui dati reali, tranne le righe indicate come stima.

## 1. Fonti locali

- Catalogo film v3: **41,138** film; snapshot Wikidata film: **41,395** entità (41,115 nel catalogo, 280 no), 149,026 etichette, 1,676 richieste originali (acquisite 2026-11-03 – 2026-11-04).
- Catalogo serie s5: 15,697 serie, 15,032 stagioni (4,175 logiche), 78,705 episodi con trama + 147,249 righe-episodio solo metadati, 2,578 film TV; snapshot Wikidata serie: 32,412 entità.

## 2. Copertura dei campi nei film (su opere del catalogo presenti nello snapshot)

- Titolo italiano (etichetta): 41,068 (99.9%)
- Data di pubblicazione: 40,521 (98.6%)
- … con il luogo della pubblicazione (uscita per paese): 14,620 (35.6%)
- Durata (snapshot): 35,269 (85.8%)
- Generi: 38,795 (94.4%)
- Paesi: 40,945 (99.6%)
- Lingue: 33,308 (81.0%)
- Società di produzione/distribuzione: 29,488 (71.7%)
- Pagina Wikipedia it: 41,115 (100.0%)
- Relazioni con altre opere: 8,951 (21.8%)
- Franchise/serie: 3,566 (8.7%)
- Incassi o budget: 5,666 (13.8%)
- Premi o candidature: 6,072 (14.8%)
- Almeno un ruolo professionale: 40,207 (97.8%)
- Identificativi: imdb_title 40,801 (99.2%), tmdb_movie 38,764 (94.3%), tmdb_tv 97 (0.2%), tvdb_series 129 (0.3%), eidr 35,416 (86.1%)

## 3. Persone e crediti

- Persone distinte nei ruoli dei film e delle serie: **119,539** (film); con un nome già disponibile offline: **91,906**.

| Ruolo | Crediti | Con persona già nominata | Persone distinte | Nominate |
|---|---|---|---|---|
| director | 43,046 | 42,999 | 13,344 | 13,319 |
| writer | 47,610 | 29,342 | 15,915 | 8,156 |
| cast | 363,446 | 359,490 | 83,281 | 81,598 |
| composer | 27,023 | 6,826 | 5,746 | 903 |
| cinematographer | 24,455 | 5,240 | 4,051 | 680 |
| editor | 18,510 | 3,710 | 3,674 | 871 |
| producer | 35,261 | 15,425 | 10,229 | 4,036 |
| production_designer | 7,388 | 1,267 | 1,559 | 249 |
| costume_designer | 4,618 | 751 | 1,021 | 118 |
| creator | 319 | 285 | 234 | 205 |

I nomi offline vengono dalle etichette dello snapshot e dal catalogo (registi e attori): gli altri ruoli (sceneggiatori, compositori, fotografi, montatori, produttori) hanno solo il QID e **non si importano** finché la fase 4 non ne legge il nome (un credito senza nome non è utile e non si inventa).

## 4. Vocabolari, società, relazioni, franchise

- Generi: 547 voci distinte, 546 con etichetta; 81,832 di 81,833 asserzioni etichettate; testi distinti nel catalogo: 593.
- Paesi: 181 voci (181 etichettate); lingue: 245 (245 etichettate).
- Società: 4,398 distinte, 100 con nome (68,488 asserzioni).
- Relazioni: based_on 6,726 (bersaglio noto 894), followed_by 2,573 (bersaglio noto 1,946), derivative 1,049 (bersaglio noto 347), follows 2,085 (bersaglio noto 1,836); bersagli distinti 9,702, senza etichetta 6,009.
- Franchise: 887 distinti, 48 con nome; film con `franchise_id` nel catalogo: 4,049.

## 5. Premi, incassi, uscite per paese

- Premi: 23,230 asserzioni (8,137 vinti, 15,093 candidature) su 6,072 film; 1,685 premi/categorie distinti (**0 con nome**); 21,113 con anno; 12,783 con cerimonia (653 distinte, 4 nominate); 10,457 con la persona candidata (7,295 persone).
- Incassi e budget: 10,223 asserzioni su 5,666 film (5,476 incassi, 4,747 budget); USD (Q4917): 9,261; unità distinte 43; con luogo 3,695, con data 295.
- Date di pubblicazione: 80,050, di cui 46,241 con il luogo (1,230 luoghi distinti, 146 nominati).

## 6. Serie

- Serie con QID 15,675, con QID **affidabile** 13,217; presenti nello snapshot: 15,675 (13,217 affidabili). Il QID non affidabile non si usa per importare fatti da Wikidata.
- Stagioni con numero 14,999; episodi numerati 54,261 su 78,705; persone nelle serie dello snapshot: 53,764 (28,042 nominate).

## 7. Fabbisogno stimato per la fase 4 (richieste Wikidata mirate, 50 id per richiesta; STIMA, nulla è stato richiesto)

| Tipo | Entità | Richieste |
|---|---|---|
| Persone senza nome (sceneggiatori, compositori, ...) | 49,137 | 983 |
| Tutte le persone: date di vita, paese, ID IMDb/TMDb | 141,189 | 2,824 |
| Bersagli delle relazioni senza etichetta | 6,009 | 121 |
| Franchise senza nome | 839 | 17 |
| Società senza nome | 4,298 | 86 |
| Premi, categorie e cerimonie | 2,317 | 47 |
| Unità monetarie (codice ISO 4217) | 43 | 1 |
| Generi/paesi/lingue senza etichetta | 1 | 1 |
| Luoghi di uscita senza nome | 1,084 | 22 |

Minimo (nomi delle persone mancanti + premi + valute): **1,031** richieste. Completo (tutto ciò che sopra): **3,119** richieste. A 1 richiesta al secondo sono circa 0.9 ore; le risposte pesano 0,3–4 MB ciascuna (snapshot film: 344 MB per 829 richieste di entità).

## 8. IMDb: il massimo che potrebbe aggiungere (limite superiore, nulla è stato importato)

- Film del catalogo senza ID IMDb (non agganciabili senza corrispondenza per titolo): 337.

| Campo mancante | Film senza il dato | … con ID IMDb (agganciabili) | … senza ID IMDb |
|---|---|---|---|
| year | 70 | 50 | 20 |
| runtime | 3,397 | 3,293 | 104 |
| director | 522 | 473 | 49 |
| cast | 3,820 | 3,680 | 140 |
| genres | 262 | 220 | 42 |
| original_title | 2,480 | 2,296 | 184 |

Sceneggiatori e compositori mancano in Wikidata per 11,096 e 15,473 film, ma i dataset IMDb non sono stati letti: **la copertura reale che IMDb aggiungerebbe non è misurabile senza scaricarli** (vietato in questa fase) e va subordinata alle condizioni d'uso.
