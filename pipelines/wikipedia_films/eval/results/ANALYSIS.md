# Analisi: effetto del dataset, effetto dell'algoritmo, stabilità del giudice, esempi

## 1. Dataset contro algoritmo (domande A–G, 56 liste da 5 film)

Percentuale di film **validi** (pertinenti e senza violazioni) e di **violazioni**. Effetto del dataset = NEW − OLD con lo stesso algoritmo; effetto dell'algoritmo = strategia − S0 sullo stesso corpus.

| Algoritmo | OLD validi | NEW validi | effetto dataset | OLD violaz. | NEW violaz. |
|---|---|---|---|---|---|
| S0 | 29% | 35% | +6 pt | 37% | 47% |
| S1 | 32% | 39% | +7 pt | 34% | 40% |
| S2n | 38% | 50% | +12 pt | 25% | 26% |
| S3 | 28% | 40% | +12 pt | 29% | 37% |
| S5 | 38% | 58% | +20 pt | 16% | 10% |
| S6 | 70% | 80% | +9 pt | 4% | 4% |

| Corpus | S0 validi | S5 validi | S6 validi | guadagno S0→S5 | guadagno S0→S6 |
|---|---|---|---|---|---|
| OLD | 29% | 38% | 70% | +8 pt | +41 pt |
| NEW | 35% | 58% | 80% | +23 pt | +44 pt |

La pipeline antica come gira nell'applicazione (OLD-NATIVE): validi 66%, violazioni 10%; il nuovo con l'algoritmo completo (NEW-S6): validi 80%, violazioni 4%.

## 2. Stabilità del giudice (secondo passaggio con un altro ordine casuale)

Stesso vincitore in 204/248 confronti (82%); vincitori opposti (senza pareggi) in 35.

| Confronto (due passaggi, 124 giudizi) | primo | secondo | pareggi |
|---|---|---|---|
| new/S0 vs old/S0 | 75 | 41 | 8 |
| new/S5 vs old/S5 | 89 | 31 | 4 |
| new/S6 vs old/S6 | 93 | 29 | 2 |
| new/S6 vs old/NATIVE | 96 | 27 | 1 |

Limiti: il giudice è lo stesso modello che esegue il parser e il rerank (possibile preferenza per i propri criteri); le trame del nuovo sono in italiano come la domanda e quelle del vecchio in inglese, quindi nel confronto sulle risposte la lingua dell'evidenza può avvantaggiare il nuovo; per questo le metriche per film (sezioni 1–3 del REPORT) restano il riferimento principale.

## 3. Migliori e peggiori risposte

### Dove il nuovo vince di più (NEW-S6 contro OLD-NATIVE)

**Domanda 56** — Un film in cui il protagonista deve scegliere tra salvare una persona cara e salvare molte altre persone  (scarto di punteggio nuovo−vecchio: +12)

- NEW-S6: [1] **Bussano alla porta (2023)** — Leonard e i suoi compagni costringono Eric e Andrew, genitori adottivi di Wen, a prendere una decisione terribile: sacrificare una persona cara oppure evitare una catastrofe globale e salvare moltissime vite.
- OLD-NATIVE: Nessun film dell’elenco corrisponde chiaramente alla richiesta: nessuna trama descrive un protagonista costretto a scegliere tra salvare una persona cara e salvare molte altre persone.
- Giudice: A propone “Bussano alla porta”, che corrisponde chiaramente al dilemma richiesto: Eric e Andrew devono scegliere se sacrificare una persona cara oppure impedire una catastrofe e salvare molte vite. B sostiene erroneamente che non esista alcun film pertinente.

**Domanda 15** — Consigliami film di supereroi come The Dark Knight, ma niente Batman  (scarto di punteggio nuovo−vecchio: +11)

- NEW-S6: Ecco alcuni film di supereroi dai toni più cupi e drammatici, senza Batman:

- **Il corvo - The Crow (1994)**: una storia di vendetta soprannaturale, violenta e malinconica, con un protagonista tormentato.
- **Darkman (1990)**: un antieroe segnato dalla tragedia affronta criminali e corruzione usando ingegno e abilità scientifiche.
- **Unbreakable - Il predestinato (2000)**: un’indagine misteriosa e intimista sull’identità di un uomo dotato di capacità straordinarie.
- **Samaritan (2022)**: un supereroe creduto scomparso torna a confrontarsi con un passato oscuro e con la criminalità della cit
- OLD-NATIVE: L’elenco contiene un solo film pertinente: [4] *Latin Dragon* (2004). È un action crime incentrato su un eroe solitario che affronta bande criminali e protegge il proprio quartiere, con un taglio realistico e urbano che può ricordare, almeno in parte, l’atmosfera di *The Dark Knight*. Gli altri titoli sono crime thriller o drammi criminali senza elementi da film di supereroi. **Nota:** [4] non è un film di Batman né appartiene alla sua saga.
- Giudice: B vince nettamente: propone quattro film di supereroi o antieroi dai toni cupi e drammatici, senza Batman né titoli della saga esclusa. A rispetta l’esclusione, ma Latin Dragon è un action crime urbano e non un film di supereroi; quindi non soddisfa il requisito principale. La descrizione di A, che 

**Domanda 54** — Un film in cui il protagonista scopre di essere stato manipolato per tutta la vita  (scarto di punteggio nuovo−vecchio: +7)

- NEW-S6: I film più pertinenti sono:

- **[1] The Truman Show (1998)**: Truman scopre che tutta la sua vita, fin dalla nascita, è stata costruita e manipolata per uno spettacolo televisivo.
- **[2] Awareness - La realtà è un’illusione (2023)**: Ian scopre che la sua identità e la sua vita sono fondate su una grande menzogna.
- **[3] The Anomaly (2014)**: Ryan capisce di essere stato sottoposto, a sua insaputa, a un sistema di controllo remoto della mente.
- **[4] Don’t Worry Darling (2022)**: Alice scopre che la realtà in cui vive è stata alterata e imposta attraverso una manipolazione psicologica.
- *
- OLD-NATIVE: Il film più pertinente è [3], in cui il protagonista scopre che tutta la sua vita è stata una menzogna e che lui e gli altri sono in realtà alieni camuffati da esseri umani. [1] è anch’esso parzialmente pertinente: segue un bambino la cui vita, dall’adolescenza all’età adulta, viene filmata e resa pubblica, suggerendo un’esistenza sottoposta al controllo altrui.
- Giudice: B è nettamente migliore: include The Truman Show, una corrispondenza quasi perfetta con la richiesta, oltre a diversi film in cui il protagonista scopre una realtà o un’identità manipolata. Anche Il mondo sul filo e Don’t Worry Darling sono pertinenti. A propone Earthling, dove la vita dei personagg

### Dove il vecchio fa meglio o il nuovo vince di meno

**Domanda 57** — Voglio horror, ma non voglio niente che faccia paura  (scarto di punteggio nuovo−vecchio: -6)

- NEW-S6: La richiesta è contraddittoria: desideri un horror, ma escludi ciò che fa paura. Inoltre, nell’elenco non ci sono film classificati come horror. Nessun titolo è quindi adatto senza violare la tua preferenza.
- OLD-NATIVE: La richiesta è in parte contraddittoria: l’horror mira spesso a suscitare paura. Interpreto quindi il criterio come “horror leggero o ironico, non realmente spaventoso”. L’unico titolo chiaramente adatto è una parodia comica del genere; gli altri puntano su omicidi, gore, serial killer o atmosfere inquietanti.
- Giudice: A riconosce esplicitamente la contraddizione e interpreta la richiesta come horror leggero o parodistico, proponendo un titolo realmente esistente e presentato come parodia comica. Tuttavia, il film può comunque contenere elementi da horror e quindi non garantisce del tutto l’assenza di paura. B evi

**Domanda 21** — Voglio un thriller psicologico, ma niente violenza esplicita, torture o serial killer  (scarto di punteggio nuovo−vecchio: -5)

- NEW-S6: I film più pertinenti sono:

[1] **Dead Star (2025)** – Thriller psicologico centrato sull’ambiguità tra realtà e narrazione, senza elementi espliciti di torture o serial killer nella trama fornita.

[2] **La donna alla finestra (2021)** – Psychological thriller claustrofobico, fondato su paranoia, osservazione e dubbio percettivo; non emergono torture o serial killer dalla descrizione.

[3] **Regali da uno sconosciuto - The Gift (2015)** – Thriller di tensione psicologica basato su segreti, manipolazione e disagio crescente, senza indicazioni di torture o serial killer.

[5] **Transfert (2018
- OLD-NATIVE: I film più pertinenti sono:

[2] *Occupant* (2011) — Thriller psicologico claustrofobico, incentrato sull’isolamento, sulla pressione mentale e sui rapporti umani, senza indicazioni di torture o violenza esplicita nella trama.

[3] *Spellbound* (1945) — Thriller psicologico classico che usa psicoanalisi, traumi e mistero per costruire la suspense, senza serial killer né torture esplicite.

[4] *Pit of Darkness* (1961) — Thriller basato su amnesia, identità e una serie di eventi inquietanti; è adatto se cerchi una componente psicologica, pur non essendo classificato esplicitamente come thriller
- Giudice: A è complessivamente più prudente e segnala esplicitamente quando un titolo è solo parzialmente pertinente. Le sue proposte non risultano incentrate su torture o serial killer e non enfatizzano violenza esplicita, anche se alcuni titoli possono contenere episodi di violenza e Follow Me! è meno propr

**Domanda 40** — Consigliami film simili a Shrek, ma escludi tutti i sequel  (scarto di punteggio nuovo−vecchio: -5)

- NEW-S6: Ecco alcuni film autonomi, senza sequel, simili a *Shrek* per l’uso ironico delle fiabe, l’avventura fantasy e la comicità:

- **[1] Scarpette rosse e i sette nani (2019)** – Rielabora Biancaneve e i sette nani con maledizioni, trasformazioni e umorismo fiabesco.
- **[2] Cenerentola e gli 007 nani (2006)** – Una parodia delle fiabe con personaggi stravaganti e situazioni comiche.
- **[4] Boxtrolls - Le scatole magiche (2014)** – Animazione fantasy-avventurosa, creature bizzarre e satira delle paure della società.
- **[5] Sua Maestà (2011)** – Una commedia fantasy medievale incentrata su una co
- OLD-NATIVE: Ecco film dell’elenco affini a *Shrek* per l’ambientazione fantastica, l’avventura e/o il tono comico, senza includere sequel:

- **[1] The Phantom Tollbooth (1970)** — Animazione fantasy con un viaggio in un mondo magico, pieno di creature e situazioni giocose.
- **[2] Adventures of a Teenage Dragon Slayer** — Commedia fantasy per famiglie con troll, draghi e un protagonista improbabile.
- **[5] The Gamers (2002)** — Avventura fantasy comica che parodia le convenzioni delle missioni eroiche e dei mondi fantastici.
- **[3] Die Abenteuer des Prinzen Achmed (1926)** — Fiaba animata ricca di magi
- Giudice: A offre film generalmente più affini a Shrek, ma include “Cenerentola e gli 007 nani”, che è il sequel di “Happily N'Ever After” e quindi viola l’esclusione di tutti i sequel. Inoltre presenta l’elenco come privo di sequel in modo fuorviante. B è meno vicino a Shrek per tono e notorietà, ma i titoli

### Violazioni residue nelle risposte finali (film consigliati che violano un'esclusione)

- NEW-S6, domanda 4 «Voglio un film di guerra realistico come Salvate il soldato Ryan, ma s…»: Orizzonti di gloria (The film centers on a disastrous battlefield attack and its military consequences.); Cielo di fuoco (Its main subject is a bomber unit's combat missions and the pressures of aerial warfare.)
- OLD-NATIVE, domanda 4 «Voglio un film di guerra realistico come Salvate il soldato Ryan, ma s…»: Age of Heroes (This realistic World War II commando film is centered on a dangerous combat mission and fr)
- OLD-NATIVE, domanda 6 «Voglio fantascienza distopica come Blade Runner 2049, ma senza intelli…»: Impostor (The plot centrally revolves around alien-made replicants, which violates the ban on artifi)
- NEW-S6, domanda 9 «Consigliami film di sopravvivenza come The Revenant, ma senza ambienta…»: Hostiles - Ostili (The dangerous frontier escort journey contains survival elements but includes wintry, snow)
- OLD-NATIVE, domanda 9 «Consigliami film di sopravvivenza come The Revenant, ma senza ambienta…»: Dances with Wolves (This is primarily an epic Western about frontier life and cultural contact, and it include)
- NEW-S6, domanda 21 «Voglio un thriller psicologico, ma niente violenza esplicita, torture …»: La donna alla finestra (It is a psychological thriller, but its murder mystery includes explicit violent confronta)
- OLD-NATIVE, domanda 23 «Consigliami horror atmosferici, ma senza jump scare, possessioni o tor…»: Don't Look Up (It is atmospheric supernatural horror, but its haunting includes sudden scares and potenti); Nella stretta morsa del ragno (Its gothic supernatural atmosphere is strong, but the ghost appearances include sudden sho)
- NEW-S6, domanda 24 «Voglio drammi intensi, ma senza malattie terminali o lutti familiari…»: Synecdoche, New York (An intense psychological drama, but Caden's serious progressive illness and death violate )
- OLD-NATIVE, domanda 24 «Voglio drammi intensi, ma senza malattie terminali o lutti familiari…»: Long Day's Journey into Night (An intense family drama involving tuberculosis and the death of a family member.); Mothers & Daughters (Its intense family drama prominently includes a mother suffering from Alzheimer's disease.)
- NEW-S6, domanda 26 «Voglio commedie romantiche, ma senza triangoli amorosi e tradimenti…»: The Pill - La pillola del giorno dopo (It is a romantic comedy involving Fred's girlfriend, his affair with Mindy, and a resultin)
- OLD-NATIVE, domanda 26 «Voglio commedie romantiche, ma senza triangoli amorosi e tradimenti…»: Drive Me Crazy (It is a romantic comedy built around fake dating, jealousy, and multiple competing romanti); Friends with Benefits (It is a romantic comedy, but Jamie, Dylan, and other romantic partners create overlapping )
