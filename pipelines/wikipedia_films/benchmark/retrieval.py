"""Rankings of every (variant, embedding config) for every query. Film score = max cosine over the film's vectors
(one vector for A/B, several for chunked films). Pure numpy, no network."""
from __future__ import annotations

import json

import numpy as np

from common import RESULTS
from embed import MODELS, shorten
from variants import VARIANTS

CONFIGS = {  # name -> (model, dimensions or None)
    "small-1536": ("text-embedding-3-small", None),
    "large-3072": ("text-embedding-3-large", None),
    "large-1536": ("text-embedding-3-large", 1536),
}
EXTRA_CONFIGS = {"large-1024": ("text-embedding-3-large", 1024)}  # evaluated, not used for pooling


def matrices(model: str, dims: int | None, variant: str):
    d = np.load(RESULTS / f"d_{variant}_{model}.npy")
    q = np.load(RESULTS / f"q_{model}.npy")
    if dims:
        d, q = shorten(d, dims), shorten(q, dims)
    films = json.loads((RESULTS / f"d_{variant}_films.json").read_text())
    return q, d, films


def film_scores(q, d, films):
    """(n_queries, n_films) max-pooled scores; films keep first-appearance order."""
    sims = q @ d.T
    order, starts = [], []
    for i, f in enumerate(films):
        if not order or order[-1] != f:
            order.append(f); starts.append(i)
    return np.maximum.reduceat(sims, starts, axis=1), order


def rankings(configs=None, top=100):
    """{(variant, config): {"films": [...], "top": array (nq, top) of indices into films}}"""
    out = {}
    for cname, (model, dims) in (configs or {**CONFIGS, **EXTRA_CONFIGS}).items():
        for v in VARIANTS:
            q, d, films = matrices(model, dims, v)
            s, order = film_scores(q, d, films)
            idx = np.argsort(-s, axis=1)[:, :top]
            out[(v, cname)] = {"films": order, "top": idx, "scores": np.take_along_axis(s, idx, axis=1)}
    return out
