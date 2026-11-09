"""Glue to OpenAI: the LLM reorder, the embedder and the parser call. The only module of this package that talks to a model."""
from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from .index import Item
from .search import Embed, Reorder
from .signals import INSTRUCTIONS, SeriesSignals

class Order(BaseModel):
    indices: list[int]


def make_reorder(model: str = "gpt-5.6-sol", effort: str | None = "none", plot_chars: int = 1000, client=None, on_usage=None) -> Reorder:
    c = client or _openai(max_retries=2, timeout=90)
    extra = {"reasoning": {"effort": effort}} if effort else {}

    def reorder(request: str, sg: SeriesSignals, cands: list[Item]) -> list[int]:
        lines = "\n".join(f"[{i}] {x.label()} | {x.text[:plot_chars]}" for i, x in enumerate(cands))
        prompt = (f"Request: {request}\nWanted ({sg.level}): {sg.positive_en}\nAvoid traits: {'; '.join(sg.avoid_descriptions_it) or '-'}\n"
                  f"Avoid titles: {', '.join(sg.avoid_titles) or '-'}\n\nCandidates:\n{lines}")
        r = c.responses.parse(model=model, instructions="You rank candidate TV series/seasons/episodes for a search request. Use your own knowledge of every work. "
                              "Best = satisfies ALL the wanted traits and the explicit exclusions; a candidate showing a trait to avoid goes last. Return ALL candidate "
                              "indices, best first, each once.", input=prompt, text_format=Order, **extra)
        if r.output_parsed is None:
            raise RuntimeError("the reorder returned no output")
        if on_usage:
            on_usage("reorder", getattr(r, "usage", None))
        return list(r.output_parsed.indices)
    return reorder


def _openai(**kw):
    from openai import OpenAI
    return OpenAI(**kw)


def make_embed(model: str = "text-embedding-3-large", dimensions: int = 1536, client=None, on_usage=None) -> Embed:
    c = client or _openai(max_retries=2, timeout=60)

    def embed(texts: list[str]) -> np.ndarray:
        r = c.embeddings.create(model=model, input=texts, dimensions=dimensions)
        if on_usage:
            on_usage("embedding", getattr(r, "usage", None))
        return np.vstack([np.asarray(d.embedding, dtype=np.float32) for d in r.data])
    return embed


def make_parse(model: str = "gpt-5.6-luna", effort: str | None = None, client=None, on_usage=None):
    c = client or _openai(max_retries=2, timeout=60)
    extra = {"reasoning": {"effort": effort}} if effort else {}

    def parse(question: str) -> SeriesSignals:
        r = c.responses.parse(model=model, instructions=INSTRUCTIONS, input=question, text_format=SeriesSignals, **extra)
        if r.output_parsed is None:
            raise RuntimeError("the parser returned no output")
        if on_usage:
            on_usage("parser", getattr(r, "usage", None))
        return r.output_parsed
    return parse
