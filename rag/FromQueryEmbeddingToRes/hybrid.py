"""Keyword and hybrid retrieval helpers."""
import re
from rank_bm25 import BM25Okapi


def tokenizza(testo):
    """Tokenize text for keyword search."""
    return re.findall(r"\w+", testo.lower())


def costruisci_indice_bm25(collection):
    """Build a BM25 index from every document stored in a collection."""
    dati = collection.get()
    chunks = []
    for i in range(len(dati["ids"])):
        chunks.append({
            "id": dati["ids"][i],
            "testo": dati["documents"][i],
            **(dati["metadatas"][i] or {}),
        })
    corpus_token = [tokenizza(chunk["testo"]) for chunk in chunks]
    return {
        "bm25": BM25Okapi(corpus_token),
        "chunks": chunks,
    }


def cerca_bm25(query, indice, k):
    """Return the top-k BM25 matches for a query."""
    punteggi = indice["bm25"].get_scores(tokenizza(query))
    ordine = sorted(range(len(punteggi)), key=lambda i: punteggi[i], reverse=True)
    risultati = []
    for i in ordine[:k]:
        risultati.append({**indice["chunks"][i], "score": float(punteggi[i])})
    return risultati


def rrf(liste, k, rrf_costante=60):
    """Fuse ranked lists with Reciprocal Rank Fusion."""
    somme = {}
    visti = {}
    for lista in liste:
        for posizione, chunk in enumerate(lista, start=1):
            somme[chunk["id"]] = somme.get(chunk["id"], 0) + 1 / (rrf_costante + posizione)
            visti[chunk["id"]] = chunk
    migliori = sorted(somme, key=somme.get, reverse=True)[:k]
    return [{**visti[cid], "score": somme[cid]} for cid in migliori]


def cerca_hybrid(risultati_semantici, risultati_bm25, k, rrf_costante=60):
    """Fuse semantic and keyword rankings into a single top-k result list."""
    return rrf([risultati_semantici, risultati_bm25], k, rrf_costante=rrf_costante)
