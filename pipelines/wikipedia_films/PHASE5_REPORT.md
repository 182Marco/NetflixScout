# Fase 5: controlli di qualità prima delle esclusioni

Stato: **solo analisi.** Nessuna esclusione applicata, `films.jsonl`, embedding e collezioni Qdrant invariati, nessuna chiamata a pagamento, nessun commit. Le etichette sono mie, ottenute leggendo il testo delle pagine e i dati Wikidata locali; dove non è una misura lo dico. Il campione è riproducibile: `python -m pipelines.wikipedia_films.audit.sample_review <strato> <da> <a>` (seme fisso).

## 1. Campionamento dei 1.319 film a confidenza non alta [misurato + lettura]

Popolazione: 1.319 film (1.304 media, 15 decisi a mano). Ne ho letti **233**: 60 film TV, 40 lungometraggi, 30 animazioni e **tutti** i 103 degli strati piccoli (film senza P31, speciali TV, corti, video, documentari: per questi è un censimento, non una stima).

| Strato | Popolazione | Letti | Falsi positivi certi | Tasso (IC 95%) | Stima nello strato |
|---|---|---|---|---|---|
| Film TV | 735 | 60 | 1 | 1,7% (0,3–8,9%) | ~12 (2–65) |
| Lungometraggi | 301 | 40 | 0 | 0% (0–8,8%) | 0 (0–26) |
| Animazione | 180 | 30 | 0 | 0% (0–11,4%) | 0 (0–20) |
| Altri (censimento) | 103 | 103 | 1 | 1,0% | 1 |

**Falsi positivi certi**: *Uccelli di rovo* (miniserie in quattro puntate classificata film TV) e *Lobo Paramilitary Christmas Special* (è un fumetto). **Casi di confine**: *La notte quando è morto Pasolini* (intervista TV di 25 minuti), *Il giovane Mussolini* (probabile miniserie), *Vette di libertà*, *2 Girls 1 Cup* (video virale di 1 minuto), *Rabbits* (serie web), *Grachi Sweet 16* (puntata speciale).

**Come leggere i numeri.** Con campioni da 30–60 un risultato di 0 errori non esclude fino a circa il 9–11% di errori nello strato: è un limite del campione, non una garanzia. Il tasso complessivo stimato è **intorno all'1%** dei 1.319, con un'incertezza larga sui film TV. Tutte le 30 animazioni e i 40 lungometraggi letti erano opere vere (anche titoli poco noti: speciali Disney, Barbie, Scooby-Doo, film TV italiani).

### Errore sistematico trovato: miniserie classificate film TV [misurato]

Wikidata dà a molte miniserie anche la classe «film televisivo». Il mio classificatore le ha tenute come film se la pagina era senza infobox. Un controllo su **tutti** i 41.091 film trova **46 record** con una classe di serie accanto a quella di film (elenco in `audit/series_class_hybrids.json`):

| Gruppo | N | Esempi |
|---|---|---|
| A. miniserie + film TV | 20 | *Uccelli di rovo*, *Il processo di Norimberga*, *Attila l'unno*, *Atomic Train*, *Karol – Un papa rimasto uomo* |
| B. miniserie + altro tipo di film | 9 | *Heimat* (924 min), *Come Yukong spostò le montagne* (763 min), *Oblomov* |
| C. classi manga/anime | 7 | *Phantom Blood*, *Crusher Joe*, *Sukeban deka* |
| D. altre classi di serie TV | 10 | *Miss Marple nei Caraibi*, *Tomie: Another Face* |

Non sono tutti errori: *Oblomov* o *Conversazioni private* sono film veri. Con la regola «niente miniserie» servirebbe una lettura caso per caso; li propongo **come dubbi** (inclusi e segnalati), non come esclusioni. Altri 17 film TV oltre i 180 minuti senza classe di serie (*Fantaghirò 2/4/5*, *Karol – Un uomo diventato papa*) sono verosimilmente film TV in più parti: da lasciare.

## 2. Anomalie dei metadati [misurato; decisioni = proposta]

Nota di impatto: gli embedding contengono **solo la trama**. Anno, titolo e regista stanno nel payload: un anno sbagliato peggiora un filtro, non la ricerca semantica.

| Anomalia | N | Esito dell'analisi | Decisione consigliata |
|---|---|---|---|
| Anno ≥ 2026 | 188 (tutti 2026) | 162 con data di uscita Wikidata entro il 1 nov 2026; **4 con uscita dopo il dump** (*Godzilla Minus Zero* 3 nov, *Scrooge e gli spiriti del Natale* 12 nov, *Hunger Games – L'alba sulla mietitura* 20 nov, *Le nuove disavventure di Cliff Booth* 25 nov); 22 senza data (la maggior parte film italiani indipendenti, 10 senza elemento Wikidata). Nessun anno oltre il 2026 | Tenere. Segnalare i 4 «non ancora usciti alla data del dump» e rivederli a ogni rifacimento: le trame di *Hunger Games* e *Scrooge* sono brevi (482 e 630 caratteri) |
| Prima del 1895 | 7 | *Passage de Vénus* (1874), *Monkeyshines* (1889), *Un bon bock* (1892), *Pauvre Pierrot* (1892), *Fred Ott's Sneeze* (1894), *Un rêve au coin du feu* (1894), *Autour d'une cabine* (1894): esperimenti e primi film autentici | Tenere tutti. Errore: nessuno |
| Titolo e anno discordanti | 15 | In **12** casi l'anno dell'infobox e quello del titolo coincidono e il campo `year` (da Wikidata) è l'unico diverso (*Do Not Disturb* 1923 contro 2023, *Il diavolo* 1988 contro 1972, *L'adolescente* 1975 contro 1999, *Tokyo Tower* 2001 contro 2005, *Paradise Alley* 1958 contro 1962 …). 1 è spiegabile (*Il fare politica*: il titolo riporta un intervallo 1982–2004). 2 sono incerti (*La miliardaria*: l'infobox dà 1920 come `year`, il titolo 1922; *Una questione privata*: nessun infobox) | Errori probabili del campo `year`: 12. Spiegabile: 1. Incerti: 2. Il campo `year` andrebbe corretto dall'infobox solo dopo una verifica su fonte esterna |
| Anno recuperabile dal titolo | 20 | 5 sono miniserie/serie già escluse; 15 sono film TV italiani degli anni 70–80 o film recenti con «(film AAAA)» nel titolo | Recuperabile con certezza solo se non c'è un dato in conflitto: da proporre come campo a parte, non da applicare |
| Anno infobox ≠ anno Wikidata (scarto >3 anni) | 62 | 55 non hanno anno nel titolo, quindi **nessuna fonte interna decide**; di 7 con anno nel titolo, 5 danno ragione all'infobox e 2 a Wikidata; molti scarti sono ristampe o primi/ultimi passaggi | Incerti 55; errori certi di Wikidata 5; errori dell'infobox 2. Non correggere senza fonte |
| IMDb condiviso | 2 | `tt0078788`: *Apocalypse Now* (1979) e *Apocalypse Now Redux* (2001): versioni diverse, spiegabile. `tt0483403`: *Dreams Realized* e *In the Vale of Sorrow* (entrambi 1915): errore di Wikidata o stessa opera | Tenere i quattro; segnalare il secondo caso |
| Stesso titolo e anno | 1 | *È primavera...* e *È primavera* (1950) | Probabile doppione dello stesso film: da verificare, poi unire o escludere uno |
| Sinossi identica | 10 gruppi / 66 film | Sono quasi tutti remake o versioni omonime (*Senza famiglia* ×4, *Ramona* ×4, *Uncle Tom's Cabin* ×6, *The Merchant of Venice* ×13) a cui la pagina italiana dà la stessa trama | Tenere: stessa trama = stesso vettore, la ricerca restituirà il gruppo insieme. Segnalare a parte |

Altri difetti trovati nel testo (non nella lista dell'utente): testo grezzo con `<ref>`, modelli `{{…}}` o `[[…]]` non ripuliti in 12 trame (9 sono tra le 25 contaminate; le altre 3 sono Q562096, Q112977212 e Q686533), residui di marcatura `''` in 41; nessuna trama sotto i 100 caratteri.

## 3. Le 25 trame contaminate [misurato]

Per ciascuna ho confrontato il testo attuale con quello tagliato prima della prima sezione sorella. In 24 casi il taglio toglie solo sezioni estranee (Produzione, Personaggi, Accoglienza, Differenze con il romanzo, Colonna sonora, Premi). **Un caso è sbagliato e va corretto a mano** (*Nero-Fumo e i sette nani neri*), due hanno difetti minori.

| Film | Caratteri ora → dopo | Prima sezione estranea | Verifica |
|---|---|---|---|
| Q267721 | Grease (Brillantina) | 11.526 → 5.453 | Produzione (+6 altre) | ok: sezione estranea tolta. trama intera |
| Q752541 | Final Fantasy (film) | 9.946 → 3.165 | Produzione (+5 altre) | resta anche un riferimento <ref> nel testo grezzo corrente: sparisce con il taglio |
| Q158047 | L'angelo azzurro (film 1930) | 4.419 → 2.311 | Differenze con il romanzo (+1 altre) | ok: sezione estranea tolta. trama intera |
| Q36479 | Il re leone | 41.768 → 8.067 | Personaggi (+11 altre) | tolti: produzione. personaggi. accoglienza. premi; la trama resta intera (8.067 caratteri) |
| Q886645 | Sei donne per l'assassino | 6.954 → 4.265 | Produzione (+3 altre) | ok: sezione estranea tolta. trama intera |
| Q330982 | ...e tu vivrai nel terrore! - L'aldilà | 22.299 → 6.553 | Produzione (+7 altre) | ok: sezione estranea tolta. trama intera |
| Q1355901 | Exodus (film) | 12.875 → 7.117 | Differenze dalla realtà storica (+3 altre) | ok: sezione estranea tolta. trama intera |
| Q387638 | Rocky IV | 7.752 → 3.388 | Produzione (+4 altre) | ok: sezione estranea tolta. trama intera |
| Q186864 | I tredici spettri | 10.155 → 4.655 | Gli spettri (+0 altre) | la sezione tolta («Gli spettri») descrive i fantasmi uno per uno: contenuto parziale di trama. lasciato fuori e segnalato |
| Q54274 | Pirati dei Caraibi - Ai confini del mondo | 7.882 → 6.268 | Personaggi (+1 altre) | resta un residuo di marcatura (`''`): da pulire |
| Q1427849 | Music Box - Prova d'accusa | 5.484 → 4.411 | Produzione (+1 altre) | ok: sezione estranea tolta. trama intera |
| Q493755 | Il principe cerca moglie | 7.095 → 4.008 | Produzione (+5 altre) | taglio sulla barzelletta finale (modello {{Citazione}} rimasto nel testo grezzo): perde una battuta. nessun fatto narrativo |
| Q1168667 | Teodora (film 1954) | 2.769 → 754 | Produzione (+0 altre) | ok: sezione estranea tolta. trama intera |
| Q3283420 | L'anatra all'arancia | 2.424 → 2.118 | Produzione (+0 altre) | ok: sezione estranea tolta. trama intera |
| Q1852671 | Carnival of Souls (film 1962) | 7.822 → 4.850 | Produzione (+2 altre) | ok: sezione estranea tolta. trama intera |
| Q572165 | Quinto potere | 32.657 → 2.277 | Produzione (+5 altre) | tolti: produzione. accoglienza. premi. eredità; la trama resta (2.277 caratteri) |
| Q1142707 | Trader Horn | 3.076 → 1.986 | Produzione (+1 altre) | ok: sezione estranea tolta. trama intera |
| Q948467 | Scene di caccia in bassa Baviera | 4.054 → 1.667 | Produzione (+1 altre) | ok: sezione estranea tolta. trama intera |
| Q2932282 | Rumba (film 1937) | 1.536 → 520 | Produzione (+1 altre) | ok: sezione estranea tolta. trama intera |
| Q38226 | Quartetto Basileus | 2.546 → 1.600 | Produzione (+0 altre) | ok: sezione estranea tolta. trama intera |
| Q19788177 | Canzone appassionata | 2.397 → 1.327 | Produzione (+3 altre) | ok: sezione estranea tolta. trama intera |
| Q19824623 | Deathgasm | 7.431 → 6.863 | Accoglienza (+1 altre) | ok: sezione estranea tolta. trama intera |
| Q15709914 | Barbie e il cavallo leggendario | 4.937 → 4.814 | Colonna sonora (+0 altre) | ok: sezione estranea tolta. trama intera |
| Q3203072 | I figli della strada | 1.989 → 1.424 | Produzione (+0 altre) | ok: sezione estranea tolta. trama intera |
| Q3821447 | Nero-Fumo e i sette nani neri | 8.959 → 2.472 | Trama (+3 altre) | **ATTENZIONE** la sezione cercata (Trama) è una sorella successiva: il taglio automatico terrebbe la produzione e perderebbe la trama. Serve un'eccezione: usare i primi 5 paragrafi dopo la produzione |

Il testo corretto per ciascuna pagina è in `data/audit/section_fix.jsonl` (rigenerabile offline con `python -m pipelines.wikipedia_films.audit.section_scan` dal dump locale). Il taglio non elimina elementi narrativi nei 24 casi, tranne *I tredici spettri* (biografie dei fantasmi, lasciate fuori) e la battuta finale de *Il principe cerca moglie*. Per *Nero-Fumo* la trama corretta sono i paragrafi dal 2.472° carattere in poi fino alla prima frase di accoglienza (5 paragrafi, circa 2.000 caratteri): lo propongo come eccezione esplicita con test.

## 4. I 71 casi dubbi, uno per uno [lettura; nessuna modifica all'inclusione]

Riepilogo delle mie raccomandazioni: **includere 44, escludere 11, in sospeso 16**. Tutti restano inclusi e marcati «non verificato», come hai deciso. Le motivazioni sono su leggibilità di durata, regista, IMDb e testo; la fiducia è dichiarata. Tabella anche in `audit/doubtful_review.json`.

| # | Titolo | Anno | Categoria | Decisione (fiducia) | Motivo |
|---|---|---|---|---|---|
| 1 | Marmalade Boy | 1995 | serie anime | escludere (media) | 26 minuti = durata di un episodio; la pagina descrive la serie TV, l'infobox Film è un errore di pagina |
| 2 | ÉX-Driver | – | OVA | sospeso (bassa) | OVA a più episodi; da valutare se la pagina tratta la serie o un lungometraggio |
| 3 | Cortili del cuore | 1996 | serie anime | escludere (bassa) | trama del personaggio di una serie TV (nome italiano della serie), nessuna durata, nessun codice IMDb |
| 4 | Perry Mason: Il bacio che uccide | 1993 | film TV | includere (alta) | film TV della serie di Perry Mason; mancano solo regista e IMDb nella pagina |
| 5 | L'uovo dell'angelo | 1985 | film anime (OVA) | includere (alta) | 71 minuti, opera unica di Oshii: lungometraggio d'animazione uscito direttamente in home video |
| 6 | Hana yori dango | 1997 | anime breve | sospeso (bassa) | 30 minuti; non è chiaro se la pagina parli del mediometraggio del 1996 o della serie |
| 7 | Digimon Savers | 2006 | serie anime | escludere (alta) | serie TV Digimon, 20 minuti = episodio |
| 8 | Lovely Complex | 2006 | lungometraggio da manga | includere (media) | 99 minuti, regista presente: il film live-action; il manga è solo la fonte |
| 9 | Digimon Tamers | 2001 | serie anime | escludere (media) | pagina della serie TV (anche se esiste un film omonimo con altro titolo) |
| 10 | Perry Mason: Un fotogramma dal cielo | 1988 | film TV | includere (alta) | film TV di Perry Mason |
| 11 | Perry Mason: La donna del lago | 1988 | film TV | includere (alta) | film TV di Perry Mason |
| 12 | Perry Mason: Furto d'autore | 1990 | film TV | includere (alta) | film TV di Perry Mason |
| 13 | Perry Mason: La bara di vetro | 1991 | film TV | includere (alta) | film TV di Perry Mason |
| 14 | Perry Mason: L'arte di morire | 1992 | film TV | includere (alta) | film TV di Perry Mason |
| 15 | Perry Mason: Morte di un dongiovanni | 1992 | film TV | includere (alta) | film TV di Perry Mason |
| 16 | Perry Mason: L'ospite d'onore | 1993 | film TV | includere (alta) | film TV di Perry Mason |
| 17 | Perry Mason: Serata con il morto | 1994 | film TV | includere (alta) | film TV di Perry Mason |
| 18 | Perry Mason: dietro la facciata | 1994 | film TV | includere (alta) | film TV di Perry Mason |
| 19 | Lupin III - Green vs Red | 2008 | speciale TV anime | includere (media) | 80 minuti, speciale televisivo di lunghezza di un film |
| 20 | Baldios - Il guerriero dello spazio | 1981 | serie anime | sospeso (bassa) | titolo italiano della serie; esiste anche un film del 1981; la trama copre la serie (cita puntate) |
| 21 | Mobile Suit Gundam 0083: Stardust Memory | 1992 | OVA | sospeso (media) | serie OVA di 13 episodi; la durata 120 minuti è della versione montata |
| 22 | UFO Robot Goldrake contro il Grande Mazinga | 1976 | film breve anime | includere (media) | 27 minuti, cortometraggio uscito al cinema (Toei Manga Matsuri) |
| 23 | Clover (Toriko Chiya) | 1997 | lungometraggio da manga | includere (bassa) | 120 minuti e regista: sembra il film tratto dal manga |
| 24 | Digimon Adventure 02 | 2000 | serie anime | escludere (alta) | serie TV Digimon Adventure 02 |
| 25 | L'audacia degli X-Men | – | speciale TV anime | includere (media) | episodio pilota animato di X-Men (IMDb presente); è un film TV ma la pagina non ha anno |
| 26 | Macross Plus | – | OVA | sospeso (bassa) | OVA di 4 episodi ricomposto in film; la pagina non distingue |
| 27 | Ultimi raggi di luna | 2004 | lungometraggio da manga | includere (media) | 112 minuti, regista presente: film live-action |
| 28 | Adventures of Captain Marvel | 1941 | serial cinematografico | includere (media) | serial del 1941 in 12 capitoli, distribuito al cinema; coerente con gli altri 7 serial già tenuti |
| 29 | Armitage III | – | OVA | includere (bassa) | 140 minuti, regista e IMDb: versione lungometraggio dell'OVA |
| 30 | Hotel Hibiscus | 1986 | lungometraggio da manga | includere (media) | film di Nakae; l'anno 1986 è quello del manga (anno da correggere) |
| 31 | Lei e il gatto | 1999 | cortometraggio anime | includere (alta) | corto di 5 minuti di Makoto Shinkai |
| 32 | SuperDoll Rika-chan | 1999 | serie anime | escludere (alta) | serie TV, 30 minuti = episodio |
| 33 | Ken il guerriero - La leggenda | 2006 | film anime | includere (bassa) | la trama parla di un film; manca IMDb |
| 34 | La recta provincia | 2007 | miniserie TV | escludere (media) | miniserie televisiva (160 minuti in più parti), regola «niente miniserie» |
| 35 | Hiyokoi | 2010 | anime breve | sospeso (bassa) | 22 minuti, nessun dato sul regista; potrebbe essere un episodio o un corto |
| 36 | Yuuki | 2006 | film TV | includere (media) | 107 minuti, regista e IMDb presenti |
| 37 | Interno giorno | 2011 | film TV | includere (media) | film televisivo di Tommaso Rossellini |
| 38 | Mani Pulite - Il duello | 1997 | film TV | includere (media) | film TV sull'inchiesta Mani Pulite |
| 39 | Code Geass: Akito the Exiled | 2012 | OVA | sospeso (bassa) | OVA di 5 episodi; la pagina parla di «prima e seconda serie» |
| 40 | Dreams of the Rarebit Fiend | 1921 | cortometraggio muto | includere (alta) | corto di Winsor McCay del 1921 |
| 41 | Kara no kyōkai | – | serie di film (anime) | sospeso (bassa) | pagina sulla saga di film; come le altre pagine di «serie di film» andrebbe esclusa |
| 42 | Maetel Legend - Sinfonia d'inverno | – | OVA | sospeso (bassa) | OVA speciale con IMDb ma senza durata |
| 43 | Lupin III - La principessa della brezza: La città nascosta nel cielo | 2013 | film TV anime | includere (media) | speciale televisivo Lupin III di lunghezza film |
| 44 | Generation War | 2013 | miniserie TV | escludere (media) | miniserie tedesca in tre parti |
| 45 | Dive!! | 2008 | lungometraggio da manga | sospeso (bassa) | infobox film senza durata né regista; il film è del 2008 |
| 46 | Un padre inatteso | 1998 | film TV | includere (alta) | film TV |
| 47 | Love Like Aliens | – | anime | sospeso (bassa) | non c'è nessun dato (regista, durata, IMDb) |
| 48 | Bungaku shōjo | – | serie di film (anime) | sospeso (bassa) | pagina della saga, sinossi di 432 caratteri |
| 49 | Ajin - Demi Human | 2015 | lungometraggio da manga | includere (media) | 103 minuti: film (la pagina è intitolata al manga) |
| 50 | Orange (manga) | 2016 | lungometraggio da manga | includere (bassa) | infobox film con durata e regista |
| 51 | Non mi farò coinvolgere | 2014 | lungometraggio da manga | includere (media) | 84 minuti: film live-action |
| 52 | Ronnie Rocket | – | progetto non realizzato | escludere (alta) | film mai prodotto: nessuna opera da raccomandare |
| 53 | Ostaggi delle SS sulle Alpi | 2015 | film TV | includere (bassa) | la pagina lo chiama «il film»; Wikidata lo dà come miniserie di 90 minuti |
| 54 | Indagine sui sentimenti | 1984 | film TV | includere (bassa) | trama narrativa, mancano regista e IMDb |
| 55 | L DK | 2014 | lungometraggio da manga | includere (media) | film live-action del 2014 |
| 56 | Aruvu rezuru: kikaijikake no yōseitachi | 2013 | film anime | includere (media) | regista e IMDb presenti |
| 57 | Kyō no Kira-kun | 2017 | lungometraggio da manga | includere (media) | 109 minuti: film live-action |
| 58 | Bella, pazza e impossibile | 2014 | lungometraggio | includere (bassa) | categoria film, trama narrativa, mancano regista e IMDb |
| 59 | Nata Femmena | 2018 | documentario | includere (media) | documentario di 53 minuti |
| 60 | Night Skies | – | progetto non realizzato | escludere (alta) | seguito mai realizzato di Incontri ravvicinati del terzo tipo |
| 61 | P&ME - Policeman and Me | 2012 | lungometraggio da manga | includere (bassa) | regista presente; anno dell'infobox diverso da Wikidata |
| 62 | Esterno notte (film) | 2022 | miniserie / film in due parti | sospeso (media) | 344 minuti, uscita in sala in due film e in TV come miniserie |
| 63 | The Works (film) | – | film incompiuto | sospeso (media) | parte del film esiste ma non è mai uscito |
| 64 | Tsurune | 2016 | serie anime | escludere (media) | la sinossi inizia con «La serie parla…»: è la serie TV |
| 65 | Il mio matrimonio felice | 2019 | anime / romanzo | sospeso (bassa) | pagina che copre romanzo, manga, anime e film; la trama è quella del romanzo |
| 66 | Look Back | 2021 | manga / film | sospeso (bassa) | il manga è del 2021, il film d'animazione del 2024; la pagina copre entrambi |
| 67 | Giovannino Guareschi - Non muoio neanche se mi ammazzano | 2026 | lungometraggio | includere (media) | film del 2026 |
| 68 | Meitantei Conan - Black History - Kuro-zukume no soshiki to no taiketsu no rekishi | 2007 | speciale TV anime | includere (bassa) | episodio speciale di Detective Conan, senza durata |
| 69 | Meitantei Conan - Gin'yoku no Time Travel | 2004 | speciale TV anime | includere (bassa) | episodio speciale di Detective Conan, senza durata |
| 70 | 100 metri - Hyakuemu | 2025 | film anime | includere (media) | 106 minuti: film d'animazione |
| 71 | Lupin the IIIrd - Zenigata e i due Lupin | 2025 | film anime | includere (media) | film d'animazione di 53 minuti, regista e IMDb |

## 5. Numeri definitivi stimati

| | Record | Punti Qdrant |
|---|---|---|
| Oggi | 41.421 | 41.438 |
| Scenario A (esclusi i 259) | 41.162 | 41.167 |
| A + trame corrette (le 25, di cui 2 perdono i chunk) | 41.162 | **41.162** |
| A + trame + esclusioni consigliate in questa fase (11 dubbi, *Uccelli di rovo*, *Lobo*) | **41.149** | **41.149** |
| Come sopra, escludendo anche i 16 in sospeso e il gruppo A delle miniserie ibride (20) | 41.113 | 41.113 |

I punti coincidono con i record perché, dopo il taglio, nessuna trama supera il limite di 8.191 token: oggi i 17 punti in più sono i chunk dei 3 non film (12) e dei 2 film con trama contaminata (5). Vettori nuovi da calcolare: **25** (le trame corrette), circa 0,0035 USD, da autorizzare. Gli altri vettori si riusano dagli shard già verificati.

## 6. Procedura tecnica per il dataset pulito e la nuova collezione (da approvare)

1. **Versione dei dati.** `films.jsonl` e lo snapshot Wikidata restano intatti. Una lista di esclusioni versionata (`audit/exclusions.json` più le decisioni che approverai) con id, motivo e fonte della decisione; un file di correzioni di testo per le 25 trame (generato da `section_scan` più l'eccezione *Nero-Fumo* e la pulizia dei `''`).
2. **Dataset derivato.** Un comando deterministico legge `films.jsonl`, applica esclusioni e correzioni e scrive `films.clean.jsonl` con un manifesto (conteggi, SHA-256, versione della regola). Un test verifica che due esecuzioni diano gli stessi byte e che la rete non serva.
3. **Embedding.** Per ogni film si riusa il vettore dello shard se l'hash del testo non è cambiato; per i 25 testi nuovi si chiama l'API (budget massimo 0,01 USD, autorizzazione tua). Le unità sono ricostruite con la stessa funzione di Fase 3.
4. **Collezione nuova** `wikipedia_films_it_v2`, con gli stessi indici di payload e un campo `status` (`verified`/`unverified`) per i 71 dubbi (e per i 46 ibridi, se li aggiungi). La v1 non si tocca.
5. **Controlli** prima dello scambio: `check` (conteggio punti = record, nessun chunk multiplo), 72 query narrative e le query per genere/formato che oggi restituiscono pagine non-film, confronto top-10 v1 vs v2.
6. **Alias** `wikipedia_films_it` → v2 con scambio atomico e ritorno alla v1 con un comando; la v1 si cancella solo dopo l'esito della migrazione.
7. **Test** nuovi per applicazione delle esclusioni, correzione delle trame (compreso il caso *Nero-Fumo*) e riproducibilità.

## 7. Giudizio: il dataset è pronto?

**Quasi.** Con lo scenario A restano tra le poche decine e un centinaio di opere dubbie su 41.000: la stima viene dal campione (~12 film TV con un intervallo ampio) più i 71 dubbi e i 46 ibridi, quindi un ordine di grandezza dello 0,1–0,3%, non una misura. Nessun articolo enciclopedico noto. Prima di ricostruire raccomando: (1) la tua decisione sui 16 in sospeso, (2) la lettura dei 46 ibridi serie/film, (3) la correzione del caso *Nero-Fumo*, (4) il rifacimento dei 25 vettori. Limiti: campione di 233 su 1.319; nessuna verifica su fonti esterne (Wikipedia online, IMDb); i tassi sui film TV hanno un intervallo largo.
