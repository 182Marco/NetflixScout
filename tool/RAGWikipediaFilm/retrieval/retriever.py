"""The retriever to integrate: ONE dense search over ONE collection, with the request's positive filters and exclusions applied inside it.

    r = WikipediaRetriever()
    out = r.search("Consigliami horror psicologici come Hereditary, ma senza possessioni", k=5)

Pipeline = the best configuration measured in eval/results (S6f): filters (year, country, director, actor, rare plot words) evaluated by Qdrant,
the cited films removed, franchises removed by id, genre/format exclusions, semantic penalty of the traits to avoid on a pool of 300, and a final
list-wise LLM reorder of the top 25. `rerank=False` is the fast variant (S5f, no LLM call after the parse). Nothing here writes to Qdrant."""
from __future__ import annotations

from . import parser, strategies as S
from .corpus import Corpus, new_corpus
from .models import Signals


class WikipediaRetriever:
    def __init__(self, corpus: Corpus | None = None):
        self.corpus = corpus or new_corpus()

    def search(self, question: str, *, k: int = S.K, rerank: bool = True, signals: Signals | None = None) -> dict:
        signals = signals or parser.parse(question)
        ctx = S.build_context(self.corpus, signals)
        out = S.STRATEGIES["S6f"](ctx, k, request=question) if rerank else S.STRATEGIES["S5f"](ctx, k)
        return {"films": out["films"], "signals": signals, "contradictory": signals.contradictory,
                "contradiction_note": signals.contradiction_note, "trace": {**out["trace"], "coverage": ctx.coverage}}
