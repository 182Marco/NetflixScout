# Fase 6: decisioni individuali, verifica delle esclusioni e dello script di pulizia

Stato: **solo proposte e strumenti.** Nessuna esclusione in vigore oltre alle 259 già decise, `films.jsonl`, embedding e collezioni Qdrant invariati, nessuna chiamata a pagamento, nessun commit. Le decisioni sono letture mie di testo, infobox e classi Wikidata, non verifiche su fonti esterne: la colonna «fiducia» lo dice.

File nuovi in `tool/RAGWikipediaFilm/`: `audit/decisions.py` e `audit/decisions.json` (le tabelle sotto), `audit/build_clean.py` (lo script), `audit/section_detail.py` (verifica delle 25 trame), `audit/plan_overrides.proposed.json` (lo scenario consigliato, **non in vigore**), `tests/test_build_clean.py`.

## 1. I 27 dubbi (11 da escludere + 16 in sospeso), riletti

Rileggendo gli infobox ho trovato un fatto che cambia il quadro: nelle pagine di serie anime (*Digimon*, *Marmalade Boy*, *Hana yori dango*, *Tsurune*, *Baldios*…) l'infobox «Film» non descrive la serie ma **un film collegato** (per esempio «Digimon Savers The Movie» da 20 minuti, «Tsunagari no issha» da 102 minuti). La trama della pagina è invece quella della serie. È un limite dell'estrazione della Fase 1 (basta un infobox Film nella pagina), non solo un errore dei dati.

Conseguenza: escluderle toglie la **serie** dal catalogo ma fa perdere anche i **film** collegati come voci autonome (sono 9 casi circa). Recuperarli richiederebbe di estrarre la trama del film dalla sezione giusta: non è fatto.

Esito dopo la rilettura: **escludere 18** (gli 11 di prima più 7 che erano in sospeso: *Hana yori dango*, *Baldios*, *Hiyokoi*, *Code Geass: Akito the Exiled*, *Kara no kyōkai*, *The Works*, *Il mio matrimonio felice*), **in sospeso 8**, **includere 1** (*Dive!!*, film live-action).

| Titolo | Anno | Natura dell'opera | Decisione (fiducia) | Motivazione | Conseguenza |
|---|---|---|---|---|---|
| Baldios - Il guerriero dello spazio | 1981 | serie anime (l'infobox descrive «Baldios – The Movie») | **escludere** (media) | la trama cita puntate e serie | si perde il film come voce autonoma |
| Code Geass: Akito the Exiled | 2012 | OVA di 5 episodi | **escludere** (media) | l'infobox dà «60 min (episodio) / 300 min (totale)» | nessuna; la raccolta in film non è descritta dalla pagina |
| Cortili del cuore | 1996 | serie anime (l'infobox descrive il film del 1996) | **escludere** (media) | trama di serie TV; nessuna durata | si perde il film Gokinjo Monogatari come voce autonoma |
| Digimon Adventure 02 | 2000 | serie anime (l'infobox descrive il film del 2000, 65 min) | **escludere** (alta) | trama della serie TV Digimon Adventure 02 | si perde il film come voce autonoma |
| Digimon Savers | 2006 | serie anime (l'infobox descrive il film «The Movie», 20 min) | **escludere** (alta) | trama della serie TV Digimon Savers | si perde il film come voce autonoma |
| Digimon Tamers | 2001 | serie anime (l'infobox descrive il film del 2001, 50 min) | **escludere** (media) | trama della serie TV Digimon Tamers | si perde il film come voce autonoma |
| Generation War | 2013 | miniserie tedesca in 3 puntate | **escludere** (alta) | l'infobox dà «135 min (episodio)» | nessuna |
| Hana yori dango | 1997 | serie anime (l'infobox descrive il film del 1997, 30 min) | **escludere** (media) | 3.774 caratteri di trama della serie TV Toei | si perde il film come voce autonoma |
| Hiyokoi | 2010 | serie anime breve (22 min) | **escludere** (media) | regista e produttore solo di serie; nessun IMDb | nessuna perdita certa |
| Il mio matrimonio felice | 2019 | romanzo/manga/anime (la trama è del romanzo) | **escludere** (bassa) | pagina di franchise letterario | il film live-action del 2023 non compare |
| Kara no kyōkai | – | pagina sulla saga di 7 film | **escludere** (bassa) | è una pagina di serie di film, trattata come argomento come le altre 9 | i singoli film non sono voci; coerente con «Saw (serie di film)» |
| La recta provincia | 2007 | miniserie TV cilena di Raúl Ruiz | **escludere** (media) | uscita come serie TV; trama di 610 caratteri | un'opera d'autore di Ruiz non compare |
| Marmalade Boy | 1995 | serie anime (l'infobox descrive il corto del 1995, 26 min) | **escludere** (media) | la trama è quella della serie TV; il corto «Quello stesso giorno a casa di Yū» esiste ma non è descritto dalla pagina | si perde il corto come film; la serie non compare tra i film |
| Night Skies | – | seguito mai realizzato | **escludere** (alta) | descrive un progetto, non un'opera | come sopra |
| Ronnie Rocket | – | film mai realizzato (Lynch) | **escludere** (alta) | descrive un progetto, non un'opera visibile | la ricerca non potrà più proporre un film che non esiste |
| SuperDoll Rika-chan | 1999 | serie anime (l'infobox descrive il film del 1999) | **escludere** (alta) | trama della serie TV, 30 min = episodio | si perde il film come voce autonoma |
| The Works (film) | – | film d'animazione incompiuto (1984, non uscito) | **escludere** (media) | non esiste un'opera fruibile; è una voce storica | nessuna per l'utente |
| Tsurune | 2016 | serie anime (l'infobox descrive il film del 2022, 102 min) | **escludere** (media) | la sinossi inizia con «La serie parla…» | si perde il film come voce autonoma |
| Bungaku shōjo | – | saga/franchise anime (film del 2010 e serie) | **sospeso** (bassa) | 432 caratteri di trama, nessun dato | se escluso si perde al più un film d'animazione |
| Esterno notte (film) | 2022 | serie di Bellocchio uscita in sala come due film (330 min) e in TV come miniserie in 6 puntate | **sospeso** (media) | è la tua regola sulle miniserie a decidere; l'infobox è del film | incluso: opera d'autore presente, ma è una miniserie; escluso: assente |
| Look Back | 2021 | manga one-shot (2021) e film d'animazione (2024) nella stessa pagina | **sospeso** (bassa) | la trama vale per entrambi; l'anno è quello del manga | incluso: il film esiste; ma l'anno è sbagliato |
| Love Like Aliens | – | anime, tipo non determinabile | **sospeso** (bassa) | nessun dato (regista, durata, IMDb) | voce senza dati: bassa utilità comunque |
| Macross Plus | – | OVA di 4 episodi (esiste una versione film) | **sospeso** (bassa) | nessun infobox; IMDb presente | come sopra |
| Maetel Legend - Sinfonia d'inverno | – | OVA speciale (verosimilmente un solo episodio) | **sospeso** (bassa) | 6.359 caratteri di trama, IMDb presente, nessuna durata | se incluso è probabilmente corretto |
| Mobile Suit Gundam 0083: Stardust Memory | 1992 | OVA di 13 episodi (esiste anche il film montato) | **sospeso** (media) | serve la tua regola sugli OVA: la pagina è l'OVA, l'infobox il film | incluso: una serie OVA appare come film; escluso: manca un'opera del franchise |
| ÉX-Driver | – | OVA a episodi | **sospeso** (bassa) | nessuna durata né infobox; IMDb e regista presenti | se incluso compare come film un OVA a più episodi; se escluso nessuna perdita certa |
| Dive!! | 2008 | film live-action del 2008 (regia e 13 attori nell'infobox) | **includere** (media) | Wikidata lo dà come serie di romanzi, la pagina è del film | nessuna |

## 2. I 46 ibridi film/serie

Nessuna regola automatica: ho letto durata, regista, infobox e struttura di ciascuno. Il criterio è quello che hai dato (film TV sì, miniserie no) e ho usato un solo indicatore oggettivo ulteriore: **«in onda in due serate»**. Esito: **escludere 14, includere 23, in sospeso 9**. Il punto aperto è proprio la categoria «film TV in due parti» (*Karol – Un papa rimasto uomo*, *Alice nel Paese delle Meraviglie* 1999, *Il mondo sul filo*): lì serve una tua regola, che poi applico a tutti allo stesso modo (inclusi *Karol – Un uomo diventato papa* e i *Fantaghirò*, che oggi restano tra i film).

| Titolo | Anno | Natura | Decisione (fiducia) | Motivazione |
|---|---|---|---|---|
| Aftershock - Terremoto a New York | 1999 | miniserie NBC in due parti | **escludere** (media) | 170 minuti in due serate |
| Atomic Train - Disastro ad alta velocità | 1999 | miniserie NBC in due parti | **escludere** (media) | 164 minuti in due serate |
| Attila, l'unno | 2001 | miniserie USA Network in due parti | **escludere** (media) | 177 minuti in due serate |
| Fingersmith | 2005 | miniserie BBC in 3 puntate | **escludere** (alta) | nessuna durata |
| Heimat (film) | 1984 | serie TV in 11 parti (Heimat) | **escludere** (alta) | 924 minuti |
| I Nicotera | 1972 | sceneggiato in più puntate | **escludere** (alta) | la trama dice «Lo sceneggiato narra…» |
| I guardiani del cielo | 2004 | miniserie RAI in due parti | **escludere** (media) | nessuna durata |
| Il processo di Norimberga | 2000 | miniserie in due parti (TNT) | **escludere** (media) | 180 minuti trasmessi in due serate |
| La storia di Anne Frank | 2001 | miniserie ABC in due parti | **escludere** (media) | 189 minuti in due serate |
| Naso di cane | 1986 | sceneggiato TV italiano (Squitieri) | **escludere** (bassa) | sceneggiato in più puntate secondo Wikidata; nessuna durata |
| Padre Pio - Tra cielo e terra | 2000 | miniserie RAI in due parti | **escludere** (media) | nessuna durata |
| Pat, la ragazza del baseball | 1977 | serie anime TV | **escludere** (media) | nessun infobox, nessuna durata |
| Rebecca (film 1979) | 1979 | miniserie BBC in 4 puntate | **escludere** (media) | 55 minuti = episodio |
| Uccelli di rovo | 1983 | miniserie in 4 puntate (Uccelli di rovo) | **escludere** (alta) | è l'esempio tipico |
| Alice nel Paese delle Meraviglie (film 1999) | 1999 | film TV NBC in due parti (150 min) | **sospeso** (media) | evento in due serate |
| Anna dai capelli rossi - Il sequel | 1987 | film TV canadese in due parti (230 min) | **sospeso** (media) | la pagina lo chiama «film», ma è andato in onda in due serate |
| Come Yukong spostò le montagne | 1976 | ciclo documentaristico di Joris Ivens in 12 parti (763 min) | **sospeso** (media) | la pagina italiana lo tratta come film |
| Errore fatale (film 1992) | – | film TV italiano sull'AIDS (200 min) | **sospeso** (bassa) | durata da miniserie, titolo «film» |
| Fascist Legacy | 1989 | documentario BBC in due puntate | **sospeso** (bassa) | documentario televisivo; manca la durata |
| Il mondo sul filo | 1973 | film TV di Fassbinder in due parti | **sospeso** (media) | considerato un film d'autore; 212 minuti in due puntate |
| Karol - Un papa rimasto uomo | 2006 | film TV in due parti (155 min) | **sospeso** (media) | lo stesso caso di «Karol – Un uomo diventato papa» (180 min), che oggi resta tra i film |
| Ritratto di donna velata | 1975 | sceneggiato RAI (1975) | **sospeso** (bassa) | nessun dato di durata; non è chiaro se in più puntate |
| Sukeban deka | 1987 | serie o film live-action Sukeban Deka | **sospeso** (bassa) | nessun dato di regia né durata |
| 102 Boulevard Haussmann | – | film TV francese | **includere** (media) | film televisivo |
| Amore di perdizione | 1978 | film di Manoel de Oliveira (262 min) | **includere** (alta) | distribuito al cinema, esiste una versione in 6 puntate |
| Andersonville (film) | 1996 | film TV TNT (167 min) | **includere** (media) | infobox film presente |
| Anne of Green Gables: A New Beginning | 2008 | film TV (2008) di 144 minuti | **includere** (media) | un solo film |
| Bravo Two Zero (film) | 1999 | film TV BBC (114 min) | **includere** (media) | un solo film |
| Carlo e Diana - Una storia d'amore | 1982 | film TV (1982) | **includere** (media) | singolo film TV |
| Conversazioni private | 1996 | film di Liv Ullmann (200 min, 5 parti) | **includere** (media) | infobox film; nella versione italiana tagliato |
| Crusher Joe | 1983 | film d'animazione del 1983 (132 min) | **includere** (media) | infobox film con regista |
| Demon City Shinjuku, la città dei mostri | – | OVA di lungometraggio di Kawajiri | **includere** (media) | singola opera di circa 80 minuti |
| Emel'jan Pugačёv | 1979 | film sovietico | **includere** (alta) | film per il cinema |
| Fujimi-nichōme kōkyō gakudan | 2012 | film live-action (83 min) | **includere** (media) | infobox film con regista |
| L'isola misteriosa (film 2005) | 2005 | film TV (172 min) | **includere** (media) | singolo film Hallmark |
| LEGO Jurassic World: L'evasione di Indominus Rex | 2016 | speciale TV animato di 22 minuti | **includere** (media) | un solo speciale |
| Mesih | 2007 | film iraniano (100 min) | **includere** (bassa) | infobox film |
| Miss Marple nei Caraibi (film) | 1983 | film TV (92 min) | **includere** (alta) | un solo film |
| Oblomov (film) | 1980 | film di Michalkov | **includere** (alta) | film per il cinema |
| Phantom Blood | 2007 | film del 2007 (91 min) | **includere** (media) | infobox film con regista |
| Riphagen | 2016 | film olandese del 2016 (130 min) | **includere** (media) | esiste anche una versione serie |
| Sweet Poolside | 2004 | film del 2004 (103 min) | **includere** (media) | infobox film con regista |
| Tomie: Another Face | 1999 | film in tre episodi (72 min) | **includere** (media) | film compilation, non una serie |
| Un mare di guai (film 1995) | – | film TV (Bob Clark) | **includere** (media) | un solo film |
| Unge Andersen | 2005 | film TV danese (120 min) | **includere** (media) | infobox film |
| È solo acqua e vento | – | documentario | **includere** (media) | documentario unico |

## 3. Le 259 esclusioni certe: non tutte lo sono

Ho riletto tutte le 259 contro il rischio di aver escluso film veri. **251 reggono. Otto sono da rivedere**, e il difetto è sistematico: la regola «classe Wikidata = opera letteraria o videogioco ⇒ non film» ha escluso 7 pagine che hanno un infobox Film, regista e spesso durata, più un caso di speciale TV.

| Titolo | Anno | Decisione (fiducia) | Motivo |
|---|---|---|---|
| Tsumi no yohaku | 2012 | **includere** (alta) | film giapponese del 2012 (122 min, regista, IMDb, infobox film): Wikidata lo dà come opera letteraria |
| Kurai tokoro de machiawase | 2006 | **includere** (alta) | film giapponese del 2006 (130 min, regista, infobox film): stessa causa |
| Gli amori di Suzanna Andler | 2021 | **includere** (alta) | film di Benoît Jacquot del 2021 (91 min, infobox film): stessa causa |
| Another | 2009 | **sospeso** (media) | Another: infobox film con regista ma l'anno 2009 è del romanzo; il film live-action è del 2012 |
| Il vento dell'Amnesia | 1983 | **sospeso** (media) | Il vento dell'Amnesia: anime (OVA) con infobox film; l'anno è quello del romanzo |
| The Connection (spettacolo teatrale) | 1961 | **sospeso** (media) | The Connection: la pagina è intitolata allo spettacolo teatrale, ma l'infobox è il film di Shirley Clarke (1961) |
| Jesus Christ Superstar Live in Concert | 2018 | **includere** (media) | Jesus Christ Superstar Live in Concert: la pagina lo chiama «film TV» (come «Grinch Musical Live!», che è tenuto) |
| Fantaghirò (miniserie televisiva) | 1991 | **sospeso** (media) | Fantaghirò (1991): il titolo dice «miniserie», ma i sequel Fantaghirò 2, 4 e 5 sono tenuti tra i film TV: incoerenza da sciogliere |

Altri controlli sulle 259:
- **Cortometraggi, animazione, film muti:** nessuno dei 259 ha classe «cortometraggio», «film muto» o «animazione» (solo 1 *Arion*, classe di film d'animazione ma pagina del manga). Non ci sono corti o muti esclusi.
- **Film TV esclusi per il titolo:** 19 pagine hanno una classe film (12 «film TV», 6 «lungometraggio», 1 «animazione») ma il titolo Wikipedia dice «(miniserie televisiva)» o «(manga)»; li ho lasciati esclusi perché è Wikipedia stessa a dichiararlo, tranne *Fantaghirò* (vedi tabella).
- **Serie di film e newsreel:** *Alice Comedies*, *Kinopravda*, *Die Deutsche Wochenschau*, *Cremaster (serie di film)* sono pagine di raccolta, non di un singolo film: restano escluse.
- Le restanti sono serie TV, manga, anime, miniserie, voci di genere e simili, senza classe di film né infobox Film (controllato sulla lista completa).

## 4. Le 25 trame: verifica sezione per sezione

Ho riletto dal dump locale **tutte** le intestazioni di ognuna delle 25 pagine (`audit/section_detail.json`). In 24 pagine la «Trama» è seguita solo da sezioni estranee (Produzione, Personaggi, Accoglienza, Riconoscimenti, Colonna sonora, Sequel…); la lunghezza del testo corretto coincide con la sezione «Trama» tranne in un caso (*Final Fantasy*, dove include un sottoparagrafo). Il caso *Nero-Fumo* è confermato: l'intestazione trovata dalla Fase 1 era «Storia» (2.472 caratteri di produzione) e la «Trama» vera (2.030) viene dopo; l'eccezione manuale produce esattamente quella sezione.

| Film | Caratteri ora → dopo | Sezioni tolte | Verifica |
|---|---|---|---|
| Grease (Brillantina) | 11.526 → 5.448 | Produzione. Colonna sonora. Edizione italiana. Accoglienza. Riconoscimenti. Altri media… | ok: solo sezioni estranee tolte; trama intera |
| Final Fantasy (film) | 9.946 → 3.010 | Produzione. Colonna sonora. Accoglienza. Riconoscimenti. Riferimenti alla serie videoludica. Aki Ross | la «Trama» (1.354 car.) include il sottoparagrafo «Temi affrontati» (1.809): si tiene tutto (struttura Wikipedia). ma è analisi tematica. non narrazione |
| L'angelo azzurro (film 1930) | 4.419 → 2.311 | Differenze con il romanzo. Altro | ok: solo sezioni estranee tolte; trama intera |
| Il re leone | 41.768 → 8.067 | Personaggi. Produzione. Colonna sonora. Distribuzione. Promozione. Accoglienza… | trama intera (8.067 car.). 2.4k token: non serve più il chunking |
| Sei donne per l'assassino | 6.954 → 4.265 | Produzione. Influenze. Accoglienza. Distribuzione | ok: solo sezioni estranee tolte; trama intera |
| ...e tu vivrai nel terrore! - L'aldilà | 22.299 → 6.548 | Produzione. Colonna sonora. Promozione. Distribuzione. Accoglienza. Riferimenti letterari… | ok: solo sezioni estranee tolte; trama intera |
| Exodus (film) | 12.875 → 7.112 | Differenze dalla realtà storica. Produzione. Distribuzione. Premi e candidature | ok: solo sezioni estranee tolte; trama intera |
| Rocky IV | 7.752 → 3.388 | Produzione. Tematica. Colonna sonora. Distribuzione. Director's cut | ok: solo sezioni estranee tolte; trama intera |
| I tredici spettri | 10.155 → 4.650 | Gli spettri | «Gli spettri» (5.498 car.) è la scheda dei 13 fantasmi: lasciata fuori; la trama resta intera |
| Pirati dei Caraibi - Ai confini del mondo | 7.882 → 6.263 | Personaggi. Produzione | ripulito il residuo `''` del taglio |
| Music Box - Prova d'accusa | 5.484 → 4.411 | Produzione. Riconoscimenti | ok: solo sezioni estranee tolte; trama intera |
| Il principe cerca moglie | 7.095 → 3.897 | Produzione. Curiosità. Distribuzione. Accoglienza. Riconoscimenti. Sequel | tolta la sola frase finale che annunciava una barzelletta (il modello citazione era già perso): nessun fatto narrativo |
| Teodora (film 1954) | 2.769 → 754 | Produzione | ok: solo sezioni estranee tolte; trama intera |
| L'anatra all'arancia | 2.424 → 2.113 | Produzione | ok: solo sezioni estranee tolte; trama intera |
| Carnival of Souls (film 1962) | 7.822 → 4.844 | Produzione. Distribuzione. Remake | ok: solo sezioni estranee tolte; trama intera |
| Quinto potere | 32.657 → 2.277 | Produzione. Distribuzione. Accoglienza. Riconoscimenti. Adattamenti. Nella cultura di massa | trama intera (2.277 car.) |
| Trader Horn | 3.076 → 1.986 | Produzione. Riconoscimenti | ok: solo sezioni estranee tolte; trama intera |
| Scene di caccia in bassa Baviera | 4.054 → 1.667 | Produzione. Accoglienza | ok: solo sezioni estranee tolte; trama intera |
| Rumba (film 1937) | 1.536 → 520 | Produzione. Distribuzione | ok: solo sezioni estranee tolte; trama intera |
| Quartetto Basileus | 2.546 → 1.600 | Produzione | ok: solo sezioni estranee tolte; trama intera |
| Canzone appassionata | 2.397 → 1.327 | Produzione. Distribuzione | ok: solo sezioni estranee tolte; trama intera |
| Deathgasm | 7.431 → 6.858 | Accoglienza. Sequel | ok: solo sezioni estranee tolte; trama intera |
| Barbie e il cavallo leggendario | 4.937 → 4.814 | Colonna sonora | ok: solo sezioni estranee tolte; trama intera |
| I figli della strada | 1.989 → 1.424 | Produzione | ok: solo sezioni estranee tolte; trama intera |
| Nero-Fumo e i sette nani neri | 8.959 → 2.030 | Storia. Accoglienza. … | **eccezione manuale**: la sezione «Storia» (2.472 car.) è produzione. la «Trama» (2.030 car.) viene dopo; si tengono i soli paragrafi della Trama |

Correzioni tecniche fatte allo script rispetto a quanto scritto in Fase 5: il riferimento `<ref>` di *Final Fantasy* **non** spariva con il taglio (era dentro la trama): ora `tidy()` toglie riferimenti e residui `''`; la frase finale di *Il principe cerca moglie* che introduceva una citazione ormai persa viene tolta. Dopo la correzione nessuna delle 25 ha marcatura residua e nessuna trama del catalogo supera gli 8.191 token (la più lunga, *I dieci comandamenti* 1956, è a 7.761).

## 5. Lo script di pulizia [verificato]

`python -m tool.RAGWikipediaFilm.audit.build_clean build | verify`

- **Entrate (sola lettura):** `films.jsonl`, `audit/exclusions.json`, `data/audit/section_fix.jsonl`, `data/audit/classification.jsonl`, `audit/plan_overrides.json` (assente = scenario base).
- **Uscite:** `data/clean/films.clean.jsonl`, `data/clean/excluded.jsonl` (i record esclusi, interi, con motivo), `data/clean/clean_manifest.json` (conteggi e SHA-256 di tutte le entrate e uscite).
- **Deterministico:** serializzazione identica a quella di Fase 1 (chiavi ordinate, nessun orologio, nessuna casualità); `verify` ricostruisce in memoria e confronta byte per byte.
- **Reversibile:** `clean + excluded` coprono tutti i 41.421 record; per i testi corretti si conserva l'SHA-256 dell'originale e `verify` controlla che combaci con `films.jsonl`. Ogni campo diverso dal testo è identico all'originale. Nei test una modifica a mano o un record perso vengono rilevati.
- **Offline:** non importa rete né librerie HTTP; i test lo girano su dati sintetici.
- **Esito sul catalogo reale:** scenario base = 41.162 record puliti, 259 esclusi, 25 trame corrette, 71 «non verificati»; `verify` → «OK». Occupa 131 MB.

## 6. Numeri

Ogni film ha un solo punto (nessuna trama supera il limite), quindi **punti = record**. Si riusano i vettori già verificati, tranne i 25 testi corretti: 26.896 token, **0,0035 USD**, da autorizzare.

| Scenario | Record | Punti |
|---|---|---|
| Oggi | 41.421 | 41.438 |
| Base (259 esclusi + 25 trame) | 41.162 | 41.162 |
| **Consigliato**: base, +4 film rimessi dentro, −18 dubbi, −14 ibridi, −1 fumetto (*Lobo*), sospesi inclusi e marcati | **41.133** | **41.133** |
| Come sopra ma con tutti i sospesi inclusi e rimessi dentro i 4 incerti delle 259 | 41.137 | 41.137 |
| Come il consigliato ma sospesi tutti esclusi (8 dubbi + 9 ibridi) | 41.116 | 41.116 |

Nello scenario consigliato i record segnati «non verificati» sono 62 (53 dubbi rimasti + 9 ibridi in sospeso). Il file `audit/plan_overrides.proposed.json` lo descrive: per applicarlo si copia in `plan_overrides.json` e si rilancia `build`.

## 7. Contraddizioni tra i rapporti precedenti

1. **«259 non film certi»** (Fase 4/5): non lo sono tutti; 8 vanno rivisti e 4 sono film veri. Il numero di esclusi certi diventa 251, più 8 da decidere.
2. **Digimon & co. «errore di pagina»** (Fase 5): più preciso: l'infobox è di un film collegato e la trama di una serie; vedi sopra.
3. **«Il riferimento `<ref>` di Final Fantasy sparisce con il taglio»** (Fase 5): falso, è dentro la trama; corretto con `tidy()`.
4. **Miniserie:** la Fase 4 esclude 63 miniserie, ma 29 miniserie+film erano rimaste tra i film, e *Fantaghirò* (1991) è escluso mentre i sequel restano. Incoerenza da chiudere con una regola.
5. **Totali:** 41.149 (Fase 5, 11 dubbi esclusi) → 41.133 (consigliato qui, 18 dubbi + 14 ibridi + 4 rimessi dentro).
6. **Nero-Fumo:** la Fase 5 lo dava «circa 2.000 caratteri»: sono 2.030, ed è la sezione «Trama», non una porzione a posizione fissa.
7. **«Una sinossi identica, 66 film»:** invariato, non è un errore ma remake con la stessa trama.
8. `INTEGRATION_PROPOSAL.md` era superata (obiettivo = sostituzione) ed è stata eliminata in Fase 8, sostituita da `INTEGRATION_PLAN.md`; `README.md`/`PROGRESS.md` parlano ancora della fase di integrazione parallela nella sezione 13: da allineare dopo la tua approvazione.

## 8. Decisioni che servono da te

1. Regola per i **film TV in due parti**: tenerli o escluderli? (9 ibridi + *Karol* e i *Fantaghirò*.)
2. Gli **8 dubbi in sospeso** (*ÉX-Driver*, *Gundam 0083*, *Macross Plus*, *Maetel Legend*, *Love Like Aliens*, *Bungaku shōjo*, *Esterno notte*, *Look Back*): includere o escludere?
3. I **film collegati alle serie anime** (infobox di *Digimon* ecc.): accettiamo la perdita come voci autonome o chiedi l'estrazione dal testo?
4. Le **8 pagine da rivedere** tra le 259.
5. L'**eccezione Nero-Fumo** e le altre correzioni di testo (Final Fantasy tiene *Temi affrontati*: ok?).
6. Il costo di **0,0035 USD** per i 25 vettori.

## 9. Procedura esatta per generare il dataset e ricostruire la collezione (dopo l'approvazione)

1. Copiare `audit/plan_overrides.proposed.json` in `audit/plan_overrides.json` con le tue modifiche.
2. `python -m tool.RAGWikipediaFilm.audit.build_clean build` poi `verify` (deve dire «OK»).
3. Embedding dei soli 25 testi corretti (autorizzazione, ~0,0035 USD); gli altri vettori vengono dagli shard esistenti per `film_id` e hash del testo.
4. Creare `wikipedia_films_it_v2` con la procedura di Fase 3 sul file `films.clean.jsonl` (stessi indici, più il campo `catalog_status`). La v1 non si tocca.
5. `check` sulla v2 (punti = record, nessun chunk multiplo), poi alias da v1 a v2.

## 10. Test necessari prima di dichiarare il nuovo RAG pronto

- **Offline (fatti):** 86 test nella cartella; costruzione deterministica, reversibilità, rilevamento di manomissioni, tabelle di decisione coerenti.
- **Da fare dopo la ricostruzione:** (a) `check` della v2; (b) le 72 query narrative con confronto top-10 v1/v2; (c) query per genere/formato che oggi restituiscono voci di argomento; (d) una query per ognuno dei 25 film corretti (devono trovarsi per la loro trama); (e) un film «non verificato» deve essere filtrabile; (f) nessun film escluso deve comparire; (g) un controllo che l'alias passi e ritorni.
- **Prima di sostituire il vecchio RAG:** un confronto di qualità su domande reali tra vecchio e nuovo (richiede chiamate a pagamento: da autorizzare) e l'adattamento di `rag_search` (query in italiano, nessuna `semantic_query` inglese, routing e `data_coverage.py`), che questa fase non tocca.
