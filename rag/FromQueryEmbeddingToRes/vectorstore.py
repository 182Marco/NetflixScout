"""Persistent vector store helpers backed by ChromaDB."""
from pathlib import Path
import re

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


def _normalize_signals(signals):
    normalized = []
    for signal in signals or []:
        text = str(signal).strip()
        if text:
            normalized.append(text)
    return normalized


def _contains_signal(text, signal):
    if not text or not signal:
        return False
    return signal.lower() in text.lower()


def _is_hard_excluded(result, hard_exclusions):
    if not hard_exclusions:
        return False

    title = str(result.get("title") or "")
    movie_id = str(result.get("movie_id") or "")
    source = str(result.get("source") or "")

    for signal in hard_exclusions:
        if (
            _contains_signal(title, signal)
            or _contains_signal(movie_id, signal)
            or _contains_signal(source, signal)
        ):
            return True
    return False


def _count_negative_matches(result, negative_signals):
    if not negative_signals:
        return 0

    fields = [
        str(result.get("title") or ""),
        str(result.get("genres") or ""),
        str(result.get("cast") or ""),
        str(result.get("testo") or ""),
    ]
    haystack = "\n".join(fields)

    matches = 0
    for signal in negative_signals:
        if not signal:
            continue
        # Whole-word-ish match when possible, fallback to substring for multiword phrases.
        if " " in signal:
            if _contains_signal(haystack, signal):
                matches += 1
            continue
        pattern = rf"\b{re.escape(signal.lower())}\b"
        if re.search(pattern, haystack.lower()):
            matches += 1
    return matches


def search(
    collection,
    query,
    k,
    backend,
    model,
    *,
    positive_signals=None,
    negative_signals=None,
    hard_exclusions=None,
    fetch_k=None,
):
    """Return the top-k most similar documents for a query."""
    positive_signals = _normalize_signals(positive_signals)
    negative_signals = _normalize_signals(negative_signals)
    hard_exclusions = _normalize_signals(hard_exclusions)

    semantic_query = " ".join(positive_signals) if positive_signals else query
    q = embed([semantic_query], backend=backend, model=model)[0]

    requested_k = int(fetch_k or k)
    requested_k = max(requested_k, int(k))
    ris = collection.query(query_embeddings=[q], n_results=requested_k)

    # Soft penalty for negative signals: subtract from semantic score, never hard-filter.
    soft_penalty_per_match = 0.08

    risultati = []
    for i in range(len(ris["ids"][0])):
        risultato = {
            "id": ris["ids"][0][i],
            "testo": ris["documents"][0][i],
            "score": 1 - ris["distances"][0][i],
        }
        if ris["metadatas"][0][i]:
            risultato.update(ris["metadatas"][0][i])

        if _is_hard_excluded(risultato, hard_exclusions):
            continue

        negative_matches = _count_negative_matches(risultato, negative_signals)
        if negative_matches > 0:
            risultato["score"] = risultato["score"] - (soft_penalty_per_match * negative_matches)

        risultati.append(risultato)

    risultati.sort(key=lambda item: item.get("score", 0.0), reverse=True)
    return risultati[:k]
