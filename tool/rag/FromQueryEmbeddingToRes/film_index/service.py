"""Glue to OpenAI: the embedder, the parser call and the LLM reorder, all configured from `CONFIG["rag"]`."""
from __future__ import annotations

from functools import lru_cache

import numpy as np
from openai import OpenAI

from . import parser
from .index import Film
from .models import Order, Signals

RERANK_INSTRUCTIONS = (
    "You rank candidate films for a recommendation request. Use your own knowledge of every film. Best = satisfies ALL the wanted traits, genre and "
    "the explicit exclusions of the request. A candidate that shows ANY trait the user wants to avoid, belongs to an excluded franchise or is a cited "
    "film goes last, even if it is otherwise a perfect match for the positive part. Do not prefer a film because it is famous. "
    "Return {top_rule}")


@lru_cache(maxsize=1)
def openai_client() -> OpenAI:
    return OpenAI(max_retries=2, timeout=60)


def make_embed(model: str, dimensions: int | None, client: OpenAI | None = None):
    def embed(texts: list[str]) -> np.ndarray:
        kw = {"dimensions": dimensions} if dimensions else {}
        r = (client or openai_client()).embeddings.create(model=model, input=texts, **kw)
        return np.vstack([np.asarray(d.embedding, dtype=np.float32) for d in r.data])
    return embed


def make_parse(model: str, effort: str | None, client: OpenAI | None = None):
    return lambda question: parser.parse(question, client=client or openai_client(), model=model, effort=effort)


def make_reorder(cfg: dict, client: OpenAI | None = None):
    """LLM list-wise reorder of the candidates. Raises on failure: the caller keeps the penalty order."""
    plot_chars = int(cfg.get("plot_chars", 450))
    top = cfg.get("top")
    rule = f"only the {top} best candidate indices, best first, each once." if top else "ALL candidate indices, best first, each once."
    extra = {"reasoning": {"effort": cfg["effort"]}} if cfg.get("effort") else {}

    def reorder(request: str, s: Signals, cited: list[str], cands: list[Film]) -> list[int]:
        lines = "\n".join(f"[{i}] {f.label()} | {', '.join(f.genres[:4])} | {f.plot[:plot_chars]}" for i, f in enumerate(cands))
        prompt = (f"Request: {request}\nWanted: {s.positive_en}\nAvoid traits: {'; '.join(s.avoid_descriptions_en) or '-'}\n"
                  f"Avoid franchises: {', '.join(s.avoid_franchise_names) or '-'}\nCited films (exclude): {', '.join(cited) or '-'}\n\nCandidates:\n{lines}")
        r = (client or openai_client()).responses.parse(model=cfg["model"], instructions=RERANK_INSTRUCTIONS.format(top_rule=rule), input=prompt,
                                                        text_format=Order, **extra)
        if r.output_parsed is None:
            raise RuntimeError("the reorder returned no output")
        return list(r.output_parsed.indices)
    return reorder
