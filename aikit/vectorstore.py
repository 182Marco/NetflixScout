"""vectorstore.py — la collection ChromaDB, da oggi nel toolkit aikit/.

È il modulo che avete scritto a Modulo 2 · Lezione 9 (la collection persistente su
disco, l'upsert con embedding ESPLICITI, la ricerca che parla in score),
promosso in aikit/ — lo stesso percorso di embeddings.py (Modulo 2 · Lezione 7) e search.py
(Modulo 2 · Lezione 8). NON si tocca, si importa:

    from aikit import vectorstore

    collection = vectorstore.apri_collection("lumen_chunks")
    risultati = vectorstore.search(collection, "una domanda", 3)

È questo il `search` sul vector DB — non va confuso con
`aikit.search.search()`, il brute-force in-memory di Modulo 2 · Lezione 8 tenuto per
confronto, che `cerca_chunk` non usa.

`cerca_chunk` (già scritto, di Modulo 2 · Lezione 11) usa SOLO `apri_collection()`: la
riapre così com'è, non la ricrea mai. `crea_collection()` invece è per chi
rigenera da zero la collection — `prepara_collection.py` (la riserva) e,
oggi (Modulo 2 · Lezione 12), `reindicizza_chunks` nel Lab 2 (TODO 4 di `rag.py`), quando si
cambia strategia/size di chunking e si ri-indicizza.
"""
from pathlib import Path

import chromadb

from aikit.embeddings import embed

CHROMA_DIR = Path(__file__).parent.parent.parent / "chroma"


def apri_collection(nome):
    """La collection su disco: la crea la prima volta, poi la riapre (Modulo 2 · Lezione 9)."""
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return client.get_or_create_collection(
        nome, metadata={"hnsw:space": "cosine"}   # la metrica di Modulo 2 · Lezione 7-9
    )


def crea_collection(nome):
    """Come apri_collection(), ma da ZERO: se la collection esiste la cancella.

    Usata da `prepara_collection.py` per ricostruire la riserva e, a Modulo 2 · Lezione 12,
    da `reindicizza_chunks` (Lab 2) quando si cambia strategia/size. Il
    retrieval (`cerca_chunk`) NON la chiama: la collection va riaperta con
    `apri_collection`, non ricreata a ogni domanda.
    """
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    if nome in [c.name for c in client.list_collections()]:
        client.delete_collection(nome)
    return client.create_collection(nome, metadata={"hnsw:space": "cosine"})


def indicizza(collection, ids, testi, embeddings, metadatas=None):
    """Upsert con embedding ESPLICITI (mai l'embedder di default del DB)."""
    collection.upsert(ids=ids, documents=testi, embeddings=embeddings,
                      metadatas=metadatas)


def search(collection, query, k, backend="openai"):
    """I k documenti più simili alla query, dal più simile in giù.

    Ogni risultato è un dict {"id", "testo", "score", ...metadata}: la query
    viene embeddata nello stesso spazio del corpus (regola di Modulo 2 · Lezione 8) e il DB
    risponde in DISTANZE — lo score è 1 - distanza, come a Modulo 2 · Lezione 9. L'"id"
    (es. "manuale-lumadesk-007") è la fonte da citare nel prompt RAG.
    """
    q = embed([query], backend=backend)[0]
    ris = collection.query(query_embeddings=[q], n_results=k)
    risultati = []
    for i in range(len(ris["ids"][0])):
        r = {
            "id": ris["ids"][0][i],
            "testo": ris["documents"][0][i],
            "score": 1 - ris["distances"][0][i],
        }
        if ris["metadatas"][0][i]:
            r.update(ris["metadatas"][0][i])
        risultati.append(r)
    return risultati
