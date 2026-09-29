"""search.py — la ricerca brute-force di Modulo 2 · Lezione 8, da oggi nel toolkit aikit/.

È il modulo che avete scritto a Modulo 2 · Lezione 8 (top-k + MMR), promosso nel
toolkit aikit/ — lo stesso percorso che embeddings.py ha fatto a Modulo 2 · Lezione 8.
NON si tocca, si importa. Serve da termine di confronto storico: la stessa
ricerca la fa il vector DB (Modulo 2 · Lezione 9+), e i documenti in testa devono essere gli
stessi.

    from aikit.search import search
    search("Quanto costa la spedizione?", 3)

Non è questo il `search` usato da `cerca_chunk`: `cerca_chunk` usa
`vectorstore.search()`, sul vector DB — questo resta il brute-force
in-memory di Modulo 2 · Lezione 8, tenuto per confronto.
"""
import json

from pathlib import Path

import numpy as np

from aikit.embeddings import embed, cosine_similarity

DATASET = Path(__file__).parent.parent.parent / "dataset"


def carica_corpus():
    """Riapre il corpus di Modulo 2 · Lezione 7: restituisce (docs, vectors, backend)."""
    vectors = np.load(DATASET / "corpus_embeddings.npz")["vectors"]
    meta = json.loads((DATASET / "corpus_meta.json").read_text(encoding="utf-8"))

    per_id = {}
    for riga in (DATASET / "corpus_lumen.jsonl").read_text(encoding="utf-8").splitlines():
        if riga.strip():
            doc = json.loads(riga)
            per_id[doc["id"]] = doc

    # i testi nell'ORDINE dei vettori: la riga i del npz è il doc di ids[i]
    docs = [per_id[doc_id] for doc_id in meta["ids"]]
    return docs, vectors, meta["backend"]


def search(query, k):
    """I k testi più simili alla query, dal più simile in giù."""
    docs, vectors, backend = carica_corpus()
    q = embed([query], backend=backend)[0]        # lo STESSO spazio del corpus
    scores = [cosine_similarity(q, v) for v in vectors]
    migliori = np.argsort(scores)[::-1][:k]
    return [{**docs[i], "score": scores[i]} for i in migliori]


def search_mmr(query, k, lambda_):
    """Come search(), ma i k risultati li sceglie MMR."""
    docs, vectors, backend = carica_corpus()
    q = embed([query], backend=backend)[0]
    sim_query = [cosine_similarity(v, q) for v in vectors]

    scelti = [int(np.argmax(sim_query))]          # il primo è il più rilevante
    while len(scelti) < min(k, len(vectors)):
        migliore = None
        punteggio_migliore = None
        for c in range(len(vectors)):
            if c in scelti:
                continue
            somiglianza_scelti = max(
                cosine_similarity(vectors[c], vectors[s]) for s in scelti
            )
            punteggio = lambda_ * sim_query[c] - (1 - lambda_) * somiglianza_scelti
            if punteggio_migliore is None or punteggio > punteggio_migliore:
                migliore = c
                punteggio_migliore = punteggio
        scelti.append(migliore)

    return [{**docs[i], "score": sim_query[i]} for i in scelti]
