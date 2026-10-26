# Protocollo di migrazione Chroma → Qdrant

Fissato il 2026-10-26, **prima** di catturare qualunque baseline di retrieval. Non si modifica dopo aver visto i dati; un cambio richiede una nuova versione datata con motivazione.

## Soglie approvate dall'utente

Proposte, non verità assolute: ogni differenza significativa va spiegata (causa, effetto sul prodotto). Due motori diversi non devono restituire sempre lo stesso ordinamento.

| Metrica | Soglia | Riferimento |
|---|---|---|
| recall@10 | >= 0,95 | ricerca esatta (scansione completa) sullo stesso indice |
| recall@50 (`fetch_k`) | >= 0,90 | idem |
| tolleranza di similarità coseno sui pareggi | 1e-4 (float32) | differenze minori sono "pareggio numerico" |

Classificazione degli ordinamenti diversi:
- **pareggio numerico**: |Δ similarità| entro la tolleranza;
- **differenza significativa**: un elemento esce dal top-k con Δ > tolleranza, o un'inversione tra posizioni con Δ > tolleranza.

Un recall sotto soglia con causa documentata e innocua non è di per sé un fallimento, ma va riportato.

## Regola sui riferimenti omonimi / remake (decisione dell'utente)

- Un riferimento `resolved` (da evitare) esclude il suo `movie_id` **e ogni chunk con lo stesso `title_norm`** (remake e omonimi inclusi).
- Ogni esclusione per omonimia è registrata nel trace (`excluded_same_title`: titolo, anno, `movie_id`) e riportata al prompt.
- Se l'utente chiede esplicitamente il remake, quel titolo non è un riferimento da evitare e la regola non si applica.
- `ambiguous`: nessun vettore usato, nessuna esclusione per solo titolo; il riferimento è dichiarato non risolto. Eccezione: `(title_norm, release_year_int)` esatti se l'utente ha dato l'anno.
- `not_in_index` / `estimated`: esclusione per `title_norm` esatto con l'anno quando noto; senza anno vale la regola prudente di `hard_exclusions`, dichiarata nel trace.

## Baseline

- Backup verificato: `~/Backups/NetflixScout/pre-qdrant-20261026/` (copia di `dbVettoriale/openai`, manifest SHA-256 di originale e copia identici, originale invariato dopo la copia); manifest SHA-256 anche di `dataset/`.
- Tag git locale `pre-qdrant` su `816bf02` (nessun push).
- Suite offline di partenza: 1554 test passati in 15,6 s, nessun fallimento preesistente, albero git pulito.

## Valutazione umana

Un solo valutatore, ~20-30 casi: evidenza indicativa, non dimostrazione statistica. Senza valutazione la qualità è "non verificata".

## Aggiornamento 2026-10-26 (dopo lo spike della Fase 2) - validazione dei vettori

Qdrant con distanza coseno normalizza i vettori in scrittura; i vettori OpenAI in Chroma hanno norma 1 +- 5e-4. `array_equal` fallirebbe per costruzione. Decisione dell'utente: la validazione esatta dei vettori della Fase 3 diventa

- per **ogni** punto: `|| qdrant_vector - chroma_vector / ||chroma_vector|| ||_inf <= 1e-6` (float32), con l'errore massimo osservato registrato nel report;
- dimensione 1536 per ogni punto, conteggio e id invariati.

Tolleranza fissata prima della migrazione; non si modifica dopo aver visto i dati. Il ranking per coseno non cambia con la normalizzazione.

## Aggiornamento 2026-10-26 (prima della Fase 5) - come si valutano i risultati

Registrato **prima** di misurare qualunque variante. Le soglie gia' approvate (recall@10 >= 0,95; recall@50 >= 0,90; tolleranza 1e-4) non cambiano e nessun risultato viene reinterpretato per farlo passare.

### Regola di lettura delle soglie (decisione dell'utente)
- **Criterio aggregato:** la media sulle query/casi.
- **Controllo obbligatorio per singola query/caso:** il minimo. Ogni valore sotto soglia e' un'**eccezione da documentare** (causa, effetto, se e' presente anche nel riferimento), mai omessa e mai riassorbita nella media.
- Una fase con eccezioni non documentate non e' superata. Le eccezioni documentate non cambiano l'esito del criterio aggregato ma restano nel resoconto.
- Applicazione retroattiva alla Fase 4 (gia' misurata): media rispettata; eccezione q17 (recall@10 = 0,90) documentata in `phase4/phase4_report.md`.

### Fase 5 - varianti, dati e criteri (congelati prima della misura)
- **A** ricerca normale (nessun riferimento); **B** `average_vector`; **C** `best_score`. Stessi casi, stessi vettori del testo, stessa pool (`fetch_k` = 50, k = 10), ricerca **esatta** per isolare l'effetto della strategia dall'approssimazione HNSW (controllo di coerenza HNSW `ef`=128 a parte), stesso testo come primo esempio positivo (peso 1: il peso del testo NON viene esplorato).
- Nessuna chiamata a pagamento: i casi usano i vettori del testo gia' salvati nella baseline e i vettori dei film presi dall'indice. Il percorso "descrizione stimata" per film assenti richiede un embedding nuovo e **non e' misurato** in questa fase.
- I casi sono in `phase5/cases.json` e il loro hash SHA-256 e' registrato in `phase5/cases.sha256` prima di qualunque misura.

### Metriche automatiche (top-10 finale), per variante e per caso
1. pertinenza al testo: coseno medio tra i 10 risultati e il vettore del testo;
2. vicinanza ai positivi: coseno medio ai film positivi risolti (e il positivo meno servito);
3. distanza dai negativi: coseno medio ai film negativi risolti (e il massimo su un singolo risultato);
4. violazioni dei vincoli del caso (genere escluso, genere richiesto assente, fuori intervallo di anni; anno ignoto contato a parte);
5. presenza accidentale dei riferimenti (per `movie_id` e per titolo normalizzato): atteso 0;
6. sovrapposizione con A; rischio dei vettori mediati: massimo coseno a un singolo positivo per risultato (media e minimo);
7. latenza (mediana di 5 esecuzioni).

### Criteri di accettazione di una variante rispetto ad A (tutti necessari)
1. **Negativi (soglia scelta dall'utente):** sui casi con almeno un negativo risolto, calo medio del coseno medio ai negativi >= 0,02 **e** calo in >= 60% di quei casi.
2. **Pertinenza al testo:** calo medio <= 0,02 su tutti i casi con riferimenti; controllo per caso: nessun caso con perdita > 0,05 (eccezioni documentate).
3. **Positivi:** calo medio del coseno ai positivi <= 0,02; controllo per riferimento: nessun positivo con perdita > 0,05 (eccezioni documentate).
4. **Vincoli:** violazioni totali non maggiori di A; per caso nessun aumento (eccezioni documentate).
5. **Riferimenti nei risultati:** 0 in tutti i casi.
6. **Controllo senza riferimenti validi** (ambigui, assenti, nessuno): risultati identici ad A (id e ordine) nel 100% dei casi.
La latenza e' riportata, non e' un criterio. Un calo della similarita' ai negativi da solo non basta. Se nessuna variante soddisfa tutti i criteri l'esito e' **"nessuna variante migliora abbastanza la baseline"** e la ricerca normale resta invariata.

### Valutazione qualitativa
Separata dai risultati automatici. Schede anonime (varianti in ordine casuale, etichette X/Y/Z, chiave in file separato) con griglia 0/1/2 su pertinenza alla richiesta, vicinanza al positivo, assenza del tratto negativo, correttezza dei fatti. Le compila l'utente; fino ad allora la qualita' e' **non verificata**. Un solo valutatore: evidenza indicativa, non statistica.
