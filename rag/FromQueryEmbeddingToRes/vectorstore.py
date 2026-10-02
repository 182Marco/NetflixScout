"""Persistent vector store helpers backed by ChromaDB."""
from pathlib import Path

import chromadb

from .embeddings import embed

DB_ROOT = Path("dbVettoriale")


def db_dir_for_backend(backend):
    """Return the persistent directory associated with an embedding backend."""
    if backend not in ("openai", "local"):
        raise ValueError(
            f"backend {backend!r} sconosciuto: "
            "'openai' o 'local'"
        )
    return DB_ROOT / backend


def _resolve_db_dir(db_dir=None, backend=None):
    if db_dir is not None:
        return Path(db_dir)
    if backend is None:
        raise ValueError("Serve db_dir oppure backend.")
    return db_dir_for_backend(backend)


def apri_collection(nome, db_dir=None, backend=None):
    """Open a persistent collection, creating it on first access."""
    persist_dir = _resolve_db_dir(db_dir=db_dir, backend=backend)
    client = chromadb.PersistentClient(path=str(persist_dir))
    return client.get_or_create_collection(
        nome,
        metadata={"hnsw:space": "cosine"},
    )


def crea_collection(nome, db_dir=None, backend=None):
    """Create a collection from scratch, deleting an existing one if needed."""
    persist_dir = _resolve_db_dir(db_dir=db_dir, backend=backend)
    client = chromadb.PersistentClient(path=str(persist_dir))
    if nome in [c.name for c in client.list_collections()]:
        client.delete_collection(nome)
    return client.create_collection(nome, metadata={"hnsw:space": "cosine"})


def indicizza(collection, ids, testi, embeddings, metadatas=None):
    """Upsert explicit embeddings into a Chroma collection."""
    collection.upsert(
        ids=ids,
        documents=testi,
        embeddings=embeddings,
        metadatas=metadatas,
    )


def search(collection, query, k, backend, model):
    """Return the top-k most similar documents for a query."""
    q = embed([query], backend=backend, model=model)[0]
    ris = collection.query(query_embeddings=[q], n_results=k)
    risultati = []
    for i in range(len(ris["ids"][0])):
        risultato = {
            "id": ris["ids"][0][i],
            "testo": ris["documents"][0][i],
            "score": 1 - ris["distances"][0][i],
        }
        if ris["metadatas"][0][i]:
            risultato.update(ris["metadatas"][0][i])
        risultati.append(risultato)
    return risultati
