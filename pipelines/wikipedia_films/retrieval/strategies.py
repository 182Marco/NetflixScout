"""Retrieval strategies, one dense retriever each. Every strategy runs on any `Corpus`; none fuses rankings.

S0  semantic                      the positive description (+ the vectors of the cited reference films), nothing excluded
S1  ids                           S0 without the cited films
S2n franchise by name             S1 without the films whose title carries a franchise name (both corpora)
S2f franchise by id               S1 without the films that share a franchise id with the cited ones (NEW only: the old index has none)
S3  penalty                       pool ranked by cos(r,P) - lam * max_i cos(r,N_i); N = vectors of the described traits to avoid + avoided films
S3b subtraction                   one query vector normalise(P - alpha * mean(N)); a single search
S4  metadata                      genre (and format) exclusions only
S5  combined                      S1 + franchise + genres + penalty
S6  combined + LLM list rerank    the top of S5 reordered by an LLM that reads the constraints
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from pydantic import BaseModel

from . import llm
from .corpus import Corpus, Film, norm
from .models import Signals

POOL = 300
LAMBDA = 0.5
ALPHA = 0.5
K = 5


@dataclass
class Context:
    corpus: Corpus
    signals: Signals
    P: np.ndarray                                   # positive query vector
    text_vec: np.ndarray
    negatives: list[np.ndarray]
    cited: list[dict]                               # {"keys": {...norm titles}, "year": int|None, "point_id": str|None, "in_index": bool, "role": like|avoid}
    franchise_ids: set[str]
    franchise_names: list[str]
    avoid_genre_terms: list[str]
    coverage: dict = field(default_factory=dict)
    apply_filters: bool = False                     # positive filters (year, country, director, actor, rare terms), server side


def unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / (np.linalg.norm(v) or 1.0)


def build_context(corpus: Corpus, s: Signals) -> Context:
    lang = corpus.lang
    positive = s.positive_it if lang == "it" else s.positive_en
    desc = s.avoid_descriptions_it if lang == "it" else s.avoid_descriptions_en
    vecs = corpus.embed([positive] + list(desc))
    text_vec, desc_vecs = vecs[0], list(vecs[1:])
    cited, positives, negatives = [], [text_vec], list(desc_vecs)
    franchise_ids: set[str] = set()
    cov = {"refs": 0, "refs_in_index": 0}
    to_embed: list[tuple[str, str]] = []
    pending = []
    for role, refs in (("like", s.like_titles), ("avoid", s.avoid_titles)):
        for r in refs:
            f = corpus.resolve(r.title_it, r.title_original, r.year)
            cov["refs"] += 1
            cov["refs_in_index"] += 1 if f else 0
            cited.append({"keys": {norm(r.title_it), norm(r.title_original)} - {""}, "year": r.year, "point_id": f.point_id if f else None,
                          "in_index": f is not None, "role": role, "title": r.title_original})
            if f is not None:
                (positives if role == "like" else negatives).append(unit(f.vector))
                franchise_ids |= set(f.franchise_ids)
            else:
                pending.append((role, r.summary_it if lang == "it" else r.summary_en))
    if pending:
        for (role, _), v in zip(pending, corpus.embed([t for _, t in pending])):
            (positives if role == "like" else negatives).append(unit(v))
    # franchise names → franchise ids through the film that carries the name (NEW only: the old index has no franchise field)
    for name in s.avoid_franchise_names:
        if corpus.key == "new":
            f = corpus.resolve(name, name, None)
            if f:
                franchise_ids |= set(f.franchise_ids)
    P = unit(np.mean([unit(v) for v in positives], axis=0))
    keep = {norm(g) for g in (s.keep_genres_it if lang == "it" else s.keep_genres)}
    terms = [t for t in corpus.genre_terms(s.avoid_genres, s.avoid_genres_it) if norm(t) and not any(norm(t) in k or k in norm(t) for k in keep)]
    return Context(corpus, s, P, unit(text_vec), negatives, cited, franchise_ids, [n for n in s.avoid_franchise_names if norm(n)], terms, cov)


# ---- predicates
def is_cited(f: Film, ctx: Context) -> bool:
    keys = {norm(f.title), norm(f.original_title)} - {""}
    for c in ctx.cited:
        if c["point_id"] == f.point_id:
            return True
        if keys & c["keys"] and (not c["year"] or not f.year or abs(f.year - c["year"]) <= 1):
            return True
    return False


def franchise_name_hit(f: Film, ctx: Context) -> bool:
    titles = [norm(f.title), norm(f.original_title)]
    for n in ctx.franchise_names:
        words = norm(n).split()
        pat = r"\b" + r"\s+".join(w + ("s?" if i == len(words) - 1 else "") for i, w in enumerate(words)) + r"\b"
        import re
        if any(re.search(pat, t) for t in titles if t):
            return True
    return False


def franchise_id_hit(f: Film, ctx: Context) -> bool:
    return bool(set(f.franchise_ids) & ctx.franchise_ids)


def genre_hit(f: Film, ctx: Context) -> bool:
    gs = [norm(g) for g in f.genres]
    return any(norm(t) in g for t in ctx.avoid_genre_terms for g in gs)


def format_hit(f: Film, ctx: Context) -> bool:
    bad = set(ctx.signals.avoid_formats)
    return bool(bad and f.work_format and (f.work_format in bad or ("series" in bad and f.work_format == "tv_related")))


def _pool(ctx: Context, vector=None) -> list[Film]:
    flt = ctx.corpus.positive_filter(ctx.signals) if ctx.apply_filters else None
    return ctx.corpus.search(ctx.P if vector is None else vector, limit=POOL, flt=flt, with_vectors=True)


def _finish(films: list[Film], k: int, trace: dict) -> dict:
    return {"films": films[:k], "trace": trace}


def _penalised(pool: list[Film], ctx: Context, lam: float) -> list[Film]:
    if not ctx.negatives or not pool:
        return pool
    M = np.stack([unit(f.vector) for f in pool])
    N = np.stack(ctx.negatives)
    sc = M @ ctx.P - lam * np.max(M @ N.T, axis=1)
    out = []
    for i in np.argsort(-sc):
        f = pool[i]
        f.score = float(sc[i])
        out.append(f)
    return out


def s0(ctx, k=K):
    return _finish(_pool(ctx), k, {})


def s1(ctx, k=K):
    return _finish([f for f in _pool(ctx) if not is_cited(f, ctx)], k, {})


def s2n(ctx, k=K):
    return _finish([f for f in _pool(ctx) if not is_cited(f, ctx) and not franchise_name_hit(f, ctx)], k, {"franchise_names": ctx.franchise_names})


def s2f(ctx, k=K):
    if ctx.corpus.key != "new":
        return None
    return _finish([f for f in _pool(ctx) if not is_cited(f, ctx) and not franchise_id_hit(f, ctx)], k, {"franchise_ids": sorted(ctx.franchise_ids)})


def s3(ctx, k=K):
    return _finish(_penalised(_pool(ctx), ctx, LAMBDA), k, {"lambda": LAMBDA, "negatives": len(ctx.negatives)})


def s3b(ctx, k=K):
    if not ctx.negatives:
        return s0(ctx, k)
    q = unit(ctx.P - ALPHA * unit(np.mean(ctx.negatives, axis=0)))
    return _finish(_pool(ctx, q), k, {"alpha": ALPHA})


def s4(ctx, k=K):
    return _finish([f for f in _pool(ctx) if not genre_hit(f, ctx) and not format_hit(f, ctx)], k, {"avoid_genre_terms": ctx.avoid_genre_terms})


def _combined_pool(ctx: Context) -> list[Film]:
    pool = [f for f in _pool(ctx) if not is_cited(f, ctx) and not franchise_name_hit(f, ctx) and not genre_hit(f, ctx) and not format_hit(f, ctx)
            and not (ctx.corpus.key == "new" and franchise_id_hit(f, ctx))]
    return _penalised(pool, ctx, LAMBDA)


def s5(ctx, k=K):
    return _finish(_combined_pool(ctx), k, {"lambda": LAMBDA, "negatives": len(ctx.negatives), "franchise_ids": sorted(ctx.franchise_ids),
                                            "avoid_genre_terms": ctx.avoid_genre_terms})


class Order(BaseModel):
    indices: list[int]


RERANK = ("You rank candidate films for a recommendation request. Use your own knowledge of every film. Best = satisfies ALL the wanted traits, genre and "
          "the explicit exclusions of the request. A candidate that shows ANY trait the user wants to avoid, belongs to an excluded franchise or is a cited "
          "film goes last, even if it is otherwise a perfect match for the positive part. Do not prefer a film because it is famous. "
          "Return ALL candidate indices, best first, each once.")


def rerank_llm(ctx, request: str, *, pool: int = 25, plot_chars: int = 450, model: str = llm.LLM_MODEL, effort: str | None = None, top: int | None = None):
    base = _combined_pool(ctx)[:pool]
    lines = "\n".join(f"[{i}] {f.label()} | {', '.join(f.genres[:4])} | {f.plot[:plot_chars]}" for i, f in enumerate(base))
    s = ctx.signals
    prompt = (f"Request (Italian): {request}\nWanted: {s.positive_en}\nAvoid traits: {'; '.join(s.avoid_descriptions_en) or '-'}\n"
              f"Avoid franchises: {', '.join(s.avoid_franchise_names) or '-'}\nCited films (exclude): "
              f"{', '.join(c['title'] for c in ctx.cited) or '-'}\n\nCandidates:\n{lines}")
    instr = RERANK if not top else RERANK.replace('Return ALL candidate indices, best first, each once.', f'Return only the {top} best candidate indices, best first, each once.')
    o = llm.structured(Order, instr, prompt, model=model, effort=effort)
    seen, order = set(), []
    for i in o.indices:
        if 0 <= i < len(base) and i not in seen:
            seen.add(i); order.append(i)
    order += [i for i in range(len(base)) if i not in seen]
    return [base[i] for i in order]


def s6(ctx, k=K, request: str = "", pool: int = 25, **kw):
    return _finish(rerank_llm(ctx, request, pool=pool, **kw), k, {"reranked_pool": pool, **{x: str(v) for x, v in kw.items()}})


def _with_filters(fn):
    def wrapped(ctx, k=K, **kw):
        ctx.apply_filters = True
        try:
            return fn(ctx, k, **kw) if kw else fn(ctx, k)
        finally:
            ctx.apply_filters = False
    return wrapped


def _v(**kw):
    return lambda ctx, k=K, request="": s6(ctx, k, request, **kw)


VARIANTS = {   # latency / quality variants of the LLM reorder
    "V1": _v(effort="low"), "V2": _v(effort="none"),
    "V3": _v(model="gpt-5.4-mini"), "V4": _v(model="gpt-5.4-nano"), "V5": _v(model="gpt-4.1-mini"),
    "V6": _v(effort="low", pool=15, plot_chars=300), "V7": _v(effort="low", pool=40), "V8": _v(effort="low", plot_chars=1200),
    "V9": _v(effort="low", pool=50, plot_chars=600), "V10": _v(model="gpt-5.4-mini", effort="low"),
    "W1": _v(effort="none", pool=40), "W2": _v(effort="none", pool=50, plot_chars=600), "W3": _v(model="gpt-5.4-mini", pool=40),
    "W4": _v(effort="none", pool=50, plot_chars=600, top=8), "W5": _v(effort="low", pool=50, plot_chars=600, top=8),
    "W6": _v(model="gpt-5.4-mini", pool=50, plot_chars=600, top=8),
    "X1": _v(model="gpt-5.6-sol", effort="none", pool=40), "X2": _v(model="gpt-5.6-terra", effort="none", pool=40),
    "X3": _v(model="gpt-5.4", effort="none", pool=40), "X4": _v(model="gpt-5.6-sol", effort="none", pool=40, plot_chars=700),
    "X5": _v(model="gpt-5.6-sol", effort="none", pool=40, plot_chars=1500), "X6": _v(model="gpt-5.6-sol", effort="none", pool=50, plot_chars=700),
    "X7": _v(model="gpt-5.6-sol", effort="none", pool=40, plot_chars=700, top=8), "X8": _v(model="gpt-5.6-sol", effort="none", pool=30, plot_chars=700),
}

STRATEGIES = {**VARIANTS, "S6w": lambda ctx, k=K, request="": s6(ctx, k, request, 50), "S5f": _with_filters(s5), "S6f": _with_filters(s6), "S0": s0, "S1": s1, "S2n": s2n, "S2f": s2f, "S3": s3, "S3b": s3b, "S4": s4, "S5": s5, "S6": s6}
