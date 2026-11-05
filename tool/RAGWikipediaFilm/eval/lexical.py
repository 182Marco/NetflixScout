"""A/B of the lexical component on rare plot words: a SINGLE dense ranking in every variant, never a fusion.

    python -m tool.RAGWikipediaFilm.eval.lexical build     # picks rare-term cases from the catalogue and writes Italian queries (LLM, cached)
    python -m tool.RAGWikipediaFilm.eval.lexical run       # D0 dense | L1 dense + full-text filter | L2 BM25 candidate set ordered by the dense score | B BM25 alone (reference only)

Ground truth: the film whose plot contains the rare term (a term found in at most 2 plots of 41.138)."""
from __future__ import annotations

import json
import random
import re
import sys
from collections import Counter

import numpy as np
from pydantic import BaseModel
from qdrant_client import models

from ..retrieval import llm
from ..retrieval.corpus import new_corpus, norm
from .ab import RES, jl_write, pmap

CATALOGUE = RES.parents[1] / "data" / "clean_v3" / "films.v3.jsonl"
N_CASES = 40


class Q(BaseModel):
    question: str


INSTR = ("Scrivi UNA domanda in italiano, naturale, di un utente che cerca un film ricordando poco: una frase vaga sulla premessa (senza il titolo) "
         "che includa esattamente la parola o il nome indicato come dettaglio concreto (es. «… in cui compare un personaggio di nome X»). "
         "Non rivelare altro della trama. Restituisci solo la domanda.")


def tokens(text: str) -> set[str]:
    return set(re.findall(r"\b[A-ZÀ-Ý][\wà-ÿ']{3,}\b", text))


def build():
    films = [json.loads(l) for l in CATALOGUE.open(encoding="utf-8")]
    df = Counter()
    per = {}
    for f in films:
        t = {w for w in tokens(f["synopsis"]) if norm(w) and len(norm(w)) >= 4}
        per[f["film_id"]] = t
        df.update(t)
    rng = random.Random(20261104)
    cands = []
    for f in films:
        rare = [w for w in per[f["film_id"]] if df[w] <= 2 and norm(w) not in norm(f["title"]) and w.lower() not in f["synopsis"].lower().split("«")[0:0]]
        # a term the title does not give away, found in the plot of at most two films
        if rare and f["synopsis"].count(rare[0]) >= 2:
            cands.append((f, sorted(rare)[0]))
    rng.shuffle(cands)
    cases = []
    for f, term in cands[:N_CASES]:
        q = llm.structured(Q, INSTR, f"Titolo (non rivelare): {f['title']}\nTrama: {f['synopsis'][:700]}\nParola o nome da includere: {term}").question
        owners = [g["film_id"] for g in films if term in per[g["film_id"]]]
        cases.append({"film_id": f["film_id"], "title": f["title"], "term": term, "owners": owners, "question": q})
    jl_write("lexical_cases.jsonl", cases)
    print(len(cases), "cases")


def run():
    from rank_bm25 import BM25Okapi
    cases = [json.loads(l) for l in (RES / "lexical_cases.jsonl").open()]
    films = [json.loads(l) for l in CATALOGUE.open(encoding="utf-8")]
    tok = lambda t: re.findall(r"\w+", t.lower())
    bm = BM25Okapi([tok(f["synopsis"]) for f in films])
    ids = [f["film_id"] for f in films]
    corpus = new_corpus()
    vecs = corpus.embed([c["question"] for c in cases])
    out = []
    for c, v in zip(cases, vecs):
        owners = set(c["owners"])
        def hit(ranked):          # rank (1-based) of the first owner within the list, else None
            for i, fid in enumerate(ranked, 1):
                if fid in owners:
                    return i
            return None
        fid = lambda fs: [f.payload["film_id"] if hasattr(f, "payload") else f for f in fs]
        d0 = [x.payload["film_id"] for x in corpus.client.query_points(corpus.collection, query=[float(z) for z in v], limit=50, with_payload=["film_id"]).points]
        term_norm = norm(c["term"])
        l1_flt = models.Filter(must=[models.FieldCondition(key="synopsis", match=models.MatchText(text=c["term"]))])
        l1 = [x.payload["film_id"] for x in corpus.client.query_points(corpus.collection, query=[float(z) for z in v], limit=50, query_filter=l1_flt, with_payload=["film_id"]).points]
        scores = bm.get_scores(tok(c["question"]))
        top = np.argsort(-scores)[:200]
        cand_ids = [ids[i] for i in top]
        b = cand_ids[:50]
        # L2: BM25 only chooses the candidate set; the ORDER is the dense score
        pts = corpus.client.query_points(corpus.collection, query=[float(z) for z in v], limit=50, with_payload=["film_id"],
                                         query_filter=models.Filter(must=[models.FieldCondition(key="film_id", match=models.MatchAny(any=cand_ids))])).points
        l2 = [x.payload["film_id"] for x in pts]
        out.append({"film_id": c["film_id"], "term": c["term"], "owners": len(owners), "D0": hit(d0), "L1": hit(l1), "L2": hit(l2), "BM25_alone": hit(b)})
    jl_write("lexical_results.jsonl", out)
    n = len(out)
    def rate(k, cut):
        return sum(1 for r in out if r[k] is not None and r[k] <= cut) / n
    lines = ["# Componente lessicale: parole rare di trama (UN solo ranking denso in ogni variante)", "", f"{n} domande generate da termini presenti in al più 2 trame.", "",
             "| Variante | hit@1 | hit@5 | hit@10 | trovata (top 50) |", "|---|---|---|---|---|"]
    for k, label in (("D0", "D0 solo denso"), ("L1", "L1 denso + filtro full-text Qdrant"), ("L2", "L2 candidati BM25 ordinati dal punteggio denso"), ("BM25_alone", "BM25 da solo (riferimento, non candidato)")):
        lines.append(f"| {label} | {rate(k,1):.2f} | {rate(k,5):.2f} | {rate(k,10):.2f} | {sum(1 for r in out if r[k] is not None)/n:.2f} |")
    (RES / "LEXICAL_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    {"build": build, "run": run}[sys.argv[1]]()
