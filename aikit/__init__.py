"""aikit — il toolkit del corso, un modulo riusabile per lezione.

Undici moduli in tutto, costruiti nel corso delle lezioni:
  - loaders/ (Modulo 2 · Lezione 4): load(path) -> list[Document], dispatch per formato.
  - clean.py (Modulo 2 · Lezione 5): pipeline di pulizia componibile, pipeline_for(path).
  - llm_client.py (Modulo 2 · Lezione 3): LLMClient, il pattern prompt-as-function; cost_usd().
  - embeddings.py (Modulo 2 · Lezione 7): embed() con backend selezionabile, cosine.
  - search.py (Modulo 2 · Lezione 8): la ricerca brute-force scritta da voi.
  - vectorstore.py (Modulo 2 · Lezione 9-10): la collection ChromaDB.
  - chunk.py (Modulo 2 · Lezione 10): le tre strategie di chunking.
  - rag.py (Modulo 3 · Lezione 2): la pipeline del modulo — indicizza(),
    recupera(), genera(), rispondi() e CONFIG; le regole del prompt in
    ISTRUZIONI (modificato in aula a Modulo 3 · Lezione 3).
  - hybrid.py (Modulo 3 · Lezione 4): BM25 accanto al semantico, fusi con
    RRF — costruisci_indice_bm25(), cerca_bm25(), rrf(), cerca_hybrid().
  - rerank.py (Modulo 3 · Lezione 5): il secondo stadio — rerank_cohere(),
    rerank_llm(), cerca_due_stadi().
  - tools.py (Modulo 3 · Lezione 7-8): il giro del tool calling e i quattro
    tool — Calcolatrice/calcolatrice, DataOggi/data_oggi, QueryDb/query_db
    (text-to-SQL in sola lettura su dataset/lumen.db), PrezzoProdotto/
    prezzo_prodotto (la query fissa), definisci_tool(). Promosso oggi.

Oggi (Modulo 3 · Lezione 9) `working/assistente.py` ne richiama TRE: rag
(rag.recupera() dentro il tool cerca_documenti, rag.CONFIG per il nome
della collection, rag.indicizza() se la collection manca), tools (gli
schemi e le funzioni dei quattro tool, e definisci_tool(): la lista TOOLS,
esegui() e il giro chiedi() l'assistente li ha suoi) e vectorstore
(apri_collection() per sapere se il corpus è già indicizzato), più
cost_usd() di llm_client. hybrid e rerank restano a disposizione (il «se
finisci prima» usa hybrid.cerca_hybrid()), ma non sono richiesti. chat.py
di Modulo 3 · Lezione 3 resta fuori: l'assistente è single-turn, ogni
domanda è a sé (l'aikit non è cumulativo).

Le docstring dei singoli moduli raccontano la lezione in cui sono nati: i
riferimenti a file o TODO di quelle lezioni (cerca_chunk,
prepara_collection.py, "Lab 2", "TODO 1") non riguardano questa cartella.
"""
