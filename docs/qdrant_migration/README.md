# Ricerca semantica RAG su Qdrant - guida d'insieme

Stato finale: **Qdrant è l'unico motore.** ChromaDB è stato rimosso da codice, dipendenze, configurazione e test. Gli strumenti di migrazione, il ritorno a Chroma e gli script di confronto con Chroma sono stati cancellati; i report di fase in questa cartella sono un registro **storico** della migrazione e citano Chroma per questo.

## Perché una ricerca semantica
Le raccomandazioni di NetflixScout non devono dipendere dalle parole esatte. "Un film su un uomo che perde i ricordi e cerca chi è" deve trovare
una trama che parla di amnesia e identità anche se non contiene quelle parole. Per questo ogni trama del corpus (CMU Movie Summary Corpus) è trasformata
da un modello (`text-embedding-3-small`) in un **vettore di 1536 numeri**: testi con significato vicino hanno vettori vicini. La domanda dell'utente, riscritta
in inglese dal parser dei segnali (`semantic_query`), diventa un vettore con lo stesso modello e si cercano le trame più vicine (similarità del coseno).
Quando serve una parola concreta (un personaggio, un luogo) la modalità `hybrid` aggiunge la ricerca per parole chiave (BM25) e fonde le due liste con RRF.

## Come funziona la ricerca RAG (flusso)
1. L'orchestratore sceglie `rag_search` per raccomandazioni e ricerche per trama, temi, emozioni.
2. `retrieval.py` estrae i segnali (generi, decennio, vincoli, `semantic_query`); `vectorstore.search` incorpora `semantic_query` e interroga il motore (`fetch_k` candidati).
3. Boost di genere, esclusioni, eventuale BM25 e RRF; `rerank.py` (Cohere `rerank-v3.5`) riordina; `constraints.py` etichetta ogni vincolo (verificato / probabile / non verificabile / contraddetto).
4. `TmdbRagEnricher` aggiunge regia, cast e voti dei candidati verificati; solo l'orchestratore scrive la risposta.

## Come Qdrant conserva e recupera i vettori
Una **collezione** (`netflix_scout`) contiene 42.522 **punti**. Ogni punto ha: il vettore (1536 float, distanza coseno), il **payload** (il testo della trama come `document`,
i metadati `title`, `release_year`, `genres`, `cast`, `movie_id`..., il vecchio id stringa come `legacy_id`, `title_norm` per le ricerche per titolo, `release_year_int` intero)
e un id UUID ricavato in modo deterministico dal vecchio id (`uuid5`). La ricerca usa un indice **HNSW** (approssimato e veloce, ~6 ms a query sul server); la modalità
`exact=True` fa la scansione completa ed è il riferimento con cui si misura la qualità. Il server mantiene gli indici sui campi usati dai filtri.

## Cosa è cambiato
- **Codice**: pacchetto `tool/rag/FromQueryEmbeddingToRes/store/` (contratto `VectorStore`, `QdrantStore`, adattatore `QdrantCollection` con la superficie di lettura usata da `search` e BM25, id e normalizzatori, versioni client/server fissate insieme); `references.py` (riferimenti "come X", spento); catalogo TMDb (spento).
- **Configurazione**: `CONFIG["rag"]["vectorstore"]` con `engine` (predefinito `qdrant`) e `qdrant.{mode,url,path}`; variabili `VECTORSTORE_ENGINE`, `VECTORSTORE_QDRANT_MODE|URL|PATH`, `QDRANT_API_KEY` (letta in un solo punto).
- **Architettura**: terminale, chat legacy, API web e builder partono dalla stessa configurazione (`build_ready_app_or_exit`); il server irraggiungibile dà un messaggio di una riga.
- **Costruzione dell'indice**: `buildSemanticDb.py` crea una collezione nuova, non sostituisce mai nulla (vedi `rebuild.md`).
- **Strumenti**: `backup_storage.py`, `compare_indexes.py`, `scripts/start_qdrant.sh`.

## Migrazione dei 42.522 elementi e verifiche di equivalenza
- I vettori OpenAI esistenti sono stati **trasferiti senza rigenerarli** (da una copia di Chroma); validazione di tutti i punti: conteggio, id, dimensione, documenti, ogni metadato, vettori (errore massimo 5,96e-8 sul vettore normalizzato, tolleranza 1e-6), campi derivati. Un solo anno non convertibile (*Hunting Season*, "1010"), riportato e non inventato.
- Parità del recupero (28 query fisse, riferimento = ricerca esatta): recall@10 medio 0,996 (minimo 0,90) e recall@50 0,993 per Qdrant; Chroma 0,979 e 0,931. Nessuna regressione reale (`phase4/`).
- **Ricostruzione dai dataset** (OpenAI reale, server reale): 42.522 punti, id/documenti/metadati identici all'indice migrato; coseno medio fra i vettori 0,999995 (minimo 0,994); top-10 e top-50 identici su 28/28 query (`rebuild/rebuild_report.md`).
- Integrità: l'indice migrato è identico (202 file, hash) alla copia di backup dopo le prove; Chroma originale e backup non sono stati cancellati.

## Come avviare, eseguire, testare
- **Server**: vedi `server.md` (comando esatto e directory). **Progetto**: `python app.py` (terminale) o `uvicorn web_api.main:app --host 127.0.0.1 --port 8000` (un solo worker).
- **Test offline** (senza server): `python -m pytest tests -q`; i test che richiedono un server saltano **con il motivo** se non risponde. **Con server temporaneo isolato**: avviare un server su uno storage vuoto (porta 6401) e `QDRANT_URL=http://127.0.0.1:6401 python -m pytest tests -m qdrant_server`. Mai puntare i test sullo storage reale.

## Chroma
Rimosso: non esiste più un ritorno a Chroma. La cartella `dbVettoriale/openai` (vecchio indice) è un dato inutilizzato che si può cancellare a mano.

## Risultati dei test reali
Due batterie di 20 domande con servizi reali: `phase7/phase7_report.md` (14 complete, 5 parziali, 1 corretta durante il test) e `phase7/phase7_report_v2.md` (13 complete, 5 parziali, 2 errate). Nessun problema infrastrutturale.

## Limiti e questioni aperte
- Immagine Docker non provata (nessun runtime): provato solo il binario ufficiale 1.20.0 (`docker_status.md`).
- Il binario Qdrant sta in `bin/qdrant` (ignorato da git); va riscaricato se manca (`server.md`).
- Errori di risposta aperti: reranker che preferisce una menzione di passaggio (r04), follow-up "più recente" che propone film non usciti (f01), soglia di voti scelta dall'utente non supportata (d01), "più votati" ambiguo (d02).
- Catalogo TMDb: implementato e provato offline e sul server (concorrenza), **spento e non calibrato** (`catalog/`).
- Costo delle batterie reali non misurato.
